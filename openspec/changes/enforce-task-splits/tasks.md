## 1. Record splits

- [ ] 1.1 `runner/run.py`: write `splits` (task id → split) to `run.json` beside `tasks`; verify
  with a test that a two-split suite records both
- [ ] 1.2 `compare.LoadedRun`: a `splits` property that reads `run.json`, else recovers from the
  suite file when its hash equals `suite_hash`, else returns none with a reason; verify with tests
  for a new run, an old run with an unchanged suite, and an old run with an edited or missing suite

## 2. Review

- [ ] 2.1 `review._eval_candidates`: keep only units of `train` tasks; live candidates unchanged;
  verify with a test that a run with train, val and test failures yields only train evidence
- [ ] 2.2 Report runs left out for unrecoverable splits (run id, unit count, reason) in `review`,
  `sample` and `--dry-run` output; verify with a test on an edited suite
- [ ] 2.3 Report "no train evidence" with split counts when filtering empties the eval side; verify
  with a test where all units are in `test` and no live sessions exist

## 3. Replay

- [ ] 3.1 `gate`: attach each task's split to motivating cases, the regression bank and fallen
  tasks, and give per-split bank rates per model in `replay.json` and `replay.md`; verify with a
  test where a `test` task falls and acceptance is not recommended
- [ ] 3.2 Show `unknown` for unrecoverable splits without changing the recommendation rule; verify
  with a test

## 4. DSH adapter

- [ ] 4.1 `adapters/dsh.py`: assign `train`/`val`/`test` from `sha256(task_id)` mod 5 (0–2/3/4) when
  no `--split` is given; rewrite the module comment; verify with a test that assignment is stable
  across two loads and across task order
- [ ] 4.2 `cli/eval.py`: `--split` defaults to none (per-task assignment) and still overrides every
  task when given; verify with a test

## 5. Documentation

- [ ] 5.1 Update the split text in `schemas/task-suite.schema.json` and `docs/templates/suite.yaml`
  to say review reads only `train`; `docs/data.md` gains `run.json` `splits`; the guide's §3.10 and
  §5.2 describe the filter and the old-run recovery; verify `bin/check` passes
