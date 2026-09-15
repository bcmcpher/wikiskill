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

### Requirement: The routing probe runs on open models with its declared control

The pilot MUST run the data-science-harness routing suite with the OFF condition as the protocol's
harness-off control. It MUST report `route@1`, `route@k`, and `capability@k` per model, as the probe
fixture defines them.

#### Scenario: Two open models

- **WHEN** the reported run completes on two open models
- **THEN** the pilot report gives each metric per model under OFF and ROUTED, and names OFF as the
  control

### Requirement: Mutating operations are blocked during the probe

Routing-probe runs MUST block pushes, saves, sibling configuration, and credential access. They MUST
set `DATALAD_AUTOSAVE=0`.

#### Scenario: Model attempts a push

- **WHEN** a doer agent tries `datalad push` during a routing task
- **THEN** the guard blocks it, the run is classified `permission_blocked`, and route metrics still
  count the delegation

### Requirement: Unrun probes and runs are stated

The pilot report MUST name every data-science-harness probe not executed and every planned run not
completed, with reasons. It MUST NOT present smoke-run results as the reported run.

#### Scenario: Only the smoke run completed

- **WHEN** no remote endpoint was available for the reported run
- **THEN** the report labels its figures as smoke results, and lists the reported run and the
  provenance, reproducibility, and cost probes as unrun
