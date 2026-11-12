## MODIFIED Requirements

### Requirement: Two components of one kind and name fail the check and the build

`wikiskill collection check` MUST fail when two discovered components of one kind share a name, and
MUST name both paths. The build MUST fail when two entries it builds would write the same output
path. Only entries the build turns into components count: a file that is not a component, such as a
`README.md` in both `skills/` and `skill/`, MUST NOT fail the build.

`wikiskill collection check` MUST also fail when two discovered components of one kind would build
to the same flat name, which is the component's bare name, even when their qualified names differ.
This covers two plugins of one source, two sources, and a claude-plugin source beside an
opencode-layout source. The check MUST name both qualified components and the flat path they share.
A skill, an agent and a command that share a bare name MUST NOT fail the check, as they build to
different directories.

#### Scenario: A plugin skill and a child of the same name

- **WHEN** a source holds `dup/SKILL.md` and `dup/dup/SKILL.md`
- **THEN** `wikiskill collection check` fails and names both paths, and the build fails because both
  build to `skills/dup`

#### Scenario: Plain files in both directory forms

- **WHEN** a plugin holds `skills/a/SKILL.md`, `skills/README.md` and `skill/README.md`
- **THEN** the build succeeds and installs the skill `a` only

#### Scenario: Two plugins provide a skill of one bare name

- **WHEN** plugins `a` and `b` of one claude-plugin source each provide a skill named `status`
- **THEN** `wikiskill collection check` fails and names `a/status`, `b/status` and `skills/status`,
  and the build fails for the same pair

#### Scenario: Two sources provide an agent of one bare name

- **WHEN** an opencode-layout source provides the agent `reviewer` and a claude-plugin source
  provides `kit/reviewer`
- **THEN** `wikiskill collection check` fails and names `reviewer`, `kit/reviewer` and
  `agents/reviewer`

#### Scenario: Different kinds share a bare name

- **WHEN** a plugin provides the skill `plan` and the agent `plan`
- **THEN** `wikiskill collection check` does not fail for that name

## ADDED Requirements

### Requirement: Two sources that provide one plugin name fail the check

`wikiskill collection check` MUST fail when two claude-plugin sources each provide a plugin of the
same name, and MUST name both plugin directories. The build already rejects this, because both
plugins would be mirrored to `plugins/<plugin>`; the check MUST agree with the build even when the
two plugins share no component name.

#### Scenario: Same plugin name, no shared components

- **WHEN** two claude-plugin sources each hold a plugin `kit`, one with the skill `alpha` and one
  with the skill `beta`
- **THEN** `wikiskill collection check` fails and names both `kit` directories

### Requirement: No built skill carries a nested skill

When the build installs any skill, it MUST leave out each top-level subdirectory of the skill that
holds a `SKILL.md` at any depth. This applies to a skill in a `skills/` directory, a flat skill
child of a plugin, and a plugin that is itself a skill, on both OpenCode and Claude Code. The
skill's other supporting files MUST still be copied. A plugin-root skill MUST keep its `evals/`
directory when that directory holds no `SKILL.md`.

`wikiskill collection check` MUST print a warning, not a failure, for each subdirectory left out for
this reason, naming the skill and the subdirectory.

#### Scenario: An ordinary skill with a nested SKILL.md

- **WHEN** `skills/guide/SKILL.md` sits beside `skills/guide/examples/demo/SKILL.md` and
  `skills/guide/references/notes.md`
- **THEN** the built `guide` skill holds `SKILL.md` and `references/notes.md`, holds no `examples/`,
  and no built layout holds a `SKILL.md` for `demo`

#### Scenario: Check warns about the left-out directory

- **WHEN** `wikiskill collection check` reads the collection with `skills/guide/examples/demo/SKILL.md`
- **THEN** it prints a warning naming `guide` and `examples/`, and does not fail for it

#### Scenario: A plugin-root skill keeps its evals

- **WHEN** `solo/SKILL.md` sits beside `solo/evals/suite.yaml`, which holds no `SKILL.md`
- **THEN** the built `solo` skill holds `evals/suite.yaml`
