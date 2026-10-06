# collection-config Specification

## Purpose

Defines the collection manifest: which skills and agents wikiskill watches, where their sources live,
which models serve each meta-role, and how abstract model aliases resolve in each harness.

## Requirements

### Requirement: A collection is declared by a manifest

Each watched collection MUST be declared in a manifest that names the collection, its source
directories and their layout, and a watch list of skills and agents. Reading a manifest or its
sources MUST NOT write to the source directories.

#### Scenario: Declaring a collection

- **WHEN** the user runs `wikiskill collection init <name> --source <dir>`
- **THEN** a manifest is written under the wikiskill config directory listing the discovered skills
  and agents, with a watch list for the user to edit

#### Scenario: A watch-list entry does not resolve

- **WHEN** the watch list names a skill that is not present in any source directory
- **THEN** `wikiskill collection check` reports it as unresolved and exits non-zero

#### Scenario: Checking a git-tracked source

- **WHEN** `wikiskill collection check` runs against a source directory inside a git repository
- **THEN** that repository's `git status` is unchanged afterwards

### Requirement: Meta-roles are configured per role

The manifest MUST let each meta-role — judge, maintainer, proposer — name its own OpenAI-compatible
endpoint and model, independently of the models under test, and MUST reject a judge model that is
also a model under test. A role MAY state its model's context in tokens, which work sent to that role
is sized by.

#### Scenario: Roles on different endpoints

- **WHEN** the judge points at a remote vLLM server and the maintainer at a local Ollama model
- **THEN** each role's calls go to its own endpoint

#### Scenario: Judge equals a target

- **WHEN** an evaluation's target model list includes the configured judge model
- **THEN** the configuration is rejected with a message naming the model

#### Scenario: Role context

- **WHEN** `[roles.maintainer]` sets `context_tokens = 32768`
- **THEN** the collection loads with that context on the maintainer role, and a context that is not
  a positive integer is rejected

### Requirement: Model aliases are resolved per harness

The manifest MUST map abstract model aliases to a concrete provider and model for each harness, and a
component whose alias has no mapping MUST inherit the calling agent's model rather than fail. An alias
MAY map to another alias of the same harness, one hop at most. A chain that is cyclic or does not end
in a `provider/model` string MUST be rejected by `wikiskill collection check`.

#### Scenario: Open-model alias table

- **WHEN** a collection agent declares `model: haiku` and the manifest maps `haiku` to
  `ollama/qwen3:30b-a3b` for OpenCode
- **THEN** the OpenCode build of that agent uses `ollama/qwen3:30b-a3b`

#### Scenario: Tier alias

- **WHEN** the OpenCode table maps `haiku = "small"` and `small = "opencode/big-pickle"`
- **THEN** an agent declaring `model: haiku` builds with `opencode/big-pickle`

#### Scenario: Cyclic alias

- **WHEN** the OpenCode table maps `small = "large"` and `large = "small"`
- **THEN** `wikiskill collection check` rejects the manifest and names both aliases

#### Scenario: Unmapped alias

- **WHEN** an agent's alias has no mapping for the target harness
- **THEN** the built agent omits a model, inherits its caller's, and the build output lists the alias
  as unmapped

### Requirement: A source can be narrowed to a unit

A claude-plugin source entry MUST accept a `plugins` list, and discovery, watching, building and
evaluation MUST see only the components of the listed plugins. A listed plugin that does not exist
MUST be reported by `wikiskill collection check` as unresolved.

#### Scenario: One plugin under evaluation

- **WHEN** the data-science-harness source declares `plugins = ["datalad"]`
- **THEN** `wikiskill collection check` lists only `datalad/datalad-doer`, and a ROUTED run installs
  no component from any other plugin

#### Scenario: Misspelled plugin

- **WHEN** a source declares `plugins = ["datalod"]`
- **THEN** `wikiskill collection check` reports `datalod` as unresolved and exits non-zero

### Requirement: The judge role can name several models

`[roles.judge]` MAY name `models`, a list of two or more distinct models on its one endpoint, instead
of `model`. Naming both, or an empty or repeated list, MUST be rejected. Every model in the list MUST
be checked against the models under test, as a single judge is.

#### Scenario: A three-model panel

- **WHEN** `[roles.judge]` sets `models = ["gpt-oss:120b", "llama3.3", "nemotron-3.5-lightning"]`
- **THEN** the collection loads with a three-model judge panel on the role's endpoint

#### Scenario: A panel member under test

- **WHEN** a run's models include `llama3.3`, which is in the judge panel
- **THEN** the run is refused, naming `llama3.3`
