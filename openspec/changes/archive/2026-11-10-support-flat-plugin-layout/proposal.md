## Why

A `claude-plugin` source finds skills only at `<plugin>/skills/<name>/SKILL.md`. Collections in the
wild also put a plugin's skills directly in the plugin directory (`<plugin>/<name>/SKILL.md`), or
make the plugin directory itself the skill (`<plugin>/SKILL.md`). skills-comm uses both for six of
its eight plugins, so wikiskill sees only two of them and cannot evaluate the rest.

## What Changes

- A plugin with no `skills/` directory has its skills discovered in its own subdirectories: each
  `<plugin>/<name>/SKILL.md` is the skill `<plugin>/<name>`.
- A plugin directory that holds a `SKILL.md` itself is the skill `<plugin>/<plugin>`.
- A plugin that has a `skills/` directory is read as today; the flat forms are not also scanned.
- Agents and commands keep their current locations; only skills gain flat forms.
- Discovery, watching, `plugins` narrowing, building and evaluation all see the flat skills.
  Nothing is written into the source directory.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `collection-config`: a new requirement on where a claude-plugin source's skills may sit.

## Impact

- `src/wikiskill/collection.py`: `Source.dirs_for`, `discover` and `_plugin_of`.
- The harness build that copies a skill's directory (`src/wikiskill/build*.py`): a `<plugin>/SKILL.md`
  skill's directory is the plugin directory, which may hold a README and other files.
- `docs/evaluate-and-refine-a-skill.md` §2 and `docs/` collection notes: the accepted layouts.
- Tests in `tests/test_collection.py` and `tests/test_build.py`, on synthetic trees only.
- No suite hash changes. A component's `source_hash` is unchanged for skills already discovered.
- No dependency on other open changes.
