# harness-packaging Specification

## Purpose

Defines how wikiskill's own skills, commands and meta-agents are written once and built into each
supported harness's layout, so every harness runs the same instructions and installs cleanly.

## Requirements

### Requirement: wikiskill components are single-source

wikiskill's skills, commands, and agents MUST be authored once under a harness-neutral source tree,
and every harness layout MUST be generated from that tree by `wikiskill build`, never edited by hand.

#### Scenario: Editing a component

- **WHEN** a source skill under `harness/source/skills/` changes and `wikiskill build` runs
- **THEN** the change appears in every harness layout that build produces

#### Scenario: OpenCode agent permissions

- **WHEN** a neutral agent declares `capabilities: [read, search]` and is built for OpenCode
- **THEN** the built agent has `mode: subagent` and a permission block that denies edit, bash, and web
  access

### Requirement: Installation is idempotent and reversible

`wikiskill install` MUST write only files it owns, MUST record which files it wrote, and
`wikiskill install --uninstall` MUST remove exactly those files.

#### Scenario: Installing twice

- **WHEN** `wikiskill install --harness opencode` runs twice in a row
- **THEN** the second run reports no changes and creates no duplicates

#### Scenario: Uninstalling next to user files

- **WHEN** the user's OpenCode config directory also holds their own skills and the user uninstalls
- **THEN** only wikiskill's recorded files are removed and the user's files are untouched
