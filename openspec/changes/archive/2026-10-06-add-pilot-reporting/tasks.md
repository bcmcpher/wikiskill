## 1. Preflight failures and pooled cost

- [x] 1.1 Read each run's `preflight`. List failed models (run, problems) and preflighted models
  with no unit, in the leaderboard (`leaderboard.md`, `.json`)
- [x] 1.2 The same list in the version board
- [x] 1.3 Leaderboard cells: outcome-class counts over every unit; median `duration_ms`, input and
  output tokens over units that ran. Add a median-seconds column and an outcomes table

## 2. Critical checks under OFF

- [x] 2.1 Check OFF units against `--critical`; per-model count and listed units; never disqualify

## 3. Judge panels

- [x] 3.1 `Role.models`: parse `models`, reject `model` with `models`, an empty list and repeats
- [x] 3.2 Self-judging refusal for every panel model (manifest load and `refuse_self_judging`)
- [x] 3.3 `judge_task` over a panel: one opinion per model when N models meet `judges: N`; N from
  one model; refuse other combinations before any unit runs; `Opinion.model`
- [x] 3.4 Report: per-dimension levels per judge model beside the majority

## 4. Delegations for the judge

- [x] 4.1 Rubric `shows: [delegations]` in the loader and the rubric schema; refuse unknown values
- [x] 4.2 Collect each delegation from the unit's normalized events (agent, description, prompt),
  bounded at 4000 characters with the original length; add them to the judge prompt; never `expected`

## 5. Model catalogue

- [x] 5.1 `catalogue.py`: load and validate; match with or without provider; uncatalogued models
- [x] 5.2 `--models-file` on `leaderboard` (including `--by-version`) and `report` (5.4). Family and size
  columns; rows grouped by family and ordered by size
- [x] 5.3 Same-family marking of judge opinions, and the majority of the other judges, in the report
- [x] 5.4 `wikiskill report <run>` (`cli/report.py`): rebuild `report.{json,md}` from the run's files
  with `report.write`, `--models-file` passed through; never re-run or re-judge

## 6. Tests and docs

- [x] 6.1 Tests: preflight lists, outcome and cost medians, OFF critical failures, panel parsing and
  refusals, one opinion per model, delegation view and blindness, catalogue matching and grouping,
  same-family majority
- [x] 6.2 README, `docs/data.md`, and an example catalogue in `examples/`
- [x] 6.3 `bin/check` passes; `openspec validate add-pilot-reporting --strict --no-interactive`
