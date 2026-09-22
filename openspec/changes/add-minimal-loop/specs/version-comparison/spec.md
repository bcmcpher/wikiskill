## Purpose

Defines how two evaluation runs of one suite are compared across versions of a component — the light
gate before cross-model replay exists — and how the user's decision is recorded.

## ADDED Requirements

### Requirement: Runs of one suite compare across component versions

`wikiskill compare <run-a> <run-b>` MUST compare two completed runs from their stored results without
re-running anything. It MUST refuse runs whose suite or task ids differ, and MUST warn when the
component under test has the same `source_hash` in both. `--record accept|reject --proposal <id>` MUST
append the decision, both run ids, both hashes, and the pooled result to `wiki/skill-impact.md`, and
MUST NOT apply or revert any change.

#### Scenario: Before and after a patch

- **WHEN** run A used datalad-doer at hash `h1` and run B at hash `h2`, on the same suite
- **THEN** the comparison is produced and labels its columns with both hashes

#### Scenario: Different suites

- **WHEN** the two runs used different suites
- **THEN** the command exits non-zero and names both suites

#### Scenario: Recording a decision

- **WHEN** the user runs the comparison with `--record reject --proposal p-001`
- **THEN** `skill-impact.md` gains one entry for `p-001`, and no source file changes

### Requirement: Comparisons report intervals, direction, and tool choice

The comparison MUST report the following, for each condition, for each model and pooled:
- the pass rate with a Wilson 95% interval
- the direction of change, reported as "no detectable difference" when the two intervals overlap
- the distribution of tool calls, from the runs' trajectories in the raw log
- a pooled row recomputed with `timeout` outcomes excluded

Models present in only one run MUST be listed as unmatched rather than compared.

#### Scenario: Overlapping intervals

- **WHEN** version A passes 5 of 10 units and version B passes 7 of 10 for one model
- **THEN** that model's row reports both intervals and "no detectable difference"

#### Scenario: Tool choice shifts

- **WHEN** version B's units call `datalad save` in 9 of 10 runs and version A's in 3 of 10
- **THEN** the tool-choice section shows both counts side by side

#### Scenario: Timeouts

- **WHEN** some units timed out in either run
- **THEN** a timeouts-excluded pooled row appears beside the full pooled row
