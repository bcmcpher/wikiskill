## ADDED Requirements

### Requirement: Review reads only training evidence

Review MUST draw eval evidence only from units of tasks in the `train` split. Units of `val` and
`test` tasks MUST NOT appear in a review digest or in a saved sample. Live sessions have no split and
MUST remain eligible.

For a run whose `run.json` has no `splits`, review MUST take each task's split from the run's suite
file when that file's content hash equals the run's `suite_hash`. When it does not, or the file is
gone, review MUST leave the run's units out and report how many units it left out and why.

#### Scenario: A run with all three splits

- **WHEN** a run evaluated a component on tasks in `train`, `val` and `test`, and its units all
  carry failure signals
- **THEN** the review digest shows only units of the `train` tasks

#### Scenario: Live sessions

- **WHEN** a component has live sessions with notes and eval units only in `test`
- **THEN** the review digest shows the live sessions and no eval units

#### Scenario: An older run whose suite is unchanged

- **WHEN** a run has no `splits` and its suite file's hash still equals its `suite_hash`
- **THEN** review reads each task's split from the suite file and samples its `train` units

#### Scenario: An older run whose suite has changed

- **WHEN** a run has no `splits` and its suite file has been edited since the run
- **THEN** review shows none of its units and reports the run id and the number of units left out
