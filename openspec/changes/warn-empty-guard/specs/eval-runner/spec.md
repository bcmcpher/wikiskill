## ADDED Requirements

### Requirement: A run records each task's effective overrides

`run.json` MUST record, for every task in the run, the `setup` commands, the `requires` list and the
`guard` deny patterns the task ran with, after the suite defaults were applied, empty lists
included. A task whose own value cleared a suite default MUST therefore read differently from a task
in a suite that declared no default. The runner's own base denies MUST NOT be included in the
recorded `guard` patterns. Recording MUST NOT change any unit's outcome or the suite's hash.

#### Scenario: A task clears the suite's guard

- **WHEN** the suite defaults set `guard: {deny: ["git push*"]}`, task `release` sets `guard: {}`,
  and task `fetch` does not set `guard`
- **THEN** `run.json` records `[]` as the guard patterns of `release` and `["git push*"]` as those of
  `fetch`

#### Scenario: A task clears the suite's setup and requires

- **WHEN** the suite defaults set `setup: ["git init -q"]` and `requires: [datalad]`, and task
  `bare` sets `setup: []` and `requires: []`
- **THEN** `run.json` records `[]` as both the setup and the requires of `bare`

#### Scenario: A run made before this change is read

- **WHEN** a command reads a `run.json` that has no `requires` or `guard` key
- **THEN** it reads the run as before, and treats the missing keys as not recorded rather than empty
