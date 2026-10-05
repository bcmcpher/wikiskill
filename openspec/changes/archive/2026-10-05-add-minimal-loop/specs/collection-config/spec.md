## ADDED Requirements

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

## MODIFIED Requirements

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
