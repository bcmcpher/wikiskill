## Why

`wikiskill collection check` and the collection build disagree in two places. The check compares
qualified names (`a/status`, `b/status`), but the build writes a flat layout and fails when two
components share a bare name. A collection can pass the check and then fail its first eval. Also,
an ordinary skill copies a subdirectory that holds a nested `SKILL.md` into its build. OpenCode
loads every `SKILL.md` under `skills/`, so it installs a skill that discovery never reported. A
plugin-root skill already leaves such directories out.

## What Changes

- `collection check` fails when two discovered components of one kind build to the same flat name,
  across plugins and across sources. It names both qualified components and the shared flat path.
- `collection check` fails when two sources provide a plugin of the same name, which the build
  already rejects because both would share `plugins/<plugin>`.
- The build leaves out of an ordinary skill every top-level subdirectory that holds a `SKILL.md` at
  any depth. This is the rule a plugin-root skill already follows.
- `collection check` warns (does not fail) for each subdirectory the build leaves out of a skill
  for this reason, so the author sees that the content is not installed.
- A plugin-root skill keeps its `evals/` directory. This change does not alter that.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `collection-config`: the duplicate-name check covers flat names and plugin names; nested-skill
  directories are left out of every skill, not only a plugin-root skill; check warns about them.

## Impact

- `src/wikiskill/collection.py`: a flat-name clash list and a plugin-name clash list beside
  `Collection.duplicates`.
- `src/wikiskill/build.py`: `_build_skill` skips nested-skill directories for every skill; the
  nested-directory rule moves out of `plugin_skill_skip` into a shared helper.
- `src/wikiskill/cli/collection.py`: two new failure lists and one new warning list in
  `cmd_collection_check`.
- Tests in `tests/test_build.py` and the collection-check tests; new fixtures under
  `tests/fixtures/`.
- **Built output changes** for any skill that holds a nested `SKILL.md`: the subdirectory is no
  longer installed. Component version hashes read only the main file, so no version hash and no
  suite hash changes. Runs of such a skill made before and after the change installed different
  files on OpenCode; no known collection has one.
- Collections that today pass the check but fail the build will now fail the check. No collection
  that builds today starts to fail.
- No dependency on other pending changes.
