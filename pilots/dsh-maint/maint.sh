#!/usr/bin/env bash
# The DSH pilot's maintainer arm: each maintainer model reviews the same evidence and proposes
# (or declines) one patch per component; each patch is evaluated as a candidate on a panel of
# models, replayed against that model's sweep run, and scored blind by two held-out judges.
#
#     pilots/dsh-maint/maint.sh setup       # one sandbox per maintainer, no model runs
#     pilots/dsh-maint/maint.sh check       # every sandbox's review prompt is byte-identical
#     pilots/dsh-maint/maint.sh propose     # review, then refine, per maintainer and component
#     pilots/dsh-maint/maint.sh candidates  # INJECTED candidate evals on the panel, then replay
#     pilots/dsh-maint/maint.sh judge       # both judges score every proposal, blind
#     pilots/dsh-maint/maint.sh table       # docs/pilots/dsh-maint/tables/maint.{csv,md}
#     pilots/dsh-maint/maint.sh all         # setup, check, propose, candidates, judge, table
#
# Isolation: a maintainer's sandbox is its own XDG_CONFIG_HOME and XDG_DATA_HOME, holding a copy of
# each collection with only [roles.maintainer] and [roles.proposer] changed, the first sweep's runs
# (pilots/dsh-maint/evidence/, frozen at the end of the event) linked into evals/, and an empty
# wiki. No maintainer sees another's patterns or proposals, nor the event's p-001/p-002. Review and
# refine get a fixed budget, so every maintainer is shown the same evidence; `check` proves it.
#
# Nothing here decides a proposal, and nothing is applied to the DSH checkout. The suites, the
# verifiers and the DSH checkout must not change until the arm is done: replay needs the sweep's
# hashes, and `eval --proposal` refuses a changed source.
#
# Resumable: each step leaves its log or JSON under the sandbox's results/, and a step whose output
# is there is skipped. Environment: MAINTAINERS, PANEL, JUDGES, UNITS (space-separated),
# BASE_URL (http://localhost:11434/v1), MAINT_ROOT (~/.local/share/wikiskill-maint), DRY_RUN=1.

set -uo pipefail

SELF=$(realpath "$0")
HERE=$(dirname "$SELF")
ROOT=$(git -C "$HERE" rev-parse --show-toplevel) || exit 2
cd "$ROOT" || exit 2

BASE_URL=${BASE_URL:-http://localhost:11434/v1}
MAINT_ROOT=${MAINT_ROOT:-${XDG_DATA_HOME:-$HOME/.local/share}/wikiskill-maint}
LOGS=${XDG_STATE_HOME:-$HOME/.local/state}/wikiskill/dsh-maint
DRY_RUN=${DRY_RUN:-}
WIKISKILL=$ROOT/.venv/bin/wikiskill
REVIEW_ARGS=(--budget 15000 --signals 5 --clean 3)
# --allow-overlap: the leak check also matches words the component already uses (archive-doer's own
# `unminted`). A matched proposal is kept; its overlap is printed as a warning and kept in the table.
REFINE_ARGS=(--budget 15000 --allow-overlap)

usage() {
  sed -n '2,13p' "$SELF" | sed 's/^# \{0,1\}//'
  exit 2
}
[[ $# -eq 1 ]] || usage
PHASE=$1
case $PHASE in setup | check | propose | candidates | judge | table | all) ;; *) usage ;; esac

# Before the lists below become arrays: an array is not exported, so the re-exec would lose them.
if [[ $PHASE != table && -z ${MAINT_INHIBITED:-} && -z $DRY_RUN ]] &&
  command -v systemd-inhibit >/dev/null; then
  MAINT_INHIBITED=1 exec systemd-inhibit --what=sleep:idle --who=wikiskill \
    --why="DSH maintainer arm" "$SELF" "$@"
fi

read -r -a MAINTAINERS <<<"${MAINTAINERS:-qwen3:30b-a3b qwen3-coder:30b qwen3.8:latest gemma4:31b \
gemma4:latest gpt-oss:20b glm-4.7-flash:latest mistral-small3.2:24b granite4.1:30b llama3.3:latest}"
read -r -a PANEL <<<"${PANEL:-gemma4:latest gpt-oss:20b qwen3:30b-a3b}"
read -r -a JUDGES <<<"${JUDGES:-gpt-oss:120b nemotron-3.5-lightning:latest}"
read -r -a UNITS <<<"${UNITS:-archive bids curate}"

declare -A COLLECTION COMPONENT SUITE MANIFEST
COLLECTION[archive]=dsh-archive COMPONENT[archive]=archive/archive-doer
SUITE[archive]=pilots/archive-doer/suite.yaml MANIFEST[archive]=pilots/archive-doer/dsh-archive.toml
COLLECTION[bids]=dsh-bids COMPONENT[bids]=bids/bids-doer
SUITE[bids]=pilots/bids-doer/suite.yaml MANIFEST[bids]=pilots/bids-doer/dsh-bids.toml
COLLECTION[curate]=dsh-curate COMPONENT[curate]=curate/gen-data-dict
SUITE[curate]=pilots/gen-data-dict/suite.yaml MANIFEST[curate]=pilots/gen-data-dict/dsh-curate.toml

mkdir -p "$LOGS"
STAMP=$(date +%Y%m%d-%H%M%S)
say() { printf '%s  %s\n' "$(date '+%F %T')" "$*" | tee -a "$LOGS/maint-$STAMP.log"; }
state() { uv run --quiet python "$HERE/maint_state.py" "$@"; }
slug() { printf '%s' "${1//[:\/]/_}"; }
box() { printf '%s/%s' "$MAINT_ROOT" "$(slug "$1")"; }
# wikiskill inside one maintainer's sandbox. The venv's binary, so uv never sees the changed XDG.
in_box() {
  local root=$1
  shift
  XDG_CONFIG_HOME=$root/config XDG_DATA_HOME=$root/data "$WIKISKILL" "$@"
}
unload() { [[ -n $DRY_RUN ]] || ollama stop "$1" >/dev/null 2>&1 || true; }

trap 'say "interrupted; rerun to resume"; exit 130' INT TERM

for unit in "${UNITS[@]}"; do
  [[ -n ${COLLECTION[$unit]:-} ]] || { say "unknown unit $unit"; exit 2; }
done
[[ -x $WIKISKILL ]] || { say "no $WIKISKILL; run uv sync"; exit 2; }

setup() {
  local m unit root
  for m in "${MAINTAINERS[@]}"; do
    root=$(box "$m")
    for unit in "${UNITS[@]}"; do
      if [[ -n $DRY_RUN ]]; then
        say "would make $root for ${COLLECTION[$unit]}, roles $m"
        continue
      fi
      state sandbox "$root" "${COLLECTION[$unit]}" "${MANIFEST[$unit]}" "$m" \
        "$HERE/evidence/${COLLECTION[$unit]}.txt" || { say "setup $m $unit failed"; exit 1; }
      mkdir -p "$root/results"
      printf '{"maintainer": "%s", "collection": "%s", "component": "%s"}\n' \
        "$m" "${COLLECTION[$unit]}" "${COMPONENT[$unit]}" >"$root/results/$unit.json"
    done
    say "sandbox $root ready"
  done
}

check() {
  local unit m first hash
  for unit in "${UNITS[@]}"; do
    first=""
    for m in "${MAINTAINERS[@]}"; do
      [[ -z $DRY_RUN ]] || { say "would hash $m's review prompt for $unit"; continue; }
      hash=$(in_box "$(box "$m")" review "${COMPONENT[$unit]}" --collection "${COLLECTION[$unit]}" \
        "${REVIEW_ARGS[@]}" --dry-run | sha256sum | cut -c1-16)
      if [[ -z $first ]]; then
        first=$hash
        # The evidence every maintainer is shown, kept for the judges.
        in_box "$(box "$m")" review "${COMPONENT[$unit]}" --collection "${COLLECTION[$unit]}" \
          "${REVIEW_ARGS[@]}" --dry-run >"$MAINT_ROOT/$unit.evidence.md"
        say "$unit review prompt $hash"
      elif [[ $hash != "$first" ]]; then
        say "$unit: $m's review prompt is $hash, not $first; the sandboxes differ"
        exit 1
      fi
    done
  done
}

propose() {
  local m unit root log
  for m in "${MAINTAINERS[@]}"; do
    root=$(box "$m")
    for unit in "${UNITS[@]}"; do
      log=$root/results/$unit.refine.log
      if [[ -s $log ]] && ! state outcome "$log" | grep -q '^error'; then
        say "skip $m on $unit: $(state outcome "$log")"
        continue
      fi
      if [[ -n $DRY_RUN ]]; then
        say "would review and refine ${COMPONENT[$unit]} with $m"
        continue
      fi
      # A second review would see a different wiki (its watermark, its own patterns): never redo
      # an applied one, so a resumed refine is shown what the first one was.
      if grep -q '^review of .* applied' "$root/results/$unit.review.log" 2>/dev/null; then
        say "review of ${COMPONENT[$unit]} with $m already applied"
      else
        say "review ${COMPONENT[$unit]} with $m"
        in_box "$root" review "${COMPONENT[$unit]}" --collection "${COLLECTION[$unit]}" \
          "${REVIEW_ARGS[@]}" 2>&1 | tee "$root/results/$unit.review.log"
      fi
      say "refine ${COMPONENT[$unit]} with $m"
      in_box "$root" refine "${COMPONENT[$unit]}" --collection "${COLLECTION[$unit]}" \
        "${REFINE_ARGS[@]}" 2>&1 | tee "$log"
      say "$m on $unit: $(state outcome "$log")"
    done
    unload "$m"
  done
}

# Every (maintainer, unit) with a proposal: "root unit id" lines.
proposals() {
  local m unit root out
  for m in "${MAINTAINERS[@]}"; do
    root=$(box "$m")
    for unit in "${UNITS[@]}"; do
      out=$(state outcome "$root/results/$unit.refine.log")
      [[ $out == proposal\ * ]] && printf '%s %s %s\n' "$root" "$unit" "${out#proposal }"
    done
  done
}

candidates() {
  local p root unit id out log run_id base status coll
  mapfile -t todo < <(proposals)
  say "${#todo[@]} proposal(s) to evaluate on ${#PANEL[@]} panel model(s)"
  for p in "${PANEL[@]}"; do
    for line in "${todo[@]}"; do
      read -r root unit id <<<"$line"
      coll=${COLLECTION[$unit]}
      out=$root/results/$unit.replay.$(slug "$p").json
      [[ -s $out ]] && continue
      base=$(state baseline "$coll" "$HERE/evidence/$coll.txt" "$p" default) || {
        say "no baseline for $p on $unit; skipped"
        continue
      }
      if [[ -n $DRY_RUN ]]; then
        say "would eval $id ($root) on $p, injected x3, then replay against $base"
        continue
      fi
      log=$root/results/$unit.cand.$(slug "$p").log
      say "candidate $id of $(basename "$root") on $unit, panel $p"
      in_box "$root" eval --suite "${SUITE[$unit]}" --collection "$coll" --models "ollama/$p" \
        --condition injected --repeats 3 --base-url "$BASE_URL" --proposal "$id" 2>&1 | tee "$log"
      status=${PIPESTATUS[0]}
      run_id=$(awk '$1 == "run" { print $2; exit }' "$log")
      if [[ -z $run_id ]]; then
        say "FAILED candidate $id on $p: exit $status before a run began"
        continue
      fi
      in_box "$root" proposal replay "$id" "$base" "$run_id" --collection "$coll" 2>&1 |
        tee -a "$log"
      if cp "$root/data/wikiskill/$coll/wiki/proposals/$id/replay.json" "$out"; then
        say "replayed $id on $p: $(grep -o '"recommendation": "[^"]*"' "$out")"
      else
        say "replay of $id on $p wrote no replay.json; see $log"
      fi
    done
    unload "$p"
  done
}

judge() {
  local j line root unit id out
  mapfile -t todo < <(proposals)
  for j in "${JUDGES[@]}"; do
    for line in "${todo[@]}"; do
      read -r root unit id <<<"$line"
      out=$root/results/$unit.judge.$(slug "$j").json
      [[ -s $out ]] && continue
      if [[ -n $DRY_RUN ]]; then
        say "would judge $id ($root) with $j"
        continue
      fi
      state judge "$root" "${COLLECTION[$unit]}" "$id" "$j" "$BASE_URL" "$out" \
        "$MAINT_ROOT/$unit.evidence.md" &&
        say "judged $id of $(basename "$root") with $j" ||
        say "judge $j gave no scores for $id of $(basename "$root")"
    done
    unload "$j"
  done
}

table() { state table "$MAINT_ROOT" docs/pilots/dsh-maint/tables; }

say "maint $PHASE: ${#MAINTAINERS[@]} maintainer(s), units ${UNITS[*]}, panel ${PANEL[*]}"
case $PHASE in
  setup) setup ;;
  check) check ;;
  propose) propose ;;
  candidates) candidates ;;
  judge) judge ;;
  table) table ;;
  all) setup && check && propose && candidates && judge && table ;;
esac
say "maint $PHASE finished"
