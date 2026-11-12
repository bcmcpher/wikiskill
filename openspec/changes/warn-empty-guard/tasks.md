## 0. Minimal working core

The smallest shippable slice is group 1: the `suite check` warning. Groups 2 and 3 add the run
record and the documentation. Nothing is deferred beyond this change; a suppression flag for the
warning is out of scope.

## 1. Suite check

- [ ] 1.1 In `parse()` in `src/wikiskill/suite.py`, warn for each task that sets `guard` and leaves
  out a default deny pattern, naming the task, the dropped patterns and that base denies still
  apply; verify with tests for `guard: {}`, a narrower `deny`, a wider `deny` and a suite with no
  default guard
- [ ] 1.2 Verify with a test that `suite check` prints the warning and exits zero, and that the
  suite hash of the fixture is the same before and after the change
- [ ] 1.3 Add to the `guard` description in `schemas/task-suite.schema.json` that dropping a suite
  pattern is reported; verify the schema tests pass

## 2. Run record

- [ ] 2.1 In `_manifest` in `src/wikiskill/runner/run.py`, record `setup`, `requires` and `guard`
  for every task, empty lists included, without `BASE_DENY`; verify with a test on a suite where
  one task clears each default and one inherits it
- [ ] 2.2 Verify with a test that a `run.json` without `requires` or `guard` still loads in
  `report`, `compare` and `eval --fill`
- [ ] 2.3 If `warn-unsent-followups` is archived, verify with a test that `run.json` `warnings`
  holds the guard warning; if not, note in the commit that the warning is printed but not recorded

## 3. Documentation

- [ ] 3.1 `docs/data.md`: add `requires` and `guard` to the `run.json` key list and say each map
  holds every task; in `docs/evaluate-and-refine-a-skill.md`, mention the guard warning beside the
  empty-override note (§3.3) and the guard description (§3.5);
  verify `bin/check` passes

## 4. Verify

- [ ] 4.1 `uv run pytest`
- [ ] 4.2 `uv run wikiskill suite check` on a fixture suite with `guard: {}` under a default guard
- [ ] 4.3 `~/.claude-node-tools/bin/openspec validate warn-empty-guard --strict`
