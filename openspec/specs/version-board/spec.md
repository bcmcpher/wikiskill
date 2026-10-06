# version-board Specification

## Purpose

Ranks several versions of one component across models from runs wikiskill already stores: the best
version for each model and overall, guarded against noise, regressions on any model, and broken hard
rules. It ranks and never decides; the refinement gate still records what is accepted.

## Requirements
### Requirement: Runs of several versions of one component are ranked together

`wikiskill leaderboard --by-version <component> <run>...` MUST pool runs that differ only in that
component's `source_hash`. It MUST refuse runs whose suite content differs, or in which any other
component's hash differs, naming the runs and hashes. Runs of the same version MUST pool as the
leaderboard pools them.

#### Scenario: Three versions over two machines

- **WHEN** runs of v1, `p-002` and `p-003` of `archive/archive-doer`, from two machines, share one
  suite hash and every other component's hash
- **THEN** the board shows each version per model, pooled over every run of that version and model

#### Scenario: A second component also changed

- **WHEN** one run also carries a different hash for `archive-cli/zenodo`
- **THEN** the board is refused, naming that component and both hashes, and nothing is written

### Requirement: One condition is ranked, with OFF as the shared control

The board MUST rank one condition in which the component is in use: INJECTED by default, or ROUTED
when asked. OFF units MUST be pooled across every version of the same model, and shown once per
model as the control, with each version's lift over it. A version run without OFF MUST still be
ranked.

#### Scenario: A candidate run without OFF

- **WHEN** a candidate ran only INJECTED, and v1 ran OFF and INJECTED on the same models
- **THEN** the candidate is ranked, and its lift is taken against v1's OFF units for each model

### Requirement: The best version is named per model

For each model, the board MUST give every version's pass rate with a Wilson 95% interval. It MUST
name the best version as the highest point estimate among versions that are not disqualified. It
MUST give that version's direction against the baseline by the rule `compare` uses. A version
whose rate on a model is `down` against the baseline, or on which any one task's rate fell below the
baseline's by more than the gate's per-task tolerance, MUST be marked as a regression on that model,
naming the tasks that fell. A version whose units on a model all failed to run MUST be shown on
that model with its count of units not run, and MUST NOT be named best there.

#### Scenario: One task collapses

- **WHEN** a version holds nine of ten tasks at 3/3 on `gemma4` but falls from 3/3 to 0/3 on one
- **THEN** it is marked a regression on `gemma4`, naming that task, although its rate over every
  task is not `down`

#### Scenario: No version is distinguishable

- **WHEN** every version's interval on `gemma4` overlaps the baseline's
- **THEN** the board names the top version for `gemma4` and says `no detectable difference`, rather
  than presenting the top place as a finding

### Requirement: The best version overall is named on a common panel

The overall figures MUST use only the models on which every version on the board ran, and MUST name
the models left out. A version's overall rate MUST be the mean of its per-model rates over that panel,
each model weighted equally. Against the baseline, each version MUST be paired over (model, task)
cells, with the cells won and lost and an exact sign test. The best version overall MUST be the
highest panel mean among versions that are not disqualified and regress no model that both it and
the baseline ran, on the panel or not. The board MUST state how many versions were compared.

#### Scenario: A higher mean that loses one model

- **WHEN** `p-003` has the highest mean but is a regression on `qwen3:1.7b`
- **THEN** `p-003` is ranked first by mean and marked with that regression, and the version named
  best overall is the highest that regresses no model

### Requirement: Critical checks disqualify a version

`--critical <file>` MUST name verifiers by task id, or `*` for every task, and by 0-based declaration
index. The board MUST refuse an entry naming a verifier a task does not have. A version that fails a
critical check in any unit on any model MUST NOT be named best, per model or overall. The board MUST
list those units, and MUST record the file's content hash. Critical checks MUST NOT be part of the
suite, so marking them does not change `suite_hash`.

#### Scenario: One invented DOI

- **WHEN** the first verifier of every task is critical, and one `p-004` unit on `mistral` replies
  with a DOI
- **THEN** `p-004` is disqualified on every model and overall, and the board names that unit

### Requirement: The board is written for reports

The board MUST write `board.md` and `board.json` under
`<data>/<collection>/evals/versions/<component>/`, in a directory named by the runs, the condition,
the baseline and the critical checks, so boards ranked differently never overwrite one another. A
baseline that none of the runs ran MUST be refused, naming the versions they did run. The JSON MUST keep the per-unit verdicts behind
every figure. Versions MUST be labelled `p-NNN` when they are a proposal's candidate, `current` when they are
the source's current version, and otherwise by the short hash `wikiskill diff --list` shows.

#### Scenario: Recomputing a figure

- **WHEN** a report quotes a version's rate on one model
- **THEN** `board.json` holds the units that rate was computed from, with their run ids
