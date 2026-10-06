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

### Requirement: A rubric's judges can be different models

A rubric with `judges: N` MUST ask each model of an N-model judge panel once, and MUST ask a single
judge model N times. Any other combination MUST be refused before any unit runs. Every opinion MUST
record the model that gave it.

#### Scenario: Three judges, three models

- **WHEN** a rubric with `judges: 3` is judged by a three-model panel
- **THEN** the unit's rubric record holds three opinions, one from each model, each naming it

#### Scenario: Three judges, two models

- **WHEN** a rubric with `judges: 3` meets a two-model panel
- **THEN** the run is refused before any unit runs, naming both numbers

### Requirement: A judge can be shown the delegations it grades

A rubric MAY declare `shows: [delegations]`. The judge MUST then be shown, in order, each delegation
the unit's sessions made: the agent delegated to, and the description and prompt passed, each
bounded with its original length stated. A delegating call that failed MUST NOT be shown. When the
unit's sessions were not captured or cannot be read, the unit MUST NOT be judged and its rubric
record MUST give the reason, so missing evidence is never graded as no delegation. The judge MUST
still not be shown the task's expected route. A rubric that does not declare `shows` MUST be judged
as before.

#### Scenario: Grading a handoff

- **WHEN** a planner skill delegates to `archive-doer` under a rubric that shows delegations
- **THEN** the judge's prompt contains `archive-doer` and the text the planner passed, and nothing
  from the task's `expect`

### Requirement: Reports give each judge's opinion

A report MUST give, per rubric dimension, each judge model's levels beside the settled majority.
With a model catalogue, an opinion from a judge of the same family as the model judged MUST be marked,
and the majority of the remaining judges MUST be given beside the full majority, settled by the
panel's own rule.

#### Scenario: A judge of the model's own family

- **WHEN** `gpt-oss:120b` judges units of `gpt-oss:20b`, and the catalogue gives both family `gpt-oss`
- **THEN** its opinions are marked `same family`, and the report gives the other two judges'
  majority beside the three-judge one

#### Scenario: Grading delegations without the sessions

- **WHEN** a rubric shows delegations and the unit's sessions were not captured
- **THEN** the unit's rubric record gives that reason, and no judge is asked

### Requirement: A finished run's report can be rebuilt

`wikiskill report <run>` MUST rebuild `report.json` and `report.md` from the run's own `run.json` and
`results.jsonl`, as `eval` builds them, without running or judging anything. It MUST accept
`--models-file`.

#### Scenario: A catalogue written after the run

- **WHEN** a routing run finished before its catalogue existed, and the user runs `wikiskill report`
  with `--models-file`
- **THEN** the run's report is rewritten with same-family judge opinions marked, and its results
  are unchanged

### Requirement: Pooled results say what failed to run and what it cost

The leaderboard MUST list every model that failed preflight in any pooled run, with the run and its
problems, and every model that passed preflight but has no unit. Per model and condition it MUST give
outcome-class counts over every unit, and the median wall time and median input and output tokens of
the units that ran.

#### Scenario: A model fails the tool-call probe in one run

- **WHEN** `qwen2.5-coder:1.5b` fails preflight in a pooled run
- **THEN** the leaderboard lists it with that run and the probe's problem, and gives no rate from
  that run

#### Scenario: A model that runs out of steps

- **WHEN** a small model's units end `step_exhausted` and `permission_blocked`
- **THEN** its row counts each outcome class, so a format failure is told apart from a task failure
