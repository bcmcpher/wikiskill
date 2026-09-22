## ADDED Requirements

### Requirement: Collection sources build into a harness layout

`wikiskill build --collection <name> --harness opencode` MUST build the collection's own sources into an
OpenCode layout, and the eval runner MUST install components through the same build. For OpenCode:
- A Claude `tools:` declaration MUST become neutral capabilities and, from them, the agent's permission
  and tool blocks.
- An explicit `capabilities:` declaration MUST take precedence over `tools:`.
- `model:` MUST be resolved through the alias table when `role_model` is absent.
- Two components that build to the same flat name MUST fail the build, naming both sources.
- The build MUST print each component's `plugin/name` to flat-name mapping.
- The source directories MUST NOT be written to.

#### Scenario: Claude-plugin doer on OpenCode

- **WHEN** `datalad/datalad-doer` declares `tools: Read, Bash, Grep, Glob` and is built for OpenCode
- **THEN** the built agent allows bash, enables read, grep, glob and list, and denies edit and
  webfetch

#### Scenario: Flat-name collision

- **WHEN** two plugins in one source each provide a skill named `status`
- **THEN** the build fails and names both `plugin/status` components

#### Scenario: Source untouched

- **WHEN** the collection build runs against a source inside a git repository
- **THEN** that repository's `git status --porcelain` output is unchanged afterwards
