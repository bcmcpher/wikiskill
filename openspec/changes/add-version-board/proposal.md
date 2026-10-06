## Why

The gate compares two versions of a component: v1 and one candidate. A sweep across many models with
several candidates asks something it cannot answer: which version is best overall, and which is best
for each model? `wikiskill leaderboard` refuses runs whose component versions differ, and
`wikiskill compare` takes two runs. Neither ranks N versions over M models. Review cannot yet propose
a version tailored to one model either, since it reads every model's units at once.

## What Changes

- **`wikiskill leaderboard --by-version <component>`** pools runs that differ only in that one
  component's version.
  - Versions become a second axis beside models.
  - It still refuses runs whose suite or other components differ.
- **A version board**, from those runs:
  - per model: each version's pass rate with its interval; the best version; whether it is
    distinguishable from the baseline
  - overall: each version's mean over models, each model weighted equally, and a paired comparison
    against the baseline over (model, task) cells
  - a version that regresses any model beyond tolerance is marked, whatever its mean
  - a version × task matrix per model
- **Critical checks.** `--critical <file>` names verifiers that must never fail. A version that
  fails one in any unit is disqualified from "best", and the board lists the units. The file lives
  outside the suite, so marking a check does not change `suite_hash`.
- **OFF is shared across versions.** OFF does not load the component, so one OFF run per model
  serves every version. Candidate runs need only INJECTED or ROUTED.
- **`wikiskill review --model <model>`** restricts evidence to one model's units, so a proposal can
  target one model.

## Capabilities

### New Capabilities

- `version-board`: ranking several versions of one component across models, overall and per model.

### Modified Capabilities

- `experience-wiki`: review evidence can be restricted to one model.

## Impact

- `src/wikiskill/leaderboard.py`, `cli/leaderboard.py`, `review.py`, `cli/review.py`, `docs/`.
- Depends on `add-skill-diff` (landed) for version naming: `current`, hash prefixes, `p-NNN`.
- `add-dsh-pilot` uses the board to choose the best archive-doer version.
- No change to suites, `run.json` or `results.jsonl`: the board reads what runs already record.
