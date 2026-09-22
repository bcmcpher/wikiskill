## ADDED Requirements

### Requirement: Components under evaluation run on the model under test

When a collection is installed into an evaluation run, the runner MUST remove every model pin from the
built components, so each subagent runs on the model the unit is evaluating. Build and install outside
evaluation MUST keep resolved pins.

#### Scenario: Pinned doer in an OpenCode run

- **WHEN** an agent declaring `model: haiku` is installed for a unit targeting `opencode/big-pickle`
- **THEN** the installed agent has no `model` key and runs on `opencode/big-pickle`

### Requirement: Suites declare their run environment

A suite MUST be able to declare environment variables at suite and task level. The runner MUST set
them in each unit's harness process, with a task's value overriding the suite's, and MUST record them
in the run's captured configuration.

#### Scenario: DataLad autosave off

- **WHEN** a suite declares `env: { DATALAD_AUTOSAVE: "0" }`
- **THEN** every unit's harness process sees `DATALAD_AUTOSAVE=0`, and `run.json` records it
