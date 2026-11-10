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
