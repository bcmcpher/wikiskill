## ADDED Requirements

### Requirement: The graph records typed edges with evidence

The collection graph MUST contain `dependency` and `conflict` edges between components. Every edge
MUST carry a weight and the evidence it was derived from. A declared delegation that names nothing in
the collection MUST be kept as unresolved, not dropped.

#### Scenario: Declared delegation

- **WHEN** a planner skill declares `delegates_to: [archive]` and the collection includes the
  `archive` plugin
- **THEN** the graph has a dependency edge of weight 1.0 from that skill to each agent of `archive`,
  citing the file and line of the declaration

#### Scenario: Delegation outside the collection

- **WHEN** a skill delegates to a plugin the collection does not select
- **THEN** the graph lists the delegation as unresolved, with its location

#### Scenario: Prose mention

- **WHEN** a skill's body names `disseminate/dataset-release` and declares no delegation to it
- **THEN** the graph has a dependency edge of weight 0.5 to it, citing the line

#### Scenario: Routing confusion

- **WHEN** an eval run shows ROUTED tasks expecting `analyze/checkpoint` first activating
  `disseminate/dataset-release` on one model
- **THEN** the graph has a conflict edge from checkpoint to release, with that model's rate and the
  run and task ids

#### Scenario: Candidate runs

- **WHEN** a run was made with `wikiskill eval --proposal`
- **THEN** its confusions add no conflict edge

### Requirement: The graph is built on demand and versioned in the wiki

`wikiskill graph build` MUST write the graph to `graph.json` in the collection's wiki and commit it.
It MUST record the runs it read. `wikiskill graph show` and `wikiskill graph neighbours <component>`
MUST read the stored graph and MUST NOT rebuild it.

#### Scenario: Rebuild after an eval

- **WHEN** the user runs `wikiskill graph build --collection dsh` after a new eval
- **THEN** `graph.json` holds the new run's confusions, names the run, and the wiki has a commit for it

### Requirement: Neighbours are depth-1 and thresholded

A component's neighbours MUST be the components it shares a dependency edge with, in either
direction, and those it shares a conflict edge with at or above the conflict threshold (default
0.05), in either direction.

#### Scenario: Doer of a planner

- **WHEN** `disseminate/dataset-release` delegates to `archive`
- **THEN** `archive/archive-doer` is a neighbour of the planner, and the planner of the doer
