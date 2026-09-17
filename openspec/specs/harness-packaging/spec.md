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

### Requirement: A build only clears output it owns

`wikiskill build` MUST clear its output directory before writing, and MUST refuse, with an error
naming the directory, when the target holds files that no previous build produced. A refused build
MUST leave the target untouched.

#### Scenario: Output directory points at a harness config directory

- **WHEN** `wikiskill build --out` names a directory holding the user's own OpenCode configuration
- **THEN** the build fails with an error naming that directory, and nothing in it is deleted

#### Scenario: Rebuilding into a previous build's output

- **WHEN** `wikiskill build` runs twice into the same directory and a component was removed from the
  source tree between runs
- **THEN** the second build succeeds and the removed component is gone from the output

#### Scenario: Building into an empty directory

- **WHEN** the output directory exists and is empty
- **THEN** the build proceeds
