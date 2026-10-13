## ADDED Requirements

### Requirement: Replay reports each split separately

`wikiskill proposal replay` MUST report the motivating cases, the regression bank and every fallen
task with each task's split, and MUST give the regression bank's rates per split for each model.
The recommendation rule MUST stay unchanged: acceptance is recommended only when a motivating case
improved on some model and no task of any split fell past the tolerance on any model.

#### Scenario: A held-out task falls

- **WHEN** a candidate improves a `train` motivating case and a `test` task falls past the tolerance
  on one model
- **THEN** the replay lists the fallen task with its split `test`, and does not recommend acceptance

#### Scenario: Runs that recorded no splits

- **WHEN** either run lacks `splits` and its suite file no longer matches its `suite_hash`
- **THEN** the replay reports the tasks with split `unknown` and applies the same recommendation rule
