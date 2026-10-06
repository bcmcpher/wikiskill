## ADDED Requirements

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
