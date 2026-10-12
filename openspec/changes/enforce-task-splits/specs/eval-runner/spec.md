## ADDED Requirements

### Requirement: Runs record each task's split

`wikiskill eval` MUST record in `run.json` a `splits` mapping from each task id in the run to the
split that task was placed in, after any `--split` override and any adapter assignment.

#### Scenario: A suite with tasks in two splits

- **WHEN** a suite declares task `a` in `train` and task `b` in `test`, and `wikiskill eval` runs it
- **THEN** `run.json` `splits` is `{"a": "train", "b": "test"}`

#### Scenario: A split override

- **WHEN** `wikiskill eval --split train` runs a data-science-harness fixture
- **THEN** every task id in `run.json` `splits` maps to `train`
