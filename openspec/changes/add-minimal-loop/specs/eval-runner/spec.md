## ADDED Requirements

### Requirement: Components under evaluation run on the model under test

When a collection is installed into an evaluation run, the runner MUST remove every model pin from the
built components, so each subagent runs on the model the unit is evaluating. Build and install outside
evaluation MUST keep resolved pins.

#### Scenario: Pinned doer in an OpenCode run

- **WHEN** an agent declaring `model: haiku` is installed for a unit targeting `opencode/big-pickle`
- **THEN** the installed agent has no `model` key and runs on `opencode/big-pickle`

### Requirement: Suites declare their run environment

A suite MUST be able to declare, at suite and task level, environment variables and setup commands.
- The runner MUST set the variables in each unit's harness process, with a task's value overriding
  the suite's, and MUST NOT let them replace the variables it uses to isolate the run.
- It MUST run the setup commands in the unit's workdir, in order, with those variables, after
  fixtures are copied and before the session starts.
- A setup command that fails MUST make the unit an `infra_error`, never a model failure.
- Both MUST be recorded in the run's captured configuration.

This is runner mechanics. The starting state a task needs belongs with whoever writes the task, and
a fixture read in place is never edited to carry it.

#### Scenario: DataLad autosave off

- **WHEN** a suite declares `env: { DATALAD_AUTOSAVE: "0" }`
- **THEN** every unit's harness process sees `DATALAD_AUTOSAVE=0`, and `run.json` records it

#### Scenario: A dataset to start from

- **WHEN** a task declares `setup: ["datalad create --force ."]`
- **THEN** the session starts in a workdir that is already a DataLad dataset

#### Scenario: Setup fails

- **WHEN** a setup command exits non-zero
- **THEN** the unit is recorded as `infra_error` with the command and its last output lines, and no
  session is started
