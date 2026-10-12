## Why

Every task declares a split, and the schema says refinement reads `train`, tuning reads `val` and
`test` is held out. Nothing enforces it. Review shows the maintainer units from every split, so a
proposal can be shaped by the very tasks later used to judge it. Runs do not even record each
task's split, so the separation cannot be checked after the fact.

## What Changes

- **Runs record splits.** `run.json` gains `splits`, mapping each task id to its split.
- **Review reads train and live evidence only.** Eval units from `val` and `test` tasks are never
  shown to the maintainer, so they never reach a pattern or a proposal. Live sessions have no split
  and stay eligible.
- **Older runs** without `splits` are recovered from the run's suite file when its hash still matches
  `suite_hash`. Otherwise their units are left out of review, and review reports how many.
- **Replay reports per split.** Motivating cases, the regression bank and every fallen task are
  broken down by split. The recommendation rule is unchanged: no task of any split may fall past the
  tolerance on any model.
- **The data-science-harness adapter assigns splits deterministically.** Each task's split comes from
  a hash of its id, the same on every machine. `eval --split` still places every task in one split.
  **BREAKING** for review of DSH suites: tasks that were all `val` now spread across the three.
- The schema's and the template's split descriptions say the split is enforced.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `eval-runner`: `run.json` records each task's split.
- `experience-wiki`: review samples eval evidence from `train` tasks only, plus live sessions.
- `refinement-gate`: replay reports motivating cases, the regression bank and fallen tasks per split.
- `task-suite`: the data-science-harness adapter assigns a deterministic per-task split.

## Impact

- `src/wikiskill/runner/run.py` (`run.json`), `src/wikiskill/compare.py` (reading a run's splits),
  `src/wikiskill/review.py` (eval candidates), `src/wikiskill/gate.py` (breakdown),
  `src/wikiskill/adapters/dsh.py` (split assignment), `cli/eval.py` (`--split` default).
- `schemas/task-suite.schema.json`, `docs/templates/suite.yaml`, `docs/data.md`,
  `docs/evaluate-and-refine-a-skill.md` §3.10 and §5.2.
- Existing wikis keep their patterns. Patterns cite evidence that may now come from `val` or `test`;
  this change does not retire them. Review stops adding such evidence from now on.
- Depends on the `docs/evaluate-and-refine-guide` branch being merged, for the guide edits.
- Independent of `warn-unsent-followups` and `add-scripted-followups`.
