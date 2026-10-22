## 0. Minimal working core

Smallest shippable slice: discovery finds both flat forms, with names, on a synthetic tree. Deferred:
nothing; the build exclusion is in section 2 because a ROUTED run needs it.

- [x] 0.1 Add a synthetic fixture tree under `tests/fixtures/` with one plugin per form (`skills/`,
  `<plugin>/<name>/SKILL.md`, `<plugin>/SKILL.md`) plus a plugin that is a skill and holds flat skills;
  verify it holds no real collection's text

## 1. Discovery

- [x] 1.1 In `src/wikiskill/collection.py`, scan a plugin flat when it has no `skills/` or `skill/`
  directory, naming skills per the spec; verify with tests for each spec scenario in
  `tests/test_collection.py`
- [x] 1.2 Skip hidden directories, `agents/`, `commands/`, and subdirectories without a `SKILL.md`;
  verify with a test that `references/` and `scripts/` are not components
- [x] 1.3 Verify `plugins` narrowing and the watch list on the flat fixture, and that the existing
  collection tests pass unchanged

## 2. Build

- [x] 2.1 When a skill's directory is its plugin directory, copy it without child skill directories,
  `agents/`, `commands/` and `.claude-plugin/`; verify in `tests/test_build.py` that each skill is
  installed exactly once for both harness layouts
- [x] 2.2 Verify `git status` of the fixture tree is unchanged after `collection check` and a build

## 3. Documentation

- [x] 3.1 Describe the three skill locations in `docs/evaluate-and-refine-a-skill.md` §2; verify
  `bin/check` passes

## 4. Verify

- [ ] 4.1 `uv run pytest tests/test_collection.py tests/test_build.py tests/test_build_claude_code.py`
- [ ] 4.2 `uv run pytest` and `bin/check`
- [ ] 4.3 Against a read-only checkout of `../skills-comm`, run
  `env HOME="$(mktemp -d)" uv run wikiskill collection init sc --source ../skills-comm/plugins` with a
  temporary config dir, and verify all eight plugins' skills are listed and `git -C ../skills-comm status`
  is unchanged
- [ ] 4.4 `openspec validate support-flat-plugin-layout --strict`
