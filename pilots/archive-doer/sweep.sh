#!/usr/bin/env bash
# The DSH pilot's model sweep (add-dsh-pilot 4.1, 4.3, 4.4): the archive-doer suite on every model,
# one eval per model, OFF and INJECTED, sequentially, smallest and fastest first, llama3.3 last.
#
#     pilots/archive-doer/sweep.sh preflight   # 4.1: preflight every model, run no units
#     pilots/archive-doer/sweep.sh default     # 4.3: every model at --thinking default
#     pilots/archive-doer/sweep.sh off         # 4.4: the models that can think, at --thinking off
#     pilots/archive-doer/sweep.sh all         # default, then off
#
# Meant to run unattended, e.g. overnight in tmux:
#
#     tmux new -s dsh \
#       'pilots/archive-doer/sweep.sh preflight; pilots/archive-doer/sweep.sh all; exec bash'
#
# It holds a systemd sleep/idle inhibitor for its whole length, so the machine does not suspend
# mid-run, and stops at the first Ctrl-C. Each complete run is appended to the study with
# `wikiskill findings add ... --role sweep`, so `docs/pilots/dsh/findings.toml` is the run log: a
# (model, thinking) pair already recorded there is skipped, and rerunning the script after a crash
# or a stop resumes at the first unfinished model.
#
# A run is complete when every unit has a result and at most MAX_NOT_RUN of them did not run
# (`infra_error`, `skipped`). An incomplete run is not recorded, its directory is left for reading,
# and it is retried on the next invocation. A complete run that `findings add` cannot record is kept
# in $SWEEP_LOGS/unrecorded and added at the start of the next invocation, never rerun.
#
# `preflight` marks each model that fails under $SWEEP_LOGS/preflight/; the sweep skips a marked
# model, saying so, until a later `preflight` passes it. Whether a model can think is asked of the
# server (`/api/show`), and the order below must list exactly the models in pilots/models.toml.
#
# Environment: SUITE (default pilots/archive-doer/suite.yaml), REPEATS (10, the design's; the suite
# says 3 and keeps its hash), MAX_NOT_RUN (0), STUDY (docs/pilots/dsh), COLLECTION (dsh-archive),
# BASE_URL (http://localhost:11434/v1), MODELS (space-separated, overrides the order below),
# DRY_RUN=1 (print what would run). Logs go to $SWEEP_LOGS, one file per model and setting.

set -uo pipefail

SELF=$(realpath "$0")
HERE=$(dirname "$SELF")
ROOT=$(git -C "$HERE" rev-parse --show-toplevel) || exit 2
cd "$ROOT" || exit 2

SUITE=${SUITE:-pilots/archive-doer/suite.yaml}
REPEATS=${REPEATS:-10}
MAX_NOT_RUN=${MAX_NOT_RUN:-0}
COLLECTION=${COLLECTION:-dsh-archive}
BASE_URL=${BASE_URL:-http://localhost:11434/v1}
OLLAMA_URL=${BASE_URL%/v1}
STUDY=${STUDY:-docs/pilots/dsh}
CATALOGUE=pilots/models.toml
SWEEP_LOGS=${SWEEP_LOGS:-${XDG_STATE_HOME:-$HOME/.local/state}/wikiskill/dsh-sweep}
DRY_RUN=${DRY_RUN:-}

# The design's order: smallest and fastest first, so each finished run is a complete cell set.
# gpt-oss:120b is MoE and decodes faster than llama3.3, a 70B dense model, which runs last.
ORDER=(
  qwen2.5-coder:1.5b
  qwen3:1.7b
  granite4.1:3b
  ministral-3:3b
  mistral:latest
  gemma4:latest
  granite4.1:8b
  gpt-oss:20b
  mistral-small3.2:24b
  qwen3.8:latest
  granite4.1:30b
  glm-4.7-flash:latest
  qwen3:30b-a3b
  qwen3-coder:30b
  gemma4:31b
  olmo-3:32b
  nemotron-3.5-lightning:latest
  gpt-oss:120b
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

# A Ctrl-C reaches eval too; once it returns, stop here rather than start the next model.
trap 'say "interrupted; rerun to resume"; exit 130' INT TERM

if ! drift=$(state catalogue "$CATALOGUE" "${ORDER[@]}"); then
  say "the sweep's order and $CATALOGUE differ:"
  say "$drift"
  exit 2
fi
if [[ -n ${MODELS:-} ]]; then
  read -r -a ORDER <<<"$MODELS"
fi

slug() { printf '%s' "${1//[:\/]/_}"; }

eval_args() {
  printf '%s\n' --suite "$SUITE" --collection "$COLLECTION" --models "ollama/$1" \
    --condition off,injected --base-url "$BASE_URL" --repeats "$REPEATS"
}

preflight() {
  local model log mark status
  for model in "${ORDER[@]}"; do
    mapfile -t args < <(eval_args "$model")
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
}

# Record the runs a previous invocation finished but could not add to the study.
record_pending() {
  local run_id left=()
  [[ -s $UNRECORDED ]] || return 0
  while read -r run_id; do
    [[ -n $run_id ]] || continue
    if grep -qF "\"$run_id\"" "$STUDY/findings.toml" ||
      uv run wikiskill findings add "$STUDY" "$run_id" --role sweep; then
      say "recorded $run_id, finished earlier"
    else
      left+=("$run_id")
    fi
  done <"$UNRECORDED"
  printf '%s\n' "${left[@]}" | sed '/^$/d' >"$UNRECORDED"
  if [[ -s $UNRECORDED ]]; then
    say "cannot record $(tr '\n' ' ' <"$UNRECORDED")in $STUDY; fix findings.toml, then rerun"
    exit 1
  fi
}

sweep() {
  local thinking=$1 model log run_id status finished why
  if ! finished=$(state recorded "$STUDY"); then
    say "cannot read $STUDY/findings.toml; stopping"
    exit 1
  fi
  for model in "${ORDER[@]}"; do
    if grep -qxF "ollama/$model"$'\t'"$thinking" <<<"$finished"; then
      say "skip $model at --thinking $thinking: already in the study"
      continue
    fi
    if [[ -f "$SWEEP_LOGS/preflight/$(slug "$model").failed" ]]; then
      say "skip $model: failed preflight ($(cat "$SWEEP_LOGS/preflight/$(slug "$model").failed"))"
      continue
    fi
    if [[ $thinking == off ]]; then
      state thinks "$OLLAMA_URL" "$model"
      case $? in
        0) ;;
        1) say "skip $model at --thinking off: the server lists no thinking"; continue ;;
        *) say "cannot ask the server whether $model thinks; stopping"; exit 1 ;;
      esac
    fi
    mapfile -t args < <(eval_args "$model")
    args+=(--thinking "$thinking")
    if [[ -n $DRY_RUN ]]; then
      say "would run: wikiskill eval ${args[*]}"
      continue
    fi
    log="$SWEEP_LOGS/$STAMP-$(slug "$model")-$thinking.log"
    say "start $model at --thinking $thinking (log $log)"
    uv run wikiskill eval "${args[@]}" 2>&1 | tee "$log"
    status=${PIPESTATUS[0]}
    run_id=$(awk '$1 == "run" { print $2; exit }' "$log")
    # Free the GPU before the next model; Ollama would otherwise keep this one loaded for minutes.
    ollama stop "$model" >/dev/null 2>&1 || true
    if [[ -z $run_id ]]; then
      say "FAILED $model at --thinking $thinking: exit $status before a run began"
      continue
    fi
    if ! why=$(state finished "$COLLECTION" "$run_id" "$MAX_NOT_RUN"); then
      say "INCOMPLETE $model at --thinking $thinking: run $run_id, exit $status: $why; not recorded"
      continue
    fi
    if uv run wikiskill findings add "$STUDY" "$run_id" --role sweep; then
      say "done $model at --thinking $thinking: run $run_id recorded"
    else
      printf '%s\n' "$run_id" >>"$UNRECORDED"
      say "done $model at --thinking $thinking: run $run_id NOT recorded; kept in $UNRECORDED"
      exit 1
    fi
  done
}

say "sweep $PHASE: suite $SUITE x$REPEATS, collection $COLLECTION, ${#ORDER[@]} model(s)"
say "logs $SWEEP_LOGS"
[[ -n $DRY_RUN ]] || record_pending
case $PHASE in
  preflight) preflight ;;
  default) sweep default ;;
  off) sweep off ;;
  all) sweep default && sweep off ;;
esac
say "sweep $PHASE finished"
