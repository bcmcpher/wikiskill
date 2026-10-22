## Why

A `command` verifier passes or fails on its exit code, and keeps only the last 2000 characters of its
output (`score/verify.py:35`). Calibrated graders, such as skills-comm's neuroimaging scorers, print
a JSON result with a verdict and a 0–100 score, and use the exit code for validity rather than pass.
wikiskill can neither apply such a grader's own pass rule nor report the score it gives.

## What Changes

- A `command` verifier may set `result: json`. Its stdout is then read as a JSON object and stored
  whole with the unit's verifier record in `results.jsonl`.
- `pass_when` maps result fields to accepted values. The verifier passes when the exit code matches
  `expect_exit` and every listed field holds one of its values.
- `score` names a numeric result field to aggregate. Reports give the mean per task, model and
  condition, with a 95% percentile bootstrap interval, beside the pass rate and never folded into it.
- Output that is not a JSON object is an infrastructure error, not a model failure.
- `findings tables` exports the score columns in `findings.csv`.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `task-suite`: a new requirement for the structured-result fields of a command verifier.
- `eval-scoring`: new requirements for deciding pass from a result, and for reporting scores.
- `findings-export`: a new requirement for score columns in the study CSV.

## Impact

- `schemas/task-suite.schema.json`, `src/wikiskill/suite.py`: `result`, `pass_when`, `score`.
- `src/wikiskill/score/verify.py`: parsing, the pass rule, the stored result.
- `src/wikiskill/report.py`: a per-row score summary and its markdown section.
- `src/wikiskill/findings.py`: score columns in `findings.csv` and a score table in `report` tables.
- A new small statistics helper for the seeded bootstrap; stdlib only.
- Docs: `docs/evaluate-and-refine-a-skill.md` §3–§5, `docs/writing-suites.md`, `docs/data.md`.
- Existing suites keep their hash and behaviour. Runs made before this change carry no `result`, and
  their reports are unchanged.
- No dependency on other open changes. `add-verifier-secrets` pairs with it for graders that need a
  credential.
