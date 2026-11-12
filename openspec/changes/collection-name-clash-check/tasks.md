## 0. Minimal working core

The smallest shippable slice is group 1: `collection check` fails on a bare-name clash across
plugins and sources. Groups 2 and 3 can follow in the same branch. Nothing is deferred out of this
change; the narrower nested-skill exclusion (design Decision 3) is out of scope.

## 1. Flat-name clash in the check

- [ ] 1.1 Add `Collection.flat_clashes(components)` in `src/wikiskill/collection.py`, grouping by
  `(kind, names.bare(name))` and reporting groups whose qualified names differ, each as both
  qualified names and the shared `<kind dir>/<flat>` path. Verify with unit tests in
  `tests/test_collection.py` for two plugins, two sources (opencode-layout beside claude-plugin),
  and a skill and an agent sharing a bare name (no clash).
- [ ] 1.2 Report it in `cmd_collection_check` (`src/wikiskill/cli/collection.py`) through `_report`
  as a failure. Verify with a `tests/test_cli.py` test that the check exits non-zero and prints
  both qualified names, on a fixture whose `build_collection` also raises `BuildError`.

## 2. Plugin-name clash in the check

- [ ] 2.1 Add `Collection.plugin_clashes()` that walks each claude-plugin source's
  `component_roots` and reports a plugin name provided twice, naming both directories. Verify with a
  `tests/test_collection.py` test of two sources each holding `kit` with disjoint skills.
- [ ] 2.2 Report it in `cmd_collection_check` as a failure. Verify with a `tests/test_cli.py` test.

## 3. No nested skill in any built skill

- [ ] 3.1 Extract `nested_skill_dirs(skill_dir)` in `src/wikiskill/build.py` from
  `plugin_skill_skip`, and have `plugin_skill_skip` call it. Verify the existing
  `test_a_plugin_skill_leaves_nested_skills_behind` still passes.
- [ ] 3.2 Union `nested_skill_dirs(entry)` into `skip` in `_build_skill` for every skill. Verify
  with a parametrised (both harnesses) test in `tests/test_build.py`:
  `skills/guide/examples/demo/SKILL.md` is not built, `references/notes.md` is.
- [ ] 3.3 Add a test that a plugin-root skill still keeps `evals/` holding no `SKILL.md`.
- [ ] 3.4 In `cmd_collection_check`, print a `~` warning per left-out directory, naming skill and
  directory, without adding a failure; have `_check_plugin_paths` use the same skip for every skill.
  Verify with a `tests/test_cli.py` test that the check exits zero and prints the warning.

## 4. Docs

- [ ] 4.1 Update the collection-check and build sections of `docs/` that describe duplicate names
  and plugin-root skill exclusions, and note that nested-skill directories are left out of every
  skill. Verify with `rtk grep -rn "nested" docs/`.

## 5. Verify

- [ ] 5.1 `uv run pytest -q` passes.
- [ ] 5.2 `uv run ruff check src tests` and `uv run ruff format --check src tests` pass.
- [ ] 5.3 `uv run wikiskill collection check <a real collection>` still prints `ok` for each
  collection under `${XDG_CONFIG_HOME:-~/.config}/wikiskill/` that builds today.
- [ ] 5.4 `~/.claude-node-tools/bin/openspec validate collection-name-clash-check --strict` passes.
