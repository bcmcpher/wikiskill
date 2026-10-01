## ADDED Requirements

### Requirement: Runs of one suite are pooled across machines

`wikiskill leaderboard <run>...` MUST pool the results of several runs per model and condition, with
a Wilson 95% interval on each pooled pass rate, and MUST refuse runs whose `suite_hash` differs or
whose components under test carry different `source_hash`es.

A unit MUST count as passed on its verifiers where its task declares any. A task with none MUST count
on its first activation, and only under ROUTED, the one condition in which the route is possible.
Units that did not run MUST be reported beside the rate and MUST NOT enter it.

The ranking MUST mark every model whose interval overlaps the leader's, so a place in the table is
not read as a finding. A single run's report MUST carry the same pooled table.

#### Scenario: Two laptops, one suite

- **WHEN** two runs of `toy-routing` with the same suite and component hashes are pooled
- **THEN** each model and condition shows its passes over the units of both runs, with an interval,
  the runs it came from, and the context each machine served it with

#### Scenario: A suite edited between runs

- **WHEN** one run's suite file differs from the other's
- **THEN** the leaderboard is refused, naming both hashes, and nothing is written

#### Scenario: A routing task under OFF

- **WHEN** a task with an expected skill and no verifiers runs under OFF
- **THEN** its units are not counted, rather than counted as failures the condition guarantees
