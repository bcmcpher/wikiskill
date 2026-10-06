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
#     tmux new -s dsh 'pilots/archive-doer/sweep.sh all; exec bash'
#
# It holds a systemd sleep/idle inhibitor for its whole length, so the machine does not suspend
# mid-run. Each finished run is appended to the study with `wikiskill findings add ... --role sweep`,
# so `docs/pilots/dsh/findings.toml` is the run log: a (model, thinking) pair already recorded there
# is skipped, and rerunning the script after a crash or a stop resumes at the first unfinished model.
# A run that scores no unit (a failed preflight, an interruption) is not recorded, and is retried
# on the next invocation. Logs go to $SWEEP_LOGS, one file per model and setting.
#
# Environment: SUITE (default pilots/archive-doer/suite.yaml), COLLECTION (dsh-archive), BASE_URL
# (http://localhost:11434/v1), MODELS (space-separated, overrides the list below), DRY_RUN=1 (print
# what would run). Run from the repository root of the results/dsh-pilot branch.

set -uo pipefail

ROOT=$(git rev-parse --show-toplevel) || exit 2
cd "$ROOT" || exit 2

SUITE=${SUITE:-pilots/archive-doer/suite.yaml}
COLLECTION=${COLLECTION:-dsh-archive}
BASE_URL=${BASE_URL:-http://localhost:11434/v1}
STUDY=docs/pilots/dsh
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
  glm-4.7-flash
  qwen3:30b-a3b
  qwen3-coder:30b
  gemma4:31b
  olmo-3:32b
  nemotron-3.5-lightning:latest
  gpt-oss:120b
  llama3.3:latest
)

# The models whose server says they can think (design, "Thinking"; `ollama show` agrees).
THINKERS=(
  qwen3:1.7b qwen3.8:latest qwen3:30b-a3b
  gemma4:latest gemma4:31b
  gpt-oss:20b gpt-oss:120b
  glm-4.7-flash olmo-3:32b nemotron-3.5-lightning:latest
)

usage() {
  sed -n '2,9p' "$0" | sed 's/^# \{0,1\}//'
  exit 2
}

[[ $# -eq 1 ]] || usage
PHASE=$1
case $PHASE in preflight | default | off | all) ;; *) usage ;; esac

if [[ -z ${SWEEP_INHIBITED:-} && -z $DRY_RUN ]] && command -v systemd-inhibit >/dev/null; then
  SWEEP_INHIBITED=1 exec systemd-inhibit --what=sleep:idle --who=wikiskill \
    --why="DSH model sweep" "$0" "$@"
fi

if [[ -n ${MODELS:-} ]]; then
  read -r -a ORDER <<<"$MODELS"
fi

mkdir -p "$SWEEP_LOGS"
STAMP=$(date +%Y%m%d-%H%M%S)

say() { printf '%s  %s\n' "$(date '+%F %T')" "$*" | tee -a "$SWEEP_LOGS/sweep-$STAMP.log"; }

thinks() {
  local model=$1 m
  for m in "${THINKERS[@]}"; do [[ $m == "$model" ]] && return 0; done
  return 1
}

# The (model, thinking) pairs the study already holds as sweep runs, one per line, tab-separated.
done_pairs() {
  uv run --quiet python - "$STUDY" <<'PY'
import json
import sys

from wikiskill import compare, findings

study = findings.load(sys.argv[1])
for run in study.runs:
    if run.role != "sweep":
        continue
    bundled = study.bundled(run) / "run.json"
    if bundled.is_file():
        manifest = json.loads(bundled.read_text(encoding="utf-8"))
    else:
        manifest = compare.load_run(study.collection or "", run.path or run.id).manifest
    thinking = (manifest.get("options") or {}).get("thinking", "default")
    for model in manifest.get("models") or []:
        print(f"{model}\t{thinking}")
PY
}

eval_args() {
  local model=$1
  printf '%s\n' --suite "$SUITE" --collection "$COLLECTION" --models "ollama/$model" \
    --condition off,injected --base-url "$BASE_URL"
}

preflight() {
  local model log
  for model in "${ORDER[@]}"; do
    log="$SWEEP_LOGS/preflight-$STAMP-${model//[:\/]/_}.log"
    mapfile -t args < <(eval_args "$model")
    if [[ -n $DRY_RUN ]]; then
      say "would run: wikiskill eval ${args[*]} --preflight-only"
      continue
    fi
    say "preflight $model"
    uv run wikiskill eval "${args[@]}" --preflight-only 2>&1 | tee "$log"
    say "preflight $model: exit ${PIPESTATUS[0]} (log $log)"
  done
}

sweep() {
  local thinking=$1 model log run_id status finished
  finished=$(done_pairs) || { say "cannot read $STUDY/findings.toml; stopping"; exit 1; }
  for model in "${ORDER[@]}"; do
    if [[ $thinking == off ]] && ! thinks "$model"; then
      continue
    fi
    if grep -qxF "ollama/$model"$'\t'"$thinking" <<<"$finished"; then
      say "skip $model at --thinking $thinking: already in the study"
      continue
    fi
    mapfile -t args < <(eval_args "$model")
    args+=(--thinking "$thinking")
    if [[ -n $DRY_RUN ]]; then
      say "would run: wikiskill eval ${args[*]}"
      continue
    fi
    log="$SWEEP_LOGS/$STAMP-${model//[:\/]/_}-$thinking.log"
    say "start $model at --thinking $thinking (log $log)"
    uv run wikiskill eval "${args[@]}" 2>&1 | tee "$log"
    status=${PIPESTATUS[0]}
    run_id=$(awk '$1 == "run" { print $2; exit }' "$log")
    # Free the GPU before the next model; Ollama would otherwise keep this one loaded for minutes.
    ollama stop "$model" >/dev/null 2>&1 || true
    if [[ $status -ne 0 || -z $run_id ]]; then
      say "FAILED $model at --thinking $thinking: exit $status, run ${run_id:-none}; not recorded"
      continue
    fi
    if uv run wikiskill findings add "$STUDY" "$run_id" --role sweep; then
      say "done $model at --thinking $thinking: run $run_id recorded"
    else
      say "done $model at --thinking $thinking: run $run_id NOT recorded; add it by hand"
    fi
  done
}

say "sweep $PHASE: suite $SUITE, collection $COLLECTION, ${#ORDER[@]} model(s), logs $SWEEP_LOGS"
case $PHASE in
  preflight) preflight ;;
  default) sweep default ;;
  off) sweep off ;;
  all) sweep default && sweep off ;;
esac
say "sweep $PHASE finished"
