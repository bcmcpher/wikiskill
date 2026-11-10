## ADDED Requirements

### Requirement: A claude-plugin source accepts flat skill layouts

Discovery in a `claude-plugin` source MUST find a plugin's skills in one of three places, chosen per
plugin:
- `<plugin>/skills/<name>/SKILL.md` or `<plugin>/skill/<name>/SKILL.md`, named `<plugin>/<name>`,
  when the plugin has a `skills/` or a `skill/` directory. No other place is then scanned for that
  plugin's skills.
- `<plugin>/<name>/SKILL.md`, named `<plugin>/<name>`, when it has neither.
- `<plugin>/SKILL.md`, named `<plugin>/<plugin>`, when it has neither.

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

#### Scenario: A singular skill directory wins

- **WHEN** a plugin has `skill/a/SKILL.md` and also `b/SKILL.md`
- **THEN** discovery lists `<plugin>/a` only

#### Scenario: Layout detection reads the singular forms

- **WHEN** `wikiskill collection init` runs on a source whose only plugins hold `skill/`, `agent/`
  or `command/` directories
- **THEN** it detects the `claude-plugin` layout and lists their components

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

### Requirement: Two components of one kind and name fail the check and the build

`wikiskill collection check` MUST fail when two discovered components of one kind share a name, and
MUST name both paths. The build MUST fail when two entries it builds would write the same output
path. Only entries the build turns into components count: a file that is not a component, such as a
`README.md` in both `skills/` and `skill/`, MUST NOT fail the build.

#### Scenario: A plugin skill and a child of the same name

- **WHEN** a source holds `dup/SKILL.md` and `dup/dup/SKILL.md`
- **THEN** `wikiskill collection check` fails and names both paths, and the build fails because both
  build to `skills/dup`

#### Scenario: Plain files in both directory forms

- **WHEN** a plugin holds `skills/a/SKILL.md`, `skills/README.md` and `skill/README.md`
- **THEN** the build succeeds and installs the skill `a` only

### Requirement: A plugin that is a skill builds without the rest of its plugin

When the build installs a `<plugin>/SKILL.md` skill, it MUST copy the plugin directory's other files
as the skill's supporting files, except:
- the plugin's other skills;
- its plugin-level components: `agents/`, `commands/` and their singular forms, `.claude-plugin/`,
  `hooks/`, `.mcp.json`, `.lsp.json`, `output-styles/`, `workflows/`, `themes/`, `monitors/`, `bin/`
  and `settings.json`;
- hidden entries and installed files such as `.git/` and `node_modules/`;
- any directory that holds a `SKILL.md` at any depth.

`wikiskill collection check` MUST report a `${CLAUDE_SKILL_DIR}` path that names an excluded entry.

#### Scenario: Other skills, agents and commands are not copied

- **WHEN** `kit/SKILL.md`, `kit/child/SKILL.md` and `kit/commands/run.md` exist and the collection
  is built
- **THEN** the built `kit` skill holds neither `child/` nor `commands/`, and `child` and `run` are
  each built once in their own right

#### Scenario: Plugin metadata is not copied

- **WHEN** `solo/SKILL.md` sits beside `.claude-plugin/plugin.json`, `hooks/hooks.json`,
  `.mcp.json`, `monitors/monitors.json`, `output-styles/terse.md`, `bin/tool`, `node_modules/` and
  `keep.md`
- **THEN** the built `solo` skill holds only `SKILL.md` and `keep.md`

#### Scenario: A nested SKILL.md subtree is not copied

- **WHEN** `p/SKILL.md` sits beside `p/examples/inner/SKILL.md`
- **THEN** discovery lists only `p/p`, and no built layout holds a `SKILL.md` for `inner`
