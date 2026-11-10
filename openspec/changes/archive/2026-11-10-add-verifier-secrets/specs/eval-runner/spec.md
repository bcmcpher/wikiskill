## ADDED Requirements

### Requirement: Secrets reach verifiers only

The runner MUST remove every secret the suite declares, in `defaults` or on any task, from every
process it starts for any unit's harness, including the session and any export step, on OpenCode and
on Claude Code. Setup commands and the `requires` check MUST NOT receive them. A task's command
verifiers MUST receive that task's own secrets with their host values, and MUST NOT receive a secret
only another task declares. Preflight probes, the harness version check and any other harness
process started for the run but not for one unit MUST run without every secret the suite declares,
whoever built the backend and before the first such process starts, a fill's checks included.

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

#### Scenario: Preflight does not get the secret

- **WHEN** a suite declares `secrets: [HF_TOKEN]` and preflight probes the model
- **THEN** the probe's harness process sees no `HF_TOKEN`

#### Scenario: Another task's secret is withheld too

- **WHEN** a suite has tasks A and B, only A declares `secrets: [HF_TOKEN]`, and `HF_TOKEN` is set
  on the host
- **THEN** B's session sees no `HF_TOKEN`, and B's command verifier sees no `HF_TOKEN` either

#### Scenario: A fill checks the version without the secret

- **WHEN** a caller builds a backend without naming the suite's secrets and asks whether a run can
  be filled
- **THEN** the harness version check it runs sees no `HF_TOKEN`

#### Scenario: Suite without secrets

- **WHEN** no task of a suite declares secrets
- **THEN** every session environment is the same as before this change

### Requirement: A run checks its secrets before starting and never records their values

`wikiskill eval` MUST refuse to start, before any unit runs, when a declared secret is not set on
the host, and MUST name each missing variable. It MUST refuse a secret whose value is under 8
characters or starts or ends with whitespace, and name it. It MUST also refuse to start when `--api-key-env`
names a declared secret, and, with `--harness claude-code` and no `--base-url`, when
`ANTHROPIC_API_KEY` is a declared secret. `run.json` MUST record each task's secret names and MUST
NOT record their values. Every secret value the suite declares MUST be redacted, every occurrence, from stored verifier
output, before the output is trimmed, from logged events, from `results.jsonl` and `run.json`, and
from everything sent to a rubric judge and stored from its answer. Once a unit's harness exits, and
after a preflight probe, the value MUST be replaced in every file under that unit's or probe's
directory, including the harness's raw stream, stderr, exports, setup log and state, whether or not
the collection redacts. wikiskill MUST NOT write the value into any file; a file in the working
directory is the task's own. The documentation MUST state that secrets keep the value out of the
session's environment and records but not out of reach of an agent that runs as the same user.

#### Scenario: Missing secret

- **WHEN** a suite declares `secrets: [HF_TOKEN]` and `HF_TOKEN` is unset
- **THEN** `wikiskill eval` exits non-zero naming `HF_TOKEN`, and no unit directory is created

#### Scenario: Verifier prints the secret

- **WHEN** a command verifier prints the value of a declared secret
- **THEN** the verifier output stored in `results.jsonl` shows a redaction marker in its place

#### Scenario: The session prints a secret it read from the host

- **WHEN** a session reads a declared secret's value from the host and prints it to its stream, its
  stderr and its state directory
- **THEN** after the unit, no file under the run directory outside the working directory contains
  the value, and the result's reason shows a redaction marker in its place

#### Scenario: A value with surrounding whitespace

- **WHEN** a declared secret's value ends in a carriage return
- **THEN** `wikiskill eval` exits non-zero naming the variable, and no unit directory is created

#### Scenario: Names, not values

- **WHEN** a run of a task with `secrets: [HF_TOKEN]` finishes
- **THEN** `run.json` lists `HF_TOKEN` for that task, and no file wikiskill writes under the run
  directory contains its value

#### Scenario: The judge does not see a secret a verifier left behind

- **WHEN** a command verifier writes the value of a declared secret to a file in the working
  directory, and the task has a rubric
- **THEN** the files shown to the judge show a redaction marker in its place, and the file itself is
  left as the verifier wrote it

#### Scenario: The endpoint key is a secret

- **WHEN** a suite declares `secrets: [HF_TOKEN]` and `wikiskill eval` is given
  `--api-key-env HF_TOKEN`
- **THEN** `wikiskill eval` exits non-zero naming `HF_TOKEN`, before a run directory is created
