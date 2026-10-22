## ADDED Requirements

### Requirement: Secrets reach verifiers only

For a task that declares secrets, the runner MUST remove each named variable from every process it
starts for the unit's harness, including the session and any export step, on OpenCode and on Claude
Code. Setup commands and the `requires` check MUST NOT receive them. Command verifiers MUST receive
each secret with its host value.

#### Scenario: Token withheld from the session

- **WHEN** `HF_TOKEN` is set on the host and a task declares `secrets: [HF_TOKEN]`
- **THEN** a command the agent runs in the session sees no `HF_TOKEN`, and the task's command
  verifier sees the host value

#### Scenario: Same rule on Claude Code

- **WHEN** the same task runs with `--harness claude-code`
- **THEN** the session sees no `HF_TOKEN`, and the command verifier sees the host value

#### Scenario: Setup does not get the secret

- **WHEN** a task declares `secrets: [HF_TOKEN]` and a setup command prints `$HF_TOKEN`
- **THEN** the setup command prints an empty value

#### Scenario: Task without secrets

- **WHEN** a task declares no secrets
- **THEN** its session environment is the same as before this change

### Requirement: A run checks its secrets before starting and never records their values

`wikiskill eval` MUST refuse to start, before any unit runs, when a declared secret is not set on
the host, and MUST name each missing variable. `run.json` MUST record each task's secret names and
MUST NOT record their values. A secret's value MUST be redacted from stored verifier output and
from logged events.

#### Scenario: Missing secret

- **WHEN** a suite declares `secrets: [HF_TOKEN]` and `HF_TOKEN` is unset
- **THEN** `wikiskill eval` exits non-zero naming `HF_TOKEN`, and no unit directory is created

#### Scenario: Verifier prints the secret

- **WHEN** a command verifier prints the value of a declared secret
- **THEN** the verifier output stored in `results.jsonl` shows a redaction marker in its place

#### Scenario: Names, not values

- **WHEN** a run of a task with `secrets: [HF_TOKEN]` finishes
- **THEN** `run.json` lists `HF_TOKEN` for that task, and no file under the run directory contains
  its value
