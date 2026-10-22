## ADDED Requirements

### Requirement: A claude-plugin source accepts flat skill layouts

Discovery in a `claude-plugin` source MUST find a plugin's skills in one of three places, chosen per
plugin:
- `<plugin>/skills/<name>/SKILL.md`, named `<plugin>/<name>`, when the plugin has a `skills/`
  directory. No other place is then scanned for that plugin's skills.
- `<plugin>/<name>/SKILL.md`, named `<plugin>/<name>`, when it has none.
- `<plugin>/SKILL.md`, named `<plugin>/<plugin>`, when it has none.

A plugin with no `skills/` directory MAY use both flat forms at once. Every consumer of discovery,
including the watch list, `plugins` narrowing, the build and evaluation, MUST see the same skills.
Discovery MUST NOT write to the source directory.

#### Scenario: Skills directly under the plugin

- **WHEN** a source holds `brain-extraction/brain-extraction/SKILL.md` and
  `brain-extraction/brain-extraction-qc/SKILL.md`, and `brain-extraction/` has no `skills/` directory
- **THEN** `wikiskill collection check` lists `brain-extraction/brain-extraction` and
  `brain-extraction/brain-extraction-qc`

#### Scenario: The plugin directory is the skill

- **WHEN** a source holds `fc-matrix-generation/SKILL.md` and `fc-matrix-generation/README.md`
- **THEN** discovery lists the skill `fc-matrix-generation/fc-matrix-generation`, and the README is
  not a component

#### Scenario: A skills directory wins

- **WHEN** a plugin has `skills/a/SKILL.md` and also `b/SKILL.md`
- **THEN** discovery lists `<plugin>/a` only

#### Scenario: Narrowing to a flat plugin

- **WHEN** a source declares `plugins = ["job-monitor"]` and `job-monitor/SKILL.md` exists
- **THEN** `wikiskill collection check` lists only `job-monitor/job-monitor`, and a ROUTED run
  installs only that skill

#### Scenario: Mixed layouts in one source

- **WHEN** one plugin uses `skills/`, another uses `<plugin>/<name>/SKILL.md`, and a third is itself
  a skill
- **THEN** discovery lists the skills of all three, each qualified by its plugin

#### Scenario: Source untouched

- **WHEN** `wikiskill collection check` reads a git-tracked source that uses the flat forms
- **THEN** that repository's `git status` is unchanged afterwards
