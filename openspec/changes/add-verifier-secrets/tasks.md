## 0. Minimal working core

Smallest shippable slice: a suite declares `secrets`, the OpenCode session does not see them, and a
command verifier does. Deferred to later sections: Claude Code, redaction, the start-of-run check.

- [x] 0.1 Add `secrets` to `schemas/task-suite.schema.json` (defaults and task) and to the loader in
  `src/wikiskill/suite.py` with the union rule and the three load errors; verify with tests in
  `tests/test_suite.py` for each `task-suite` scenario
- [x] 0.2 Add the withheld-names helper to `src/wikiskill/runner/common.py` and call it from the
  OpenCode session and export environments and from `run_setup`; verify with
  `tests/test_runner_opencode.py` and `tests/test_runner_common.py` using a fake
  `FAKE_GRADER_TOKEN` variable
- [x] 0.3 Give command verifiers each secret's host value in `src/wikiskill/score/verify.py`; verify in
  `tests/test_verify.py`

## 1. Claude Code

- [ ] 1.1 Call the helper from `ClaudeCodeRunner.env_for`; verify in `tests/test_runner_claude.py`
  that the session environment lacks the secret and the verifier sees it

## 2. Records

- [ ] 2.1 Refuse to start when a declared secret is unset or shorter than 8 characters, naming each,
  before any unit directory exists; verify in `tests/test_run.py`
- [ ] 2.2 Record each task's secret names in `run.json`; verify a test asserts names present and
  values absent
- [ ] 2.3 Redact secret values from stored verifier output and logged events via `redact.redact`;
  verify with a verifier that echoes the secret, and a scan of every file under the run directory

## 3. Documentation

- [ ] 3.1 Document `secrets` in `docs/evaluate-and-refine-a-skill.md` §3 and `docs/writing-suites.md`,
  stating it covers the environment only; verify `bin/check` passes

## 4. Verify

- [ ] 4.1 `uv run pytest tests/test_suite.py tests/test_verify.py tests/test_run.py tests/test_runner_common.py tests/test_runner_opencode.py tests/test_runner_claude.py`
- [ ] 4.2 `uv run pytest` and `bin/check`
- [ ] 4.3 `openspec validate add-verifier-secrets --strict`
