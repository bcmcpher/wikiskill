## 1. Loader

- [ ] 1.1 In `_as_task` in `src/wikiskill/suite.py`, take `setup`, `requires` and `guard` from the
  task when the key is present, and from the defaults only when it is absent; verify with tests for
  each of the spec's scenarios
- [ ] 1.2 Verify with the existing `test_setup_is_the_tasks_own_or_the_suite_defaults` and the env
  tests that a non-empty task value and an absent key behave as before

## 2. Schema and documentation

- [ ] 2.1 In `schemas/task-suite.schema.json`, say in the `setup`, `requires` and `guard`
  descriptions that a task's value, empty included, replaces the default's
- [ ] 2.2 In `docs/evaluate-and-refine-a-skill.md` §3.3, replace the note that an empty value does
  not clear a default; add the rule to `docs/writing-suites.md` §3; verify `bin/check` passes
