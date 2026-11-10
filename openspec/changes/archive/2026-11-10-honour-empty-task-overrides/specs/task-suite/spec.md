## ADDED Requirements

### Requirement: A task's own value replaces the suite default, even when empty

When a task sets `setup`, `requires` or `guard`, the loader MUST use the task's value in place of
the suite default's, whether or not that value is empty. Only a key the task does not set MUST fall
back to the default. `env` MUST merge instead: the default's variables, with the task's value
winning for a name set in both.

#### Scenario: Empty setup clears the default

- **WHEN** the suite defaults set `setup: ["git init -q"]` and a task sets `setup: []`
- **THEN** the loaded task has no setup commands

#### Scenario: Absent setup takes the default

- **WHEN** the suite defaults set `setup: ["git init -q"]` and a task does not set `setup`
- **THEN** the loaded task's setup is `["git init -q"]`

#### Scenario: Empty guard clears the default denies

- **WHEN** the suite defaults set `guard: {deny: ["git push*"]}` and a task sets `guard: {}`
- **THEN** the loaded task denies no command patterns, as it would with `guard: {deny: []}`

#### Scenario: Empty requires clears the default

- **WHEN** the suite defaults set `requires: [datalad]` and a task sets `requires: []`
- **THEN** the loaded task requires nothing, and is not skipped on a machine without `datalad`

#### Scenario: Empty env changes nothing

- **WHEN** the suite defaults set `env: {A: "1"}` and a task sets `env: {}`
- **THEN** the loaded task's environment is `{A: "1"}`
