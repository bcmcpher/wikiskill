## Why

The task-suite schema accepts `followups`, scripted user turns sent after the first response, and
`suite.py` parses them into `Task.followups`. No runner sends them. A suite that sets them runs as a
single-turn task, with no message to say so, and its results read as if the scripted turns had
happened. Until `add-scripted-followups` lands, a suite author and a later reader of a run must be
told.

## What Changes

- `wikiskill suite check` reports every task that sets `followups` as a warning (`?`), naming the
  task and saying the turns are not sent. The suite still passes, and its hash does not change.
- `wikiskill eval` prints the same warning, as it already does for suite warnings.
- `run.json` records the suite's warnings in its existing `warnings` list, so a run read later says
  that its scripted turns were never sent. This applies to every suite warning, not only this one.
- The schema's description of `followups` says the field is accepted but not yet sent.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `task-suite`: a new requirement that a suite check reports `followups` as not sent.
- `eval-runner`: a run records its suite's warnings in `run.json`.

## Impact

- `src/wikiskill/suite.py`: one more warning in the load-time checks.
- `src/wikiskill/runner/run.py` and `src/wikiskill/cli/eval.py`: suite warnings reach `run.warnings`.
- `schemas/task-suite.schema.json`: the `followups` description.
- `docs/data.md`: `run.json`'s `warnings` also holds suite warnings.
- Tests in `tests/` for the warning and the recorded warnings.
- No existing suite changes behaviour or hash. No existing run is rewritten.
- Task 3.1 edits `docs/evaluate-and-refine-a-skill.md`, which lands with the
  `docs/evaluate-and-refine-guide` branch; merge that branch first.
- Superseded by `add-scripted-followups` when that change lands: it removes the warning.
