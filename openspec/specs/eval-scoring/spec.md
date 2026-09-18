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
