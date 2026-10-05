## MODIFIED Requirements

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

## ADDED Requirements

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
