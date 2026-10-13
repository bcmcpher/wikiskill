## ADDED Requirements

### Requirement: The data-science-harness adapter assigns splits deterministically

When a data-science-harness fixture declares no split and no `--split` is given, the adapter MUST
assign each task a split computed from its task id alone, so that the same task gets the same split
on every machine and in every run. About three fifths of tasks MUST land in `train`, one fifth in
`val`, and one fifth in `test`. `--split` MUST still place every task in the split it names.

#### Scenario: The same fixture on two machines

- **WHEN** two machines run `wikiskill eval` on the same data-science-harness fixture without
  `--split`
- **THEN** both runs record the same split for every task

#### Scenario: Override

- **WHEN** `wikiskill eval --split val` runs a data-science-harness fixture
- **THEN** every task is placed in `val`
