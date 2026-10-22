## ADDED Requirements

### Requirement: A suite declares secrets for its verifiers

A suite MUST accept `secrets`, a list of environment variable names, in `defaults` and on a task. A
task's secrets MUST be the union of its own list and the default list. Loading MUST fail when a name
is not a valid variable name, when it starts with a reserved prefix (`XDG_`, `OPENCODE_`,
`WIKISKILL_`), or when the same task's `env` sets it.

#### Scenario: Default and task secrets join

- **WHEN** `defaults.secrets` is `[HF_TOKEN]` and a task sets `secrets: [GRADER_KEY]`
- **THEN** the loaded task's secrets are `HF_TOKEN` and `GRADER_KEY`

#### Scenario: A secret also set in env

- **WHEN** a task declares `secrets: [HF_TOKEN]` and `env: {HF_TOKEN: "x"}`
- **THEN** `wikiskill suite check` reports the conflict and exits non-zero

#### Scenario: Reserved name

- **WHEN** a suite declares `secrets: [OPENCODE_CONFIG_CONTENT]`
- **THEN** `wikiskill suite check` reports a reserved name and exits non-zero
