## Why

A task that writes `setup: []`, `requires: []` or `guard: {}` means "none for this task", but
`suite.py` merges with `raw.get(x) or defaults.get(x)`, so an empty value counts as unset and the
suite default applies. A task meant to start from an empty directory silently gets the default
history; a task meant to run unguarded keeps the default denies. `guard: {deny: []}` does clear the
default, because the mapping is not empty, so the same intent behaves two ways.

## What Changes

- A task that sets `setup`, `requires` or `guard` uses its own value whenever the key is present,
  empty included. Only an absent key falls back to the suite default.
- `env` keeps merging: a task's `env: {}` adds nothing and removes nothing.
- The schema's descriptions of `setup`, `requires` and `guard` say that an empty value clears the
  default.
- **BREAKING** for a suite that writes an empty value and relied on the fallback. No suite in this
  repository does. The suite hash is the file's bytes, so such a suite keeps its hash while its
  meaning changes.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `task-suite`: a new requirement on how a task's `setup`, `requires`, `guard` and `env` combine with
  the suite defaults.

## Impact

- `src/wikiskill/suite.py`: `_as_task` tests for the key, not for a truthy value.
- `schemas/task-suite.schema.json`: three descriptions.
- `docs/evaluate-and-refine-a-skill.md` §3.3 and `docs/writing-suites.md`: the merge table and its
  note.
- Tests in `tests/test_suite.py`.
- Open decision: whether runs of a suite with an empty override, made before and after this change,
  may pool. Recommended: accept it, as no known suite is affected, and say so in the release note.
  The alternative is to fold the wikiskill version into pooling, which affects every run.
- The doc edit touches `docs/evaluate-and-refine-a-skill.md`, which lands with the
  `docs/evaluate-and-refine-guide` branch; merge that branch first.
