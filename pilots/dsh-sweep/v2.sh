#!/usr/bin/env bash
# The DSH sweep's second pass: 5 repeats per cell on every catalogue model except the held-out
# judges. A fixed list of filtered `sweep.sh` calls, never an unfiltered one; sweep.sh itself
# resumes, skips what a study records and keeps every run's log.
#
#     pilots/dsh-sweep/v2.sh 1a   # the models not run yet, at REPEATS=5
#     pilots/dsh-sweep/v2.sh 1b   # 2 more repeats on every recorded (model, thinking), pooled to 5
#
# `leaderboard` pools every run of one suite hash per model and thinking, so a recorded 3-repeat
# run and a new 2-repeat run make 5; the days between them are the run-to-run noise check.
#
# Held out of both phases: gpt-oss:120b (gen-data-dict's judge) and nemotron-3.5-lightning (the
# second judge of the maintainer arm, pilots/dsh-maint/). gemma4:31b at --thinking default is
# recorded on curate only: on archive and bids it exceeded the 600 s unit timeout, and stays
# unrecorded there by decision, so phase 1b runs it with SUITES=curate.
#
# DRY_RUN=1 prints every eval without running one.

set -uo pipefail

HERE=$(dirname "$(realpath "$0")")
SWEEP=$HERE/sweep.sh

# The new models, smallest and fastest first; llama3.3 (70B dense) last, alone, for its length.
NEW=(llama3.1:8b glm-4.7-flash:latest mistral-small3.2:24b granite4.1:30b)
# The models recorded at 3 repeats in the first pass, in its order.
OLD_DEFAULT=(qwen3:1.7b llama3.2:3b gemma4:latest granite4.1:8b gpt-oss:20b qwen3:30b-a3b
  granite4.1:3b ministral-3:3b qwen3-coder:30b)
OLD_OFF=(qwen3:1.7b gemma4:latest gpt-oss:20b qwen3:30b-a3b gemma4:31b qwen3.8:latest)
JUDGES=(gpt-oss:120b nemotron-3.5-lightning:latest)

step() {
  # step REPEATS PHASE "MODELS" [SUITES]; an empty SUITES is every suite.
  local repeats=$1 phase=$2 models=$3 suites=${4:-}
  echo "== v2: sweep.sh $phase, REPEATS=$repeats, MODELS=$models${suites:+, SUITES=$suites}"
  REPEATS=$repeats MODELS=$models SUITES=$suites "$SWEEP" "$phase"
}

judges_served() {
  local judge failed=0
  for judge in "${JUDGES[@]}"; do
    if (cd "$HERE" && uv run --quiet python sweep_state.py served \
      "$(b=${BASE_URL:-http://localhost:11434/v1}; echo "${b%/v1}")" "$judge") >/dev/null 2>&1; then
      :
    else
      echo "== v2: judge $judge is not served"
      failed=1
    fi
  done
  return "$failed"
}

case ${1:-} in
  1a)
    judges_served || exit 1
    step 5 preflight "${NEW[*]} qwen3.8:latest llama3.3:latest" || exit 1
    step 5 default "${NEW[*]} qwen3.8:latest" || exit 1
    # qwen3.8 at off is recorded at 3 repeats; phase 1b adds its 2.
    step 5 off "${NEW[*]}" || exit 1
    step 5 default llama3.3:latest || exit 1
    ;;
  1b)
    step 2 default "${OLD_DEFAULT[*]}" || exit 1
    step 2 default gemma4:31b curate || exit 1
    step 2 off "${OLD_OFF[*]}" || exit 1
    ;;
  *)
    sed -n '2,8p' "$0" | sed 's/^# \{0,1\}//'
    exit 2
    ;;
esac
echo "== v2: phase $1 finished"
