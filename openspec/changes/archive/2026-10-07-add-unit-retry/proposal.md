## Why

A run is all or nothing today. One unit whose harness crashes makes the whole run incomplete, and
the DSH sweep then reruns every unit. On 2026-10-07, OpenCode crashed once in ministral-3:3b's
archive run: `opencode produced no session (exit -5)`, a Bun crash, on one of 36 units. The other
35 units completed and were scored, but the run was not recorded, and a 16-minute rerun was queued
to replace one unit.

The scores never needed the rerun. `infra_error` units are already left out of every denominator.
The loss is in completeness: a cell with 17 of 18 units is not the cell the design asked for, and
the sweep treats an incomplete run as unusable, which is the right default for a run log.

What is missing is a way to repair one unit without discarding the others:
- inside a run, when the harness crashes on a unit, before the run ends; and
- after a run, for the units that still did not run.

## What Changes

- **Retry crashed units inside a run.** `wikiskill eval --retries N` (default 1) reruns a unit, in a
  fresh workdir, when it ends `infra_error` for a transient reason: the harness exited without a
  session, its session could not be exported, or it could not be launched. Timeouts, an agent
  mismatch, a verifier that could not run and every `skipped` unit are not retried. A scored outcome
  is never retried, pass or fail. Each result records its attempts and the errors of the earlier
  ones.
- **Fill an existing run.** `wikiskill eval --fill RUN_ID` reruns only the units of that run that
  have no scored result, under the run's own suite, models, conditions, repeats and thinking, and
  writes them into the same run. It refuses when the suite file's hash, the harness version, the
  collection's component versions or the run options no longer match the run, and a run killed
  before it wrote `run.json`. The result a filled unit replaces is kept beside the run, and
  `run.json` lists every fill.
- **The sweep fills before it gives up.** `pilots/dsh-sweep/sweep.sh` calls `--fill` on an
  incomplete run, up to `MAX_FILLS` times (default 2), before it reports the run incomplete. A run
  that becomes complete is recorded like any other.

## Impact

- `eval-runner` spec: one requirement added, one modified.
- `runner/run.py`, `runner/base.py` (`Trajectory`, `RunLayout`), `runner/opencode.py` and
  `runner/claude.py` (marking transient errors), `cli/eval.py`, `report.py`, `gate.py` (a fill
  reuses a candidate run's copy of the source), and `pilots/dsh-sweep/sweep.sh` on
  `results/dsh-pilot`.
- Readers of `results.jsonl` are unchanged: it still holds one line per unit.
- Existing runs stay valid. A run with no `fills` and no `attempts` reads as it does now.
