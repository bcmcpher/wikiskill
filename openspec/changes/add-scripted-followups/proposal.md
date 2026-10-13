## Why

Many skill failures appear only after the first answer: the user corrects a value, asks for the
next step, or pushes back on a refusal. The suite schema already has `followups`, scripted user
turns sent after the first response, but no runner sends them. `warn-unsent-followups` makes that
visible; this change makes the field work, so a suite can test how a skill holds up over a short,
scripted conversation.

## What Changes

- **Both backends send follow-up turns** in the same session, in order, after the model's previous
  answer: OpenCode by continuing the session, Claude Code by resuming it.
- **One verdict per unit, after the last turn.** Verifiers run once, after the final scripted turn.
  `final_text` is the last turn's answer; `transcript` covers every turn.
- **Budgets cover the whole conversation.** `timeout_s` and `max_steps` are shared by all turns. A
  turn that exhausts either ends the unit, and the remaining turns are not sent.
- **Routing reads the first turn.** `route@1` stays the first activation of the unit, which is in
  the first turn.
- **Runs record that follow-ups were sent**, and the leaderboard and comparisons refuse to pool a
  run that sent them with one that did not, for a suite that declares them.
- The follow-up warning from `warn-unsent-followups` is removed, and the schema's description says
  the turns are sent.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `eval-runner`: scripted follow-up turns are sent in the same session, within the unit's budgets.
- `eval-scoring`: runs that did and did not send follow-ups are never pooled.
- `task-suite`: the unsent follow-up warning is removed.

## Impact

- `src/wikiskill/runner/opencode.py` and `runner/claude.py`: a turn loop; `runner/base.py` or
  `common.py`: the shared budget accounting.
- `harness/opencode/guard/`: the step counter must persist across the processes of one unit.
- `src/wikiskill/runner/run.py`: `run.json` `options.followups`.
- `src/wikiskill/leaderboard.py`, `compare.py`, `version_board.py`: the pooling check.
- `src/wikiskill/suite.py`: the warning removed. `schemas/task-suite.schema.json`, `docs/data.md`,
  `docs/writing-suites.md`, `docs/evaluate-and-refine-a-skill.md`.
- Depends on `warn-unsent-followups` being archived first: this change removes its requirement.
- Independent of `enforce-task-splits`.
