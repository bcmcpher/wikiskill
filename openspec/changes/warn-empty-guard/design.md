## Context

`_as_task` in `src/wikiskill/suite.py` resolves `guard` with `_own`: a task's value, empty included,
replaces the default's, and only `deny` survives into `Task.guard_deny`. Both backends then deny
`BASE_DENY + task.guard_deny` (OpenCode through the guard plugin config, Claude Code through
`WIKISKILL_GUARD_DENY`). So a task's `guard: {}` keeps the base denies and loses the suite's own.
Suite warnings are collected in `parse()` and printed by `suite check` (`cli/suite.py`) and `eval`
(`cli/eval.py`). `_manifest` in `runner/run.py` writes `setup` only for tasks with a non-empty list.
Nothing in `src/` reads `setup` back from `run.json`. The DSH adapter emits no `guard`.

## Goals / Non-Goals

**Goals:**
- Report any task guard that loses a suite pattern, at load time, with the dropped patterns named.
- Make `run.json` show the effective `setup`, `requires` and `guard` of every task.

**Non-Goals:**
- Refusing such a suite. Clearing the guard can be deliberate (a task that tests a refusal to push).
- Warnings for `setup: []` or `requires: []`. Neither weakens isolation.
- Recording `BASE_DENY`. It belongs to the runner and the harness version, not the suite.
- Pooling or comparison rules based on the new keys.

## Decisions

- **Trigger on any dropped default pattern, not only on an empty guard.** `guard: {deny: [a]}` under a
  default `[a, b]` drops `b` just as silently as `{}` drops both. The check is a set difference:
  default deny patterns minus the task's. Alternative: warn only on `{}` and `deny: []`, which
  matches the RESUME note literally but misses narrowing.
- **The check needs the default's patterns.** `_as_task` discards them. Compute the warning in
  `parse()` from the raw document (`defaults.guard.deny` and whether the raw task sets `guard`)
  rather than adding a field to `Task`. A new `Task` field would ripple into every test fixture.
- **Record every task, empty lists included.** The value of the record is distinguishing "cleared"
  from "never set", which a non-empty-only map cannot do. Alternative: keep non-empty-only maps and
  add a `defaults` key echoing the suite defaults; more keys for a reader to combine.
  `setup` changes shape from "non-empty tasks only" to "every task". No code reads it; external
  readers of old runs must already handle missing tasks.
- **Keys:** `requires: {task: [..]}`, `guard: {task: [..deny..]}`, beside the existing `setup`, `env`
  and `secrets`.
- **Suite hash unchanged.** The hash covers the suite file's bytes. The warning and the manifest keys
  read the file; they do not alter it.

## Risks / Trade-offs

- [Warning noise on suites that clear the guard on purpose] → It is a `?` warning, not an error, and
  it names the patterns; a reader judges it. No suppression flag until one is asked for.
- [Ordering with `warn-unsent-followups`] → That change routes suite warnings into `run.json`
  `warnings`. Applied first, this warning is recorded by its mechanism with no extra work. Applied
  after it, this change would print the warning at `eval` but not record it. Apply
  `warn-unsent-followups` first; if the order flips, move its task 2.1 into this change.
- [Larger `run.json` for big suites] → Three short lists per task. The DSH suites have tens of tasks.
- [A DSH-adapted suite] → The adapter emits no `guard`, so no warning; its tasks record `[]`.

## Migration Plan

None. Old runs keep their manifests. Readers treat a missing `requires` or `guard` key as not recorded.

## Open Questions

Decisions for sign-off before apply. Each would change the specs as written:

1. Trigger: any dropped default pattern (as specified), or only an empty guard?
2. Record: every task with empty lists (as specified), or non-empty only plus a `defaults` echo?
3. Should `setup: []` or `requires: []` that clears a non-empty default also warn? Specified: no.
