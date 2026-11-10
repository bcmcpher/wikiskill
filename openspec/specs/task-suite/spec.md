# task-suite Specification

## Purpose

Defines the declarative task-suite format for explicit evaluation: each task's prompt, expected route,
verifiers, rubric, split, fixtures, and required capabilities, held as data rather than code.

## Requirements

### Requirement: Tasks are declarative fixtures

A task suite MUST be a data file validated against the task-suite schema. Each task MUST declare an id
unique within the suite, a prompt, a split, and at least one expected outcome: an expected route, a
verifier, or a rubric.

#### Scenario: Adding a task

- **WHEN** a contributor adds a new entry to a suite file
- **THEN** `wikiskill suite check` validates it with no change to shared code

#### Scenario: Task with no expected outcome

- **WHEN** a task declares a prompt but no route, verifier, or rubric
- **THEN** `wikiskill suite check` rejects the suite and names the task

### Requirement: Prompts do not name what they test

A task prompt MUST NOT name its expected route's qualified identifier, so that routing is tested
rather than instructed. Where a prompt contains only one half of that identifier — the plugin, or
the component name — `wikiskill suite check` MUST report it for a reader to judge, and MUST NOT
refuse the suite: a component is often named after the subject it acts on, and a plugin is often an
ordinary word.

#### Scenario: Prompt names the route

- **WHEN** a routing task's prompt contains the string `disseminate/dataset-release` and that skill
  is its expected route
- **THEN** `wikiskill suite check` reports the leak and exits non-zero

#### Scenario: Prompt uses a word the route is named after

- **WHEN** a task's prompt says "this project", and its expected route is `project/status-report`
- **THEN** `wikiskill suite check` reports it as something to look at and exits zero

### Requirement: Existing fixture suites are read in place

wikiskill MUST read a collection's existing evaluation fixtures through an adapter, without copying or
modifying them. It MUST provide an adapter for data-science-harness `bench/` tasks and rubrics.

A fixture format MUST be recognised from the file itself rather than from a prefix the caller
types, and anything wikiskill requires that the fixture does not declare MUST be supplied by
wikiskill rather than requested as a new field.

#### Scenario: data-science-harness routing suite

- **WHEN** `wikiskill eval --suite <dsh>/bench/tasks/routing-lifecycle.yaml` runs
- **THEN** the file is recognised as a data-science-harness fixture, each task's `expected_skill` and
  `expected_delegates_to` become its expected route, and the data-science-harness repository is
  unchanged

#### Scenario: Fixture declares no split

- **WHEN** a data-science-harness fixture is read and it declares no train/validation/test split
- **THEN** wikiskill places its tasks in a split of its own choosing rather than failing or asking
  the fixture to add one

### Requirement: A suite declares secrets for its verifiers

A suite MUST accept `secrets`, a list of environment variable names, in `defaults` and on a task. A
task's secrets MUST be the union of its own list and the default list. Loading MUST fail when a name
is not a valid variable name, when it is a name either runner sets to isolate a unit or route it to
its model (a name starting with `XDG_`, `OPENCODE_`, `WIKISKILL_`, `CLAUDE_CODE_` or `ANTHROPIC_`,
or one of `CLAUDE_CONFIG_DIR`, `CLAUDECODE`, `DISABLE_AUTOUPDATER`, `HOME`, `PATH`), or when any
task's `env` sets it or expands it in a value as `$NAME` or `${NAME}`, whichever task declares it.
`ANTHROPIC_API_KEY` is the one exception to the reserved names.

#### Scenario: Default and task secrets join

- **WHEN** `defaults.secrets` is `[HF_TOKEN]` and a task sets `secrets: [GRADER_KEY]`
- **THEN** the loaded task's secrets are `HF_TOKEN` and `GRADER_KEY`

#### Scenario: A secret also set in env

- **WHEN** a task declares `secrets: [HF_TOKEN]` and `env: {HF_TOKEN: "x"}`
- **THEN** `wikiskill suite check` reports the conflict and exits non-zero

#### Scenario: Reserved name

- **WHEN** a suite declares `secrets: [OPENCODE_CONFIG_CONTENT]`
- **THEN** `wikiskill suite check` reports a reserved name and exits non-zero

#### Scenario: A secret that names an isolation variable

- **WHEN** a suite declares `secrets: [CLAUDE_CONFIG_DIR]`
- **THEN** `wikiskill suite check` reports a reserved name and exits non-zero

#### Scenario: A secret expanded in env

- **WHEN** a task declares `secrets: [HF_TOKEN]` and `env: {FOO: "$HF_TOKEN"}`
- **THEN** `wikiskill suite check` names `FOO` and `HF_TOKEN` and exits non-zero

#### Scenario: Another task expands a secret

- **WHEN** task A declares `secrets: [HF_TOKEN]` and task B, which declares none, sets
  `env: {FOO: "$HF_TOKEN"}`
- **THEN** `wikiskill suite check` names B, `FOO` and `HF_TOKEN` and exits non-zero

### Requirement: A command verifier can declare a structured result

A `command` verifier MUST accept:
- `result: json`, meaning its stdout is a JSON object;
- `pass_when`, a mapping from a top-level result field to a non-empty list of accepted JSON scalar
  values;
- `score`, the name of a top-level numeric result field to aggregate.

Loading MUST fail when `pass_when` or `score` is set without `result: json`, when `pass_when` is
empty, or when any of the three is set on a verifier of another kind.

#### Scenario: A grader with a verdict

- **WHEN** a task declares a command verifier with `result: json`,
  `pass_when: {verdict: [acceptable, indistinguishable]}` and `score: score`
- **THEN** `wikiskill suite check` accepts the suite

#### Scenario: pass_when without a result

- **WHEN** a command verifier sets `pass_when` and no `result`
- **THEN** `wikiskill suite check` reports the problem and exits non-zero

#### Scenario: Result on a regex verifier

- **WHEN** a `regex` verifier sets `result: json`
- **THEN** `wikiskill suite check` reports the problem and exits non-zero

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
