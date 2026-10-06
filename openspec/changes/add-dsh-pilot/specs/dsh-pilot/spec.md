## Purpose

Defines the data-science-harness pilot: running that collection's components and routing probe through
wikiskill on open models, across model families and sizes, and reporting in the terms of its own
evaluation protocol — all without modifying data-science-harness.

## ADDED Requirements

### Requirement: The pilot never modifies data-science-harness

Building, evaluating, and refining data-science-harness components MUST NOT write to the
data-science-harness repository. Refinements MUST be delivered as patches.

#### Scenario: Full pilot run

- **WHEN** the collection build, routing probe, and a review have run
- **THEN** `git status` in the data-science-harness repository is unchanged

### Requirement: Each unit is piloted through the loop

The pilot MUST take each chosen unit — one plugin's skills, or one doer with its toolbox — through
the loop of `add-minimal-loop`, gated by `add-skill-refinement`:
- a unit collection
- a capability suite checked by hand
- a v1 run with OFF as the control
- a review, a proposal, and a v2 run of the proposal's candidate (`wikiskill eval --proposal`) with
  the same suite, models and repeats, so the source is never edited to test it
- a replay of v2 against v1 and the decision recorded

The report MUST give pass rates with intervals per model and condition.

#### Scenario: A unit completes the loop

- **WHEN** a unit's v2 run finishes
- **THEN** `wikiskill proposal replay` reports it against v1, and `skill-impact.md` records the
  decision

### Requirement: A hand-written patch passes the same gate

A patch the pilot writes by hand MUST be submitted as a proposal and evaluated as a candidate run,
replayed against v1 and decided, exactly as a generated proposal is. It MUST NOT be handed to the
data-science-harness maintainer unless that decision accepted it, and it MUST be handed over with
its comparison.

#### Scenario: The readiness-path patch

- **WHEN** a hand-written patch to `archive-doer.md` is evaluated and replayed
- **THEN** `skill-impact.md` records the decision, and the report shows `wikiskill diff` of v1
  against the candidate

### Requirement: Models are compared across families and sizes

The pilot MUST preflight every model the server offers. It MUST report every model that passed, with
pass rates and intervals per model and condition, and MUST list every model that failed with its
reason. The repeats MUST be chosen before the first run and stated in the report. Runs of one model
with different thinking settings MUST be reported as separate entrants. The report MUST state the
run-to-run spread of two runs of one version on one model, beside any difference the pilot reports
between versions or models.

#### Scenario: A model fails preflight

- **WHEN** a served model does not return a structured tool call
- **THEN** the report lists it with that reason, and no rate is reported for it

#### Scenario: Thinking on and off

- **WHEN** one model runs the suite at `--thinking default` and at `--thinking off`
- **THEN** the report shows two rows for it, one per setting, never one pooled rate

### Requirement: The routing probe uses its declared control

The pilot MUST run the data-science-harness routing suite on models from at least three families.
It MUST use the OFF condition as the protocol's harness-off control and ROUTED as harness-on. It MUST
report `route@1`, `route@k`, and `capability@k` per model, as the probe fixture defines them.
`handoff@k` MUST be scored by three judges, none of them a model under test in the routing run,
reporting each judge's identity and label beside the majority. A judge from the same family as the
model that made a delegation MUST be marked.

#### Scenario: Three open model families

- **WHEN** the routing run completes on models from three families
- **THEN** the pilot report gives each metric per model under OFF and ROUTED, and names OFF as the
  control

#### Scenario: A judge scores its own family

- **WHEN** `gpt-oss:120b` judges a delegation made by `gpt-oss:20b`
- **THEN** its label is marked, and the majority of the other two judges is reported beside the
  three-judge majority

### Requirement: The best version is chosen across models and confirmed

The pilot MUST rank its versions of a unit on the version board, per model and overall, with
critical checks for the unit's hard rules. It MUST name the best version overall and the best for
each model, each with its direction against v1. A best version MUST be confirmed by a fresh run
before the report states it as a finding, and the best overall MUST still pass the gate before it
is accepted.

#### Scenario: The finals name a best version

- **WHEN** the finals name `p-003` best overall
- **THEN** a fresh run of `p-003` and v1 on the screening panel is reported beside the finals, and
  `skill-impact.md` records the gate's decision on `p-003`

#### Scenario: A version that breaks a hard rule

- **WHEN** a version's reply contains a DOI in one unit
- **THEN** the report shows it disqualified, and it is named best for no model

### Requirement: Mutating operations are blocked during pilot runs

Pilot runs MUST block pushes, sibling configuration, network publishing, and credential access.
Saves stay allowed, since a doer's job is to make them inside the run's own dataset. Pilot runs MUST
set `DATALAD_AUTOSAVE=0`.

#### Scenario: Model attempts a push

- **WHEN** a doer agent tries `datalad push` during a pilot task
- **THEN** the guard blocks it, and the task's verifiers still judge what the run left behind

### Requirement: Unrun probes and runs are stated

The pilot report MUST name every data-science-harness probe not executed and every planned run not
completed, with reasons. It MUST NOT present smoke-run results as the reported run, and MUST NOT
present the rates of an unfinished run as complete.

#### Scenario: A model's run does not finish

- **WHEN** a model passes preflight but its sweep run does not finish
- **THEN** the report lists that model's run as unrun with the reason, and gives no rates for it

#### Scenario: Probes outside this change

- **WHEN** the report is written
- **THEN** it lists the provenance, reproducibility, and cost probes as unrun, with reasons
