## ADDED Requirements

### Requirement: Models can be described in a catalogue

A model catalogue MUST be a TOML file of `[models."<model>"]` tables with `family`, and optionally
`size_b` and `shape`. A key MUST match a model with or without its provider. A malformed catalogue
MUST be refused, naming the entry. A model the catalogue does not list MUST be shown as uncatalogued,
never dropped. Families MUST come from the catalogue and never be guessed from a model's name.

#### Scenario: A provider-qualified model

- **WHEN** the catalogue has `[models."qwen3:30b-a3b"]` and a run used `ollama/qwen3:30b-a3b`
- **THEN** that model is given the catalogue's family and size

### Requirement: Pooled tables group models by family and size

With `--models-file`, the leaderboard and the version board MUST give each model's family and size,
group per-model rows by family, and order them by size within a family. Uncatalogued models MUST
follow, by name.

#### Scenario: A size ladder

- **WHEN** the catalogue gives `granite4.1:3b`, `:8b` and `:30b` family `granite`
- **THEN** the three appear together in that order, with their sizes
