#!/usr/bin/env bash
# The DSH pilot's model sweep (add-dsh-pilot 4.1, 4.3, 4.4): every suite below on every model, one
# eval per (suite, model), OFF and INJECTED, sequentially, smallest and fastest model first.
#
#     pilots/dsh-sweep/sweep.sh preflight   # 4.1: preflight every model, run no units
#     pilots/dsh-sweep/sweep.sh default     # 4.3: every model at --thinking default
#     pilots/dsh-sweep/sweep.sh off         # 4.4: the models that can think, at --thinking off
#     pilots/dsh-sweep/sweep.sh all         # default, then off
#
# Meant to run unattended, e.g. overnight in tmux:
#
#     tmux new -s dsh \
#       'pilots/dsh-sweep/sweep.sh preflight; pilots/dsh-sweep/sweep.sh all; exec bash'
#
# It holds a systemd sleep/idle inhibitor for its whole length, so the machine does not suspend
# mid-run, and stops at the first Ctrl-C. Each suite has its own study, and each complete run is
# appended to it with `wikiskill findings add ... --role sweep`, so a study's `findings.toml` is its
# run log: a (suite, model, thinking) already recorded there at the same repeats is skipped, and
# rerunning the script after a crash or a stop resumes at the first unfinished one. A model runs
# every suite before the next model loads.
#
# A run is complete when every unit has a result and at most MAX_NOT_RUN of them did not run
# (`infra_error`, `skipped`). An incomplete run is not recorded, its directory is left for reading,
# and it is retried on the next invocation. A complete run that `findings add` cannot record is kept
# in $SWEEP_LOGS/unrecorded and added at the start of the next invocation, never rerun.
#
# `preflight` marks each model that fails under $SWEEP_LOGS/preflight/; the sweep skips a marked
# model, saying so, until a later `preflight` passes it. Whether a model can think is asked of the
# server (`/api/show`). A suite's judge (`[roles.judge]` in its collection) is never run as a model
# under test on that suite; `preflight` checks the server has it. Every model in the order must be
# in pilots/models.toml, and every program a suite's tasks require must be on their PATH: a task
# without one is `skipped`, and its run could never be complete.
#
# Environment: SUITES (space-separated names from the table below; all by default), REPEATS (3),
# MAX_NOT_RUN (0), BASE_URL (http://localhost:11434/v1), MODELS (space-separated, overrides the
# order below), DRY_RUN=1 (print what would run). Logs go to $SWEEP_LOGS, one file per run.

set -uo pipefail

SELF=$(realpath "$0")
HERE=$(dirname "$SELF")
ROOT=$(git -C "$HERE" rev-parse --show-toplevel) || exit 2
cd "$ROOT" || exit 2

REPEATS=${REPEATS:-3}
MAX_NOT_RUN=${MAX_NOT_RUN:-0}
BASE_URL=${BASE_URL:-http://localhost:11434/v1}
OLLAMA_URL=${BASE_URL%/v1}
CATALOGUE=pilots/models.toml
SWEEP_LOGS=${SWEEP_LOGS:-${XDG_STATE_HOME:-$HOME/.local/state}/wikiskill/dsh-sweep}
DRY_RUN=${DRY_RUN:-}

# name, suite, collection, study.
declare -A SUITE COLLECTION STUDY
SUITE_ORDER=(archive bids curate)
SUITE[archive]=pilots/archive-doer/suite.yaml COLLECTION[archive]=dsh-archive
STUDY[archive]=docs/pilots/dsh
SUITE[bids]=pilots/bids-doer/suite.yaml COLLECTION[bids]=dsh-bids
STUDY[bids]=docs/pilots/dsh-bids
SUITE[curate]=pilots/gen-data-dict/suite.yaml COLLECTION[curate]=dsh-curate
STUDY[curate]=docs/pilots/dsh-curate

# Scaled back from the design's 18 models on 2026-10-06, as the suites grew to three: two to three
# per family across the size range, dense and MoE, smallest and fastest first, llama3.3 (70B dense)
# last. gpt-oss:120b is left out: it judges gen-data-dict.
ORDER=(
  qwen3:1.7b
  llama3.2:3b
  gemma4:latest
  granite4.1:8b
  gpt-oss:20b
  qwen3:30b-a3b
  gemma4:31b
  llama3.3:latest
)

usage() {
  sed -n '2,8p' "$SELF" | sed 's/^# \{0,1\}//'
  exit 2
}

[[ $# -eq 1 ]] || usage
PHASE=$1
case $PHASE in preflight | default | off | all) ;; *) usage ;; esac

if [[ -z ${SWEEP_INHIBITED:-} && -z $DRY_RUN ]] && command -v systemd-inhibit >/dev/null; then
  SWEEP_INHIBITED=1 exec systemd-inhibit --what=sleep:idle --who=wikiskill \
    --why="DSH model sweep" "$SELF" "$@"
fi

mkdir -p "$SWEEP_LOGS/preflight"
STAMP=$(date +%Y%m%d-%H%M%S)
UNRECORDED=$SWEEP_LOGS/unrecorded

say() { printf '%s  %s\n' "$(date '+%F %T')" "$*" | tee -a "$SWEEP_LOGS/sweep-$STAMP.log"; }
state() { uv run --quiet python "$HERE/sweep_state.py" "$@"; }

# A Ctrl-C reaches eval too; once it returns, stop here rather than start the next run.
trap 'say "interrupted; rerun to resume"; exit 130' INT TERM

if [[ -n ${MODELS:-} ]]; then
  read -r -a ORDER <<<"$MODELS"
fi
if [[ -n ${SUITES:-} ]]; then
  read -r -a SUITE_ORDER <<<"$SUITES"
fi
for name in "${SUITE_ORDER[@]}"; do
  if [[ -z ${SUITE[$name]:-} ]]; then
    say "unknown suite $name; known: ${!SUITE[*]}"
    exit 2
  fi
  if ! uv run --quiet wikiskill collection check "${COLLECTION[$name]}" >/dev/null 2>&1; then
    say "collection ${COLLECTION[$name]} does not check; copy its manifest from pilots/ to"
    say "${XDG_CONFIG_HOME:-~/.config}/wikiskill/collections/ and run wikiskill collection check"
    exit 2
  fi
done
if ! missing=$(state catalogue "$CATALOGUE" "${ORDER[@]}"); then
  say "$missing"
  exit 2
fi
suite_files=()
for name in "${SUITE_ORDER[@]}"; do suite_files+=("${SUITE[$name]}"); done
if ! missing=$(state requires "${suite_files[@]}"); then
  say "$missing"
  say "install what is missing (see the suite's comments), or leave the suite out with SUITES"
  exit 2
fi

slug() { printf '%s' "${1//[:\/]/_}"; }

eval_args() {
  printf '%s\n' --suite "${SUITE[$1]}" --collection "${COLLECTION[$1]}" --models "ollama/$2" \
    --condition off,injected --base-url "$BASE_URL" --repeats "$REPEATS"
}

# Model availability does not depend on the suite, so preflight runs once per model, on the first.
preflight() {
  local model log mark status
  for model in "${ORDER[@]}"; do
    mapfile -t args < <(eval_args "${SUITE_ORDER[0]}" "$model")
    if [[ -n $DRY_RUN ]]; then
      say "would run: wikiskill eval ${args[*]} --preflight-only"
      continue
    fi
    log="$SWEEP_LOGS/preflight-$STAMP-$(slug "$model").log"
    mark="$SWEEP_LOGS/preflight/$(slug "$model").failed"
    say "preflight $model"
    uv run wikiskill eval "${args[@]}" --preflight-only 2>&1 | tee "$log"
    status=${PIPESTATUS[0]}
    if [[ $status -eq 0 ]]; then
      rm -f "$mark"
      say "preflight $model: ok"
    else
      printf '%s\n' "$log" >"$mark"
      say "preflight $model: FAILED, the sweep will skip it (log $log)"
    fi
  done
  local name judge failed=0
  for name in "${SUITE_ORDER[@]}"; do
    while read -r judge; do
      [[ -n $judge ]] || continue
      if [[ -n $DRY_RUN ]]; then
        say "would check the server has $name's judge $judge"
      elif state served "$OLLAMA_URL" "$judge" >/dev/null; then
        say "preflight $name's judge $judge: served"
      else
        say "preflight $name's judge $judge: NOT served; every $name run would fail"
        failed=1
      fi
    done < <(state judges "${COLLECTION[$name]}")
  done
  return "$failed"
}

# Record the runs a previous invocation finished but could not add to their study.
record_pending() {
  local study run_id left=()
  [[ -s $UNRECORDED ]] || return 0
  while read -r study run_id; do
    # A line with one field is the archive-only sweep's: a bare run id, always docs/pilots/dsh's.
    if [[ -z $run_id && -n $study ]]; then
      run_id=$study study=${STUDY[archive]}
    fi
    [[ -n $run_id ]] || continue
    if grep -qF "\"$run_id\"" "$study/findings.toml" ||
      uv run wikiskill findings add "$study" "$run_id" --role sweep; then
      say "recorded $run_id in $study, finished earlier"
    else
      left+=("$study $run_id")
    fi
  done <"$UNRECORDED"
  printf '%s\n' "${left[@]}" | sed '/^$/d' >"$UNRECORDED"
  if [[ -s $UNRECORDED ]]; then
    say "cannot record $(tr '\n' ' ' <"$UNRECORDED"); fix those findings.toml files, then rerun"
    exit 1
  fi
}

# One (suite, model, thinking) run: returns 0 when it is recorded or skipped, 1 when it is not.
run_one() {
  local name=$1 model=$2 thinking=$3 log run_id status why
  mapfile -t args < <(eval_args "$name" "$model")
  args+=(--thinking "$thinking")
  if [[ -n $DRY_RUN ]]; then
    say "would run: wikiskill eval ${args[*]}"
    return 0
  fi
  log="$SWEEP_LOGS/$STAMP-$name-$(slug "$model")-$thinking.log"
  say "start $name on $model at --thinking $thinking (log $log)"
  uv run wikiskill eval "${args[@]}" 2>&1 | tee "$log"
  status=${PIPESTATUS[0]}
  run_id=$(awk '$1 == "run" { print $2; exit }' "$log")
  if [[ -z $run_id ]]; then
    say "FAILED $name on $model at --thinking $thinking: exit $status before a run began"
    return 1
  fi
  if ! why=$(state finished "${COLLECTION[$name]}" "$run_id" "$MAX_NOT_RUN"); then
    say "INCOMPLETE $name on $model at --thinking $thinking: run $run_id, exit $status: $why"
    return 1
  fi
  if uv run wikiskill findings add "${STUDY[$name]}" "$run_id" --role sweep; then
    say "done $name on $model at --thinking $thinking: run $run_id recorded"
  else
    printf '%s %s\n' "${STUDY[$name]}" "$run_id" >>"$UNRECORDED"
    ollama stop "$model" >/dev/null 2>&1 || true
    say "done $name on $model at --thinking $thinking: run $run_id NOT recorded ($UNRECORDED)"
    exit 1
  fi
}

sweep() {
  local thinking=$1 model name unload
  declare -A recorded judges
  for name in "${SUITE_ORDER[@]}"; do
    if ! recorded[$name]=$(state recorded "${STUDY[$name]}"); then
      say "cannot read ${STUDY[$name]}/findings.toml; stopping"
      exit 1
    fi
    if ! judges[$name]=$(state judges "${COLLECTION[$name]}"); then
      say "cannot read ${COLLECTION[$name]}'s judge; stopping"
      exit 1
    fi
  done
  local todo
  for model in "${ORDER[@]}"; do
    if [[ -f "$SWEEP_LOGS/preflight/$(slug "$model").failed" ]]; then
      say "skip $model: failed preflight ($(cat "$SWEEP_LOGS/preflight/$(slug "$model").failed"))"
      continue
    fi
    todo=()
    for name in "${SUITE_ORDER[@]}"; do
      if grep -qxF "ollama/$model"$'\t'"$thinking"$'\t'"$REPEATS" <<<"${recorded[$name]}"; then
        say "skip $name on $model at --thinking $thinking: already in ${STUDY[$name]}"
      elif grep -qxF "${model,,}" <<<"${judges[$name]}"; then
        say "skip $name on $model: it judges ${COLLECTION[$name]}"
      else
        todo+=("$name")
      fi
    done
    [[ ${#todo[@]} -gt 0 ]] || continue
    if [[ $thinking == off ]]; then
      state thinks "$OLLAMA_URL" "$model"
      case $? in
        0) ;;
        1) say "skip $model at --thinking off: the server lists no thinking"; continue ;;
        *) say "cannot ask the server whether $model thinks; stopping"; exit 1 ;;
      esac
    fi
    for name in "${todo[@]}"; do
      run_one "$name" "$model" "$thinking"
    done
    # Free the GPU before the next model, judges included; Ollama would otherwise keep them loaded
    # for minutes beside the next model.
    if [[ -z $DRY_RUN ]]; then
      for unload in "$model" $(printf '%s\n' "${judges[@]}" | sort -u); do
        ollama stop "$unload" >/dev/null 2>&1 || true
      done
    fi
  done
}

say "sweep $PHASE: suites ${SUITE_ORDER[*]} x$REPEATS, ${#ORDER[@]} model(s)"
say "logs $SWEEP_LOGS"
[[ -n $DRY_RUN ]] || record_pending
case $PHASE in
  preflight) preflight || exit 1 ;;
  default) sweep default ;;
  off) sweep off ;;
  all) sweep default && sweep off ;;
esac
say "sweep $PHASE finished"
