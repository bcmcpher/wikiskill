## 0. Minimal working core

Smallest shippable slice: `result: json` and `pass_when` decide a command verifier's pass, and the
result is stored in `results.jsonl`. Deferred to later sections: `score` aggregation, report and
CSV output.

- [x] 0.1 Add a synthetic grader fixture under `tests/fixtures/` that prints a JSON verdict and score
  chosen by an argument, with optional log lines and a crash mode; verify it runs with `python3`
- [x] 0.2 Add `result`, `pass_when` and `score` to `schemas/task-suite.schema.json` and the loader;
  verify with tests in `tests/test_suite.py` for each `task-suite` scenario
- [x] 0.3 Parse stdout, apply the pass rule, store the result, and raise `VerifierError` on missing or
  oversized JSON in `src/wikiskill/score/verify.py`; verify with tests in `tests/test_verify.py` for
  each scenario of "A structured result decides pass by its declared fields"

## 1. Report

- [x] 1.1 Add a seeded percentile bootstrap helper (stdlib); verify with tests for n = 1, constant
  scores, and repeat calls giving identical intervals
- [x] 1.2 Add a per-row score summary to `src/wikiskill/report.py` and a markdown section beside the
  rubric section; verify in `tests/test_score.py` or a new test for each scenario of "Scores are
  reported beside the pass rate", including a pre-change run fixture

## 2. Findings export

- [x] 2.1 Add the score columns to `CSV_COLUMNS` and fill them for `report` table rows in
  `src/wikiskill/findings.py`; add a slim score table; verify in `tests/test_findings_export.py` that
  values equal the run report's and that unscored studies leave the columns empty

## 3. Documentation

- [x] 3.1 Document the fields in `docs/writing-suites.md` and `docs/evaluate-and-refine-a-skill.md`,
  and the `result` key in `docs/data.md`; verify `bin/check` passes

## 4. Verify

- [ ] 4.1 `uv run pytest tests/test_suite.py tests/test_verify.py tests/test_score.py tests/test_findings_export.py`
- [ ] 4.2 `uv run pytest` and `bin/check`
- [ ] 4.3 Run an end-to-end unit test that scores the synthetic grader through `runner/run.py` with a
  stub session, and check `results.jsonl` and the report
- [ ] 4.4 `openspec validate add-scored-verifier --strict`
