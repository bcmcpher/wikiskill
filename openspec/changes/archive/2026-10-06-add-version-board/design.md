## Context

A version of a component is the `source_hash` of its main file. `run.json` records each component's
hash. A proposal's candidate run records the proposal id and the candidate hash.
- `wikiskill compare` and `proposal replay` judge one candidate against one baseline. They report
  per model and pooled, with a direction of `up`, `down` or `no detectable difference`, and the gate
  adds a tolerance.
- `wikiskill leaderboard` pools runs of one suite and one set of versions across machines, ranks
  models, and marks every model whose interval overlaps the leader's.
- `wikiskill diff` names versions: `current`, hash prefixes, `p-NNN`, `p-NNN^`, `run:<id>`.

The DSH pilot will have several archive-doer versions:
- v1
- the rejected p-002
- a hand-written readiness candidate
- perhaps candidates proposed from one model's failures

These run over up to nineteen models. The question is which version is best overall, and which is
best for each model. Two-way comparisons do not answer it, and running every pair through the gate
is quadratic.

## Goals / Non-Goals

**Goals:**
- One table that ranks N versions of one component per model and overall.
- The best version per model, named with whether it is distinguishable from the baseline.
- The best version overall, named with how it does on every model, not only on average.
- A safety floor: a version that breaks a hard rule even once is not "best".
- Proposals aimed at one model.

**Non-Goals:**
- **Deciding.** The board ranks and flags. `proposal decide` still records what is accepted, and
  only for one candidate against its baseline.
- **Varying two components at once.** That is an interaction experiment, and the board refuses it.
- **Routing metrics across versions.** The board ranks on verifier pass rate. A description change
  that moves routing is still read from `compare` and the leaderboard's route columns.

## Decisions

**The version axis is a leaderboard mode, not a new command.** `wikiskill leaderboard --by-version
<component> <run>...` reuses the leaderboard's loading, its pooling across machines, thinking
entrants and harness labels. With `--by-version`:
- runs may differ in that component's hash and in nothing else the leaderboard checks: suite content,
  every other component's hash
- every other refusal stands
- runs of the same version pool as they do now

**One condition is ranked.** The board ranks the condition where the component is in use: INJECTED,
or ROUTED with `--condition routed`. OFF does not load the component. Its units are therefore pooled
across every version of the same model and shown once per model as the control. Lift is the ranked
rate minus OFF. A candidate run can then skip OFF, which saves a third or half of its GPU time.

**Per model.** Each version's rate has a Wilson 95% interval. The best version for a model has the
highest point estimate among versions that were not disqualified. Its direction against the
baseline uses the same rule as `compare`: `up`, `down` or `no detectable difference`. A version
whose rate on a model is `down`, or with any one task below the baseline by more than the gate's
per-task tolerance (one in three), is marked as a regression on that model. The tolerance is per
task in the gate too, so one collapsing task is caught even when the model's overall rate barely
moves. A version that never ran on a model is shown there as not run.

**Overall.**
- *Panel.* The panel is the models on which every version on the board ran. A model missing one
  version is shown, but kept out of the overall figures, because a mean over different models
  compares nothing.
- *Mean.* A version's overall figure is the mean of its per-model rates over the panel, each model
  weighted equally. With equal repeats this is also the pooled rate. Weighting by units would let a
  model with fewer infrastructure failures count for more.
- *Pairing.* Against the baseline, each version is paired over (model, task) cells. The board
  counts the cells it won and lost, with an exact sign test (the McNemar computation over cells).
- *Best overall.* The highest panel mean among versions that are not disqualified and regress no
  model. Regressions count on every model the version and the baseline both ran, not only the
  panel's. A version with a higher mean that regresses one model is ranked and shown, but is not named
  best. The table says which model it regressed.

**Critical checks live outside the suite.** Marking a verifier critical inside the suite would change
`suite_hash`, and every earlier run would stop pooling. `--critical <file>` takes a small YAML list:
```yaml
- { task: "*", verifier: 0 }        # every task's first verifier
- { task: mint-untagged-version, verifier: 2 }
```
Verifiers are named by task id and by their 0-based index in declaration order, which the per-unit
results already follow. The board refuses an index a task does not have. A version that fails a
critical check in any unit, on any model, is disqualified from "best". The board lists the units.
The file's content hash is recorded in the board's JSON.

**Baseline.** `--baseline <version>` takes any name `wikiskill diff` accepts. The default is the
version that is current in the collection's source.

**Version labels.** A version is labelled `p-NNN` when it is a proposal's candidate. Otherwise it is
labelled `current` or by its short hash, as `diff --list` labels it.

**Output.** `<data>/<collection>/evals/versions/<component>/<name>/` holds `board.md` and
`board.json`. The name is the leaderboard's run-set name, then the condition, the baseline and the
critical checks' hash, so boards of the same runs ranked differently never overwrite. The JSON keeps the per-unit verdicts behind every
figure, so a report can be recomputed without the runs.

**Review for one model.** `wikiskill review --model <model>` and `sample --model <model>` keep only
units and live sessions whose model matches, with or without the provider. A live session whose
model the logger could not tell is excluded. The prompt says the evidence is restricted. A proposal made from that review records the model in its meta. Nothing about how the
proposal is gated changes.

## Risks / Trade-offs

- [Winner's curse: the top of N noisy versions is biased upward] → the board says how many
  versions were compared. A confirmation run, a fresh run of the winner against the baseline, is
  the remedy. It belongs to whoever uses the board, and the DSH pilot does it.
- [Equal model weights reward versions tuned to small models] → the per-model table sits beside the
  mean, and the regression rule stops a version that wins on average by losing on one model.
- [Critical checks by index break if a suite is reordered] → a reordered suite has a new hash, so
  its runs never pool with the old ones, and the file is checked against the suite each run ran.

## Open Questions

- Should the board also weight by family, so three Qwen sizes do not outvote one Granite? Per-family
  means are cheap to add if the DSH results show it matters.
