## Purpose

Defines the data-science-harness pilot: running that collection's routing probe through wikiskill on open
models, reporting in the terms of its own evaluation protocol, and logging its real use — all without
modifying data-science-harness.

## ADDED Requirements

### Requirement: The pilot never modifies data-science-harness

Building, evaluating, logging, and refining data-science-harness components MUST NOT write to the
data-science-harness repository. Refinements MUST be delivered as patches.

#### Scenario: Full pilot run

- **WHEN** the collection build, routing probe, and a review have run
- **THEN** `git status` in the data-science-harness repository is unchanged

### Requirement: Each unit is piloted through the loop

The pilot MUST take each chosen unit — one plugin's skills, or one doer with its toolbox — through
`add-minimal-loop`'s loop:
- a unit collection
- a capability suite checked by hand
- a v1 run with OFF as the control
- a review, a proposal the user applies, and a v2 run with the same suite, models and repeats
- a comparison with the decision recorded

The report MUST give pass rates with intervals per model and condition.

#### Scenario: A unit completes the loop

- **WHEN** a unit's v2 run finishes
- **THEN** `wikiskill compare` reports it against v1, and `skill-impact.md` records the decision

### Requirement: The routing probe, when run, uses its declared control

When the pilot runs the data-science-harness routing suite, it MUST use the OFF condition as the
protocol's harness-off control. It MUST report `route@1`, `route@k`, and `capability@k` per model, as
the probe fixture defines them.

#### Scenario: Two open models

- **WHEN** the reported routing run completes on two open models
- **THEN** the pilot report gives each metric per model under OFF and ROUTED, and names OFF as the
  control

### Requirement: Mutating operations are blocked during pilot runs

Pilot runs MUST block pushes, sibling configuration, network publishing, and credential access; saves stay allowed, since a doer's job is to make them inside the run's own dataset. They MUST
set `DATALAD_AUTOSAVE=0`.

#### Scenario: Model attempts a push

- **WHEN** a doer agent tries `datalad push` during a pilot task
- **THEN** the guard blocks it, and the task's verifiers still judge what the run left behind

### Requirement: Unrun probes and runs are stated

The pilot report MUST name every data-science-harness probe not executed and every planned run not
completed, with reasons. It MUST NOT present smoke-run results as the reported run.

#### Scenario: Only the smoke run completed

- **WHEN** no remote endpoint was available for the reported run
- **THEN** the report labels its figures as smoke results, and lists the reported run and the
  provenance, reproducibility, and cost probes as unrun
