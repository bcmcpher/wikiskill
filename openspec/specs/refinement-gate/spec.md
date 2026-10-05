# refinement-gate Specification

## Purpose
Defines the gate a refinement proposal passes before it counts: a candidate run made from a copy
of the source, a replay against a baseline that reports every model and every fallen task, a
recommendation, and a decision only the user makes, recorded in `skill-impact.md`. With a
collection graph, replay also names the component's neighbours and checks description edits for
trigger theft.

## Requirements

### Requirement: Acceptance requires a human decision

A proposal MUST NOT reach `accepted`, `rejected` or `withdrawn` except through an explicit user
decision, whatever the replay results. A decided proposal MUST NOT be decided again.

#### Scenario: Replay recommends acceptance

- **WHEN** replay shows improvement and no regressions
- **THEN** the proposal stays `replayed` with an "accept" recommendation until the user decides

#### Scenario: Decision without replay

- **WHEN** the user decides a proposal that was never replayed
- **THEN** the decision is recorded, and its impact entry says replay was not run

### Requirement: Candidates are evaluated without touching the source

`wikiskill eval --proposal <id>` MUST evaluate the proposal's rendered file from a copy of its
source made in the run directory. It MUST record the proposal in `run.json`, and MUST NOT write to
the source. It MUST refuse when the source file no longer has the proposal's `source_hash`.

#### Scenario: Candidate run

- **WHEN** the user runs `wikiskill eval --proposal p-002` on the doer's suite
- **THEN** `run.json` names `p-002`, records the candidate's hash for the doer, and the source
  repository's `git status` is unchanged

### Requirement: Replay covers motivating cases and a regression bank on every model

`wikiskill proposal replay <id> <baseline> <candidate>` MUST:
- refuse a baseline not run at the proposal's `source_hash`, and a candidate run at neither its
  rendered hash nor under the proposal
- compare the two runs through `compare`
- report each model in the runs separately
- take as motivating cases the suite tasks the cited patterns' evidence came from, and as the
  regression bank every other task
- list evidence that cannot be replayed with the reason: live sessions, and tasks outside the suite
- when the collection has a graph, list each neighbour of the component with the suite tasks that
  expect it, and list as not covered each neighbour no task of the suite expects

Replay MUST NOT add or run tasks to cover a neighbour.

#### Scenario: Proposal motivated by one model's failures

- **WHEN** a proposal's evidence comes only from `qwen3:1.7b` and the runs cover three models
- **THEN** the replay reports each of the three separately

#### Scenario: Live evidence

- **WHEN** a cited pattern's evidence includes a live session
- **THEN** the replay lists that session as non-replayable with its reason

#### Scenario: Patch to a planner skill

- **WHEN** a proposal patches a planner skill with a dependency edge to a doer agent, and the suite
  has tasks expecting the doer
- **THEN** the replay names the doer as a neighbour with those tasks, and any of them that fell is in
  the list of fallen tasks

#### Scenario: Neighbour outside the suite

- **WHEN** the component has a neighbour that no task of the suite expects
- **THEN** the replay lists the neighbour as not covered and runs nothing more

### Requirement: Regressions are reported individually

The replay report MUST list every task whose pass rate fell, per model, and MUST NOT present only an
aggregate change. It MUST recommend "accept" only when motivating cases improved on at least one
model and no task on any model fell by more than the tolerance.

#### Scenario: Net improvement hiding a regression

- **WHEN** a candidate improves five cases and breaks one on the same model
- **THEN** the report shows the net change, names the broken case, and does not recommend accept

### Requirement: Every outcome is recorded in skill-impact

Each decision MUST append an entry to `skill-impact.md` with:
- the decision and the reviewer note
- the diff and the evidence references
- the replay summary, or a statement that replay was not run

A rejected or withdrawn proposal MUST keep its full content in that entry, and later proposer runs
for the component MUST be shown it.

#### Scenario: Rejected proposal

- **WHEN** the user rejects a proposal
- **THEN** its full proposal content and replay summary are appended to `skill-impact.md`, the
  wiki's patterns are unchanged, and the next `refine` prompt for that component contains the entry

### Requirement: Description edits must not steal neighbour triggers

`refine` MUST record whether a proposal changes the component's `description`. When it does and the
collection has a graph, replay MUST compare `route@1` under ROUTED, per model, between baseline and
candidate, for every task whose expected route is a conflict neighbour. It MUST list each drop as a
trigger-theft regression, and MUST NOT recommend "accept" when a drop exceeds the tolerance or when a
conflict neighbour has no such task in the suite. Without a graph, the replay MUST say the check was
not made.

#### Scenario: Broadened description

- **WHEN** a candidate description for `disseminate/publish` causes release tasks to route to
  `publish` on one model
- **THEN** the replay lists `disseminate/dataset-release`'s tasks on that model as trigger-theft
  regressions and recommends "do not accept"

#### Scenario: Conflict neighbour the suite cannot check

- **WHEN** a description edit's motivating cases improved, nothing fell, and a conflict neighbour has
  no routing task in the suite
- **THEN** the replay recommends "none" and names the neighbour it could not check
