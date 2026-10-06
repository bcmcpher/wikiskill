## Context

The DSH pilot (`add-dsh-pilot`) sweeps the archive-doer suite over about nineteen local models, ranks
its versions on the version board, and runs the DSH routing probe with a three-judge `handoff@k`.
Its report structure is set in that change's design. What the pooled outputs already give: pass
rates with intervals, per-task matrices, thinking and harness entrants, versions per model and
overall.

What each run already records, but no pooled output uses:
- `run.json` → `preflight`: per model `ok`, `problems` and `details`.
- each unit in `results.jsonl`: `outcome`, `duration_ms`, `tokens` (`input`, `output`,
  `reasoning`), and `verifiers` in declaration order.
- `rubric`: the judgement, with one opinion per judge. Every opinion comes from the one judge
  model.

The judge (`score/judge.py`) is given the rubric, the files in the work directory and the final
answer. It is blind to the expected route. `roles.judge` has one `model`, and `judges: 3` asks that
model three times.

## Goals / Non-Goals

**Goals:**
- Every number the DSH report quotes comes from a wikiskill output, not from hand-counting files.
- `handoff@k` is graded by three different models, each with its own recorded label, by judges who
  saw the delegation.
- Models can be grouped by family and ordered by size in pooled tables.

**Non-Goals:**
- **Writing the report.** The tables feed `docs/pilots/dsh.md`; the prose stays by hand.
- **Inferring a model's family from its name.** `qwen3` and `qwen3.8` share a family, and `mistral`
  reports a `llama` architecture. Families are declared, never guessed.
- **Changing pass/fail.** A judge still never touches `passed`.

## Decisions

**Preflight failures.** The leaderboard and the version board read each run's `preflight` and list
every model whose entry is not `ok`: the run, the model and its `problems`. A model that failed in
one run and passed in another is listed with both, since a pooled rate for it omits that run. A
model that passed preflight and has no units is listed as preflighted but not run.

**Outcomes and cost in the leaderboard.** Each cell gains:
- `outcomes`, counting every unit by class, the ones that did not run included
- the median `duration_ms` of units that ran
- the median input and output tokens of units that ran

Medians, because one runaway generation (qwen3:1.7b once spent ten minutes on a single request)
would swamp a mean. The ranking table gets a median-seconds column. A new outcomes table gives each
model and condition its counts by class.

**Critical checks under OFF on the board.** The board already checks `--critical` in the ranked
condition. It now also checks OFF units, and gives per model the number of OFF units that failed a
critical check, with the units listed. These never disqualify a version: OFF does not load the
component, so they say what the bare model does, which is the pilot's safety question.

**Judge panels.** `[roles.judge]` accepts `models = ["a", "b", "c"]` instead of `model`, on one
`base_url`.
- A rubric with `judges: N` and a panel of N models asks each model once.
- A panel of one asks it N times, as today.
- Any other combination is refused when the run starts. Cycling models to fill slots would give a
  majority that two opinions from one model can carry.
- Every model in the panel is checked against the models under test, as the single judge is.
- Each opinion records its `model`. The judgement's `model` is the panel, joined with `, `.

One endpoint for the panel keeps the role's shape. Judges on several endpoints are not needed for
the pilot, where Ollama serves all three.

**Delegations in the judge's view.** A rubric may say `shows: [delegations]`. The judge's prompt then
lists, in order, each delegation in the unit's sessions:
- the agent the model delegated to
- the description and prompt it passed, bounded to 4000 characters each

These come from the unit's normalized events (`delegation`, and the `tool_call` that made it). The
judge still never sees `expected`. The delegated agent is what the model did, not what it should
have done. A rubric without `shows` is judged exactly as now.

**Re-rendering a report.** `wikiskill report <run> [--collection C] [--models-file F]` rebuilds
`report.json` and `report.md` from the run's `run.json` and `results.jsonl`, with the same builder
`eval` uses. It never re-runs or re-judges anything. It is what applies a catalogue to a finished
run, and what gives old runs the new per-judge tables.

**Model catalogue.** `--models-file <toml>` on `leaderboard` and `report`:
```toml
[models."qwen3:30b-a3b"]
family = "qwen"
size_b = 30.5
shape = "moe"        # dense | moe | hybrid-moe, free text
```
Keys match a model with or without its provider, as `review --model` does. Unknown models are
listed under "uncatalogued", never dropped.
- *Leaderboard:* ranking rows gain family and size columns. The per-model tables group by family and
  order by size.
- *Version board:* the per-model table is grouped and ordered the same way.
- *Report (judge marks):* where a rubric's judges include the family of the model judged, that
  opinion is marked `same family`. The dimension shows the majority of the remaining judges beside
  the full majority.

Same-family marking is done when the report is made, not when the run happens, so a catalogue fixed
later still applies to old runs.

## Risks / Trade-offs

- [Three judges triple judging time] → a panel only runs for tasks with a rubric, and the pilot's
  routing suite is the only one with a handoff rubric.
- [Delegation text can be long] → bounded at 4000 characters per field, with the original length
  stated.
- [A catalogue drifts from what Ollama serves] → it is descriptive only; nothing is refused for a
  mismatch, and uncatalogued models are listed.

## Open Questions

- Should judges on separate endpoints be allowed later (`[[roles.judges]]`)? Not needed for the
  pilot.
