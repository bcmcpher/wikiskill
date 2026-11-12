## Why

Since `honour-empty-task-overrides`, a task's `guard`, empty included, replaces the suite default's.
A task that sets `guard: {}` therefore drops every deny pattern the suite declared, and nothing says
so: `suite check` passes quietly, and the run looks like any other. The runner's own base denies
still apply, but a suite's `git push*` or `datalad push*` is gone for that task. A run read later
cannot show it either: `run.json` records `setup` only when non-empty and never records `requires`
or `guard`, so an override that cleared a default leaves no trace beside the suite hash.

## What Changes

- `wikiskill suite check` reports a warning (`?`) for each task whose own `guard` drops a deny
  pattern the suite defaults declare, naming the task and the dropped patterns. The suite still
  passes, and its hash does not change.
- `wikiskill eval` prints the same warning, as it already prints suite warnings.
- `run.json` records each task's effective `requires` and `guard` deny patterns, and records `setup`
  for every task, empty included, so a cleared default reads differently from an absent one.
- The schema's `guard` description says that dropping a suite pattern is reported.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `task-suite`: a suite check reports a task guard that drops suite deny patterns.
- `eval-runner`: a run records each task's effective `setup`, `requires` and `guard`.

## Impact

- `src/wikiskill/suite.py`: one more load-time warning; `_as_task` must keep the suite default's
  deny patterns available to the check.
- `src/wikiskill/runner/run.py` (`_manifest`): new `requires` and `guard` keys; `setup` for every task.
- `schemas/task-suite.schema.json`: the `guard` description.
- `docs/data.md`: the `run.json` key list.
- Tests in `tests/test_suite.py` and the run-manifest tests.
- No suite changes hash or behaviour. No existing run is rewritten; readers treat a missing key as
  "not recorded".
- Best applied after `warn-unsent-followups`, which records suite warnings in `run.json`
  `warnings`. Applied first, this change's warning is printed by `eval` but not recorded in the run.
