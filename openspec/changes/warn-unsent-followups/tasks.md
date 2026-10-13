## 1. Suite check

- [ ] 1.1 In the suite loader, add a warning for each task that declares `followups`, naming the task
  and saying its turns are not sent; verify with a test that `suite check` prints it and exits zero
- [ ] 1.2 Verify with a test that a suite with no `followups` gets no such warning, and that adding
  the warning leaves the suite hash unchanged
- [ ] 1.3 Reword the `followups` description in `schemas/task-suite.schema.json` to say the field is
  accepted but not yet sent; verify `pytest` still passes the schema tests

## 2. Run record

- [ ] 2.1 Pass the loaded suite's warnings into the run so they are added to `run.warnings` before
  any unit runs; verify with a test that `run.json` `warnings` holds the follow-up warning for a
  suite that declares `followups`
- [ ] 2.2 Verify with a test that a suite with no warnings leaves `run.json` `warnings` unchanged,
  and that no unit's outcome or `passed` value depends on the warning

## 3. Documentation

- [ ] 3.1 `docs/data.md`: say that `run.json` `warnings` also holds the suite's warnings; update the
  `followups` row in `docs/evaluate-and-refine-a-skill.md` to mention the warning; verify `bin/check`
  passes
