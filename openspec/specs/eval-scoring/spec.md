# eval-scoring Specification

## Purpose

Defines how explicit evaluation runs are scored and reported: deterministic verifiers before model
judges, a judge that is never a model under test, and reports across component, model, and condition
that state what was not run.

## Requirements

### Requirement: Scoring is verifier-first

Scores MUST come from route checks and deterministic verifiers wherever a task defines them. A rubric
judge MUST be used only for rubric dimensions, MUST run on the configured judge endpoint, MUST NOT be
a model under test, and MUST NOT see the task's expected route.

#### Scenario: Task with verifier and rubric

- **WHEN** a task defines a command verifier and a rubric
- **THEN** the verifier result is recorded as the pass/fail outcome, and the rubric score is reported
  as a separate dimension

### Requirement: Reports span component, model, and condition

Each evaluation report MUST give, per task, model, and condition:
- pass rate over repeats
- route metrics
- token usage
- wall time
- outcome-class counts

Per suite it MUST also give routing loss, content value, transfer rate, and regression rate.

#### Scenario: Two models, three conditions

- **WHEN** a suite runs on two models under OFF, ROUTED, and INJECTED
- **THEN** the report contains one row per task, model, and condition, plus each model's routing loss
  and content value

### Requirement: Unrun and skipped work is stated

A report MUST list every task, model, and condition combination that was skipped, failed preflight,
or ended in `infra_error`, with the reason. It MUST NOT present a partial run as complete.

#### Scenario: Missing capability

- **WHEN** a task requires `datalad` and the run environment lacks it
- **THEN** the report lists the task as skipped with the missing capability, not as a failure or zero

### Requirement: Runs of one suite are pooled across machines

`wikiskill leaderboard <run>...` MUST pool the results of several runs per model and condition, with
a Wilson 95% interval on each pooled pass rate, and MUST refuse runs whose `suite_hash` differs or
whose components under test carry different `source_hash`es.

A unit MUST count as passed on its verifiers where its task declares any. A task with none MUST count
on its first activation, and only under ROUTED, the one condition in which the route is possible.
Units that did not run MUST be reported beside the rate and MUST NOT enter it.

Runs of one model with different thinking settings MUST be reported as separate entrants and never
pooled into one; runs with different output caps MUST be pooled with a warning.

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
