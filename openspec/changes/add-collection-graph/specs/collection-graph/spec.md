## Purpose

Defines the typed relation graph over a collection — dependency, co-usage, and conflict edges with
evidence — and its use to widen refinement replay and to prevent description edits from stealing
triggers from neighbours.

## ADDED Requirements

### Requirement: The graph records typed edges with evidence

The collection graph MUST contain `dependency`, `co_usage`, and `conflict` edges between components.
Every edge MUST carry a weight and the evidence it was derived from.

#### Scenario: Declared delegation

- **WHEN** a planner skill declares `delegates_to: [datalad, archive]`
- **THEN** the graph has dependency edges from that skill to the agents those plugins provide, citing
  the frontmatter location

#### Scenario: Routing confusion

- **WHEN** an eval report shows tasks expecting `analyze/checkpoint` routed to
  `disseminate/dataset-release` on one model
- **THEN** the graph has a conflict edge between them, with that model's confusion rate and the run id

### Requirement: Replay includes graph neighbours

When the graph exists, the refinement gate MUST add a component's neighbours above the configured
thresholds to its replay set, and MUST report any neighbour cases dropped by the replay cap.

#### Scenario: Patch to a planner skill

- **WHEN** a proposal patches a planner skill with a dependency edge to a doer agent
- **THEN** replay includes that doer's regression cases

### Requirement: Description edits must not steal neighbour triggers

When a proposal edits a skill's description, the gate MUST replay routing tasks of its conflict
neighbours. It MUST list as a regression any neighbour whose `route@1` drops beyond tolerance on any
model.

#### Scenario: Broadened description

- **WHEN** a candidate description for `disseminate/publish` causes release tasks to route to
  `publish`
- **THEN** the gate report lists `disseminate/dataset-release` routing as regressed on the affected
  models
