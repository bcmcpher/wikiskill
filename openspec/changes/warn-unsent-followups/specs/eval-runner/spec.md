## ADDED Requirements

### Requirement: Runs record their suite's warnings

`wikiskill eval` MUST print every warning its suite check reports before any unit runs, and MUST
record each of them in the run's `run.json` `warnings` list, beside the run's own warnings. A warning
MUST NOT change any unit's outcome or score.

#### Scenario: A suite with unsent follow-up turns is evaluated

- **WHEN** `wikiskill eval` runs a suite whose task `ask-then-correct` declares `followups`
- **THEN** the task runs with its first prompt only, and `run.json` `warnings` contains the warning
  that names `ask-then-correct` and says its follow-up turns were not sent

#### Scenario: A suite with no warnings is evaluated

- **WHEN** `wikiskill eval` runs a suite whose check reports no warning
- **THEN** `run.json` `warnings` holds only the run's own warnings, if any
