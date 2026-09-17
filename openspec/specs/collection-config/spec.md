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
also a model under test.

#### Scenario: Roles on different endpoints

- **WHEN** the judge points at a remote vLLM server and the maintainer at a local Ollama model
- **THEN** each role's calls go to its own endpoint

#### Scenario: Judge equals a target

- **WHEN** an evaluation's target model list includes the configured judge model
- **THEN** the configuration is rejected with a message naming the model

### Requirement: Model aliases are resolved per harness

The manifest MUST map abstract model aliases to a concrete provider and model for each harness, and a
component whose alias has no mapping MUST inherit the calling agent's model rather than fail.

#### Scenario: Open-model alias table

- **WHEN** a collection agent declares `model: haiku` and the manifest maps `haiku` to
  `ollama/qwen3:30b-a3b` for OpenCode
- **THEN** the OpenCode build of that agent uses `ollama/qwen3:30b-a3b`

#### Scenario: Unmapped alias

- **WHEN** an agent's alias has no mapping for the target harness
- **THEN** the built agent omits a model, inherits its caller's, and the build output lists the alias
  as unmapped
