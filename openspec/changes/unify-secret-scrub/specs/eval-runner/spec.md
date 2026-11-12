## MODIFIED Requirements

### Requirement: A run checks its secrets before starting and never records their values

`wikiskill eval` MUST refuse to start, before any unit runs, when a declared secret is not set on
the host, and MUST name each missing variable. It MUST refuse a secret whose value is under 8
characters or starts or ends with whitespace, and name it. It MUST also refuse to start when `--api-key-env`
names a declared secret, and, with `--harness claude-code` and no `--base-url`, when
`ANTHROPIC_API_KEY` is a declared secret. `run.json` MUST record each task's secret names and MUST
NOT record their values. Every secret value the suite declares MUST be redacted, every occurrence, from stored verifier
output, before the output is trimmed, from logged events, from `results.jsonl` and `run.json`, and
from everything sent to a rubric judge and stored from its answer. Redaction in `results.jsonl`,
`run.json`, verifier output and everything sent to or stored from a rubric judge MUST be the same:
it MUST replace the value as written and as JSON writes it, escaped or not, in every string and in
every dict key. Verifier output and the judge exchange MUST also have secret-shaped text redacted
when the suite declares a secret. A value that occurs inside the redaction marker MUST NOT nest or
alter markers, and MUST NOT make a result count as still holding the value. Once a unit's harness exits, and
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

#### Scenario: The judge does not see a secret in escaped JSON

- **WHEN** a declared secret's value holds a quote or a backslash, and a file in the working
  directory holds it as a JSON string writes it, escaped
- **THEN** the text sent to the judge shows a redaction marker in its place

#### Scenario: A secret as a key of the judge's answer

- **WHEN** the judge's answer holds the value of a declared secret as a key of an object
- **THEN** the answer stored in `results.jsonl` shows a redaction marker in place of that key

#### Scenario: A value inside the redaction marker

- **WHEN** a declared secret's value is `env_value` and a command verifier prints a JSON result
  holding it as a string
- **THEN** the result is stored with one redaction marker in place of the value, the marker itself
  is unaltered, and the verifier is not refused for printing a secret it cannot redact

#### Scenario: A seeded file the session changed

- **WHEN** an OpenCode session writes a declared secret's value into a file it copied from the
  seed, under its unit's `config/opencode/node_modules`
- **THEN** after the unit, that file does not contain the value

#### Scenario: The endpoint key is a secret

- **WHEN** a suite declares `secrets: [HF_TOKEN]` and `wikiskill eval` is given
  `--api-key-env HF_TOKEN`
- **THEN** `wikiskill eval` exits non-zero naming `HF_TOKEN`, before a run directory is created
