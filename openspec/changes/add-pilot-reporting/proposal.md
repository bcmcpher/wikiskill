## Why

The DSH pilot's report needs figures no wikiskill output pools today. It must list:
- models that failed preflight, with reasons
- outcome classes and unit times per model, to tell format failures from task failures and to size
  the screening runs
- hard-rule breaks under OFF
- `handoff@k` from three judges of different families

A judge role holds one model, and a judge never sees the delegation it would grade. Grouping models
by family and size is left to hand.

## What Changes

- **Pooled outputs say what did not run.** The leaderboard and the version board list every model
  that failed preflight in any run, with its reasons.
- **The leaderboard pools outcomes and cost.** Each model and condition gains outcome-class counts,
  median unit wall time, and median input and output tokens.
- **The version board reports critical checks under OFF.** They are shown per model and never
  disqualify, since OFF does not load the component.
- **A judge panel of several models.** `[roles.judge]` may name `models = [...]`. A rubric's
  `judges: N` then asks each model once, and every opinion records which model gave it.
- **A judge can see delegations.** A rubric may declare `shows: [delegations]`. The judge is then
  given each delegation the model made: the agent it chose and the text it passed. It is never
  given the expected route.
- **A model catalogue.** An optional TOML file gives each model's family, size and shape. With
  `--models-file`, the leaderboard and the board group rows by family and order them by size. A
  run's report also marks a judge from the family of the model it judged, and gives the majority
  of the other judges beside the full one.
- **`wikiskill report <run>`** re-renders a finished run's `report.md` and `report.json` from its
  own files, with or without a catalogue. Today a report is written only when `eval` ends.

## Capabilities

### New Capabilities

- `model-catalogue`: what wikiskill may be told about a model, and how outputs use it.

### Modified Capabilities

- `collection-config`: a judge role may name several models.
- `eval-scoring`: a judge panel of several models, judges that see delegations, per-judge reporting,
  and pooled outcomes, costs and preflight failures.
- `version-board`: critical checks under OFF, and preflight failures.

## Impact

- `collection.py`, `runner/run.py`, `score/judge.py`, `rubric.py`, `report.py`, `leaderboard.py`,
  `version_board.py`, `cli/leaderboard.py`, a new `cli/report.py`, the rubric schema, `docs/`.
- `add-dsh-pilot` uses all of it: its sweep tables, safety question, routing judges and report.
- `run.json` and `results.jsonl` gain nothing new except per-opinion judge models, which are written
  inside the existing `rubric` record. Earlier runs still load; their opinions carry no model.
