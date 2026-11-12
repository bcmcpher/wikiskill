## 0. Minimal working core

The smallest shippable slice is groups 1 and 2: one marker-safe `withhold` used by the verifier and
the judge, which closes the judge's key and escaped-JSON gaps and the false leak refusal. Deferred
to later groups: the eval-event scrubber (3), the seed skip (4), and the `Task.suite_secrets`
removal (5). Each later group ships on its own.

- [ ] 0.1 Resolve the design's open question on the seed skip rule with the user, and record the answer in `design.md`

## 1. One marker-safe scrubber

- [ ] 1.1 Add `redact.withhold(obj, values, *, patterns=False)`: all forms, strings and dict keys, single-pass replacement, optional `PATTERNS` pass; verify with new cases in `tests/test_redact.py` for a string, a nested dict with a secret key, an escaped form, and `patterns=True` on an `sk-…` string
- [ ] 1.2 Make `hide_values_in` single-pass and `holds_withheld` split on `MARKER`; verify a test with the value `env_value` yields exactly one unaltered marker and `holds_withheld` returns false
- [ ] 1.3 Make the bytes path of `common.hide_in_files` single-pass; verify the existing binary-file test in `tests/test_runner_common.py` still passes and a new one with `env_value` leaves one run of `*`
- [ ] 1.4 Re-express `hide` and `hide_value` through `withhold` (or remove them and update callers); verify `uv run pytest tests/test_redact.py tests/test_runner_common.py` passes

## 2. Verifier and judge on `withhold`

- [ ] 2.1 `score/verify.py`: output uses `withhold(..., patterns=True)` when the task withholds anything; JSON result uses `withhold` and the marker-safe check; verify `tests/test_verify.py` passes and a new test with the value `env_value` in a JSON result is stored, not refused
- [ ] 2.2 `score/judge.py` `_hidden` uses `withhold(..., patterns=True)`; verify a new `tests/test_judge.py` case where a workdir file holds the value JSON-escaped and the prompt shows a marker
- [ ] 2.3 `runner/run.py` `_judge` stores `withhold(stored, hide, patterns=True)`; verify a test where the judge answer has the value as a dict key and `results.jsonl` shows a marker there

## 3. Eval events

- [ ] 3.1 `common.Scrubber.value` applies `withhold` with the declared values after `redact_value`; verify a test where an eval event's tool input has a declared value as a dict key and the logged event shows a marker
- [ ] 3.2 Confirm `tests/test_parity.py` passes unchanged, showing live-log redaction still matches `redact.ts`

## 4. Unit scrub skips unchanged seeded files

- [ ] 4.1 Add an `unchanged` predicate to `common.hide_in_files`; verify a test where a predicate-matched file holding the value is left unread and unchanged
- [ ] 4.2 OpenCode backend passes a predicate that matches a file under `SEED_PATHS` by size and `st_mtime_ns` against the seed; verify a test where an unchanged seeded file is skipped and a seeded file rewritten with the value is scrubbed
- [ ] 4.3 Measure: scrub one synthetic unit root with a 60 MB seeded `node_modules`, before and after; record both times in the commit message

## 5. Remove `Task.suite_secrets`

- [ ] 5.1 Remove `Task.suite_secrets`, `Task.withheld` and `Task.withheld_values`; pass the suite's set to `suite.env_problems`, `score/verify.py`, `runner/run.py` and each backend's environment building; verify `rtk grep -rn "suite_secrets\|\.withheld_values\|task\.withheld" src` returns nothing
- [ ] 5.2 Verify the existing "another task's secret is withheld too" tests pass for both backends, setup, verifiers and the `requires` check

## 6. Documentation

- [ ] 6.1 `docs/data.md`: state that declared secrets are replaced in every JSON form and in dict keys in every eval record, and record the two-keys-in-one-dict known limit; verify by reading the section

## 7. Verify

- [ ] 7.1 `uv run pytest` passes
- [ ] 7.2 `uv run ruff check src tests` passes
- [ ] 7.3 `~/.claude-node-tools/bin/openspec validate unify-secret-scrub --strict` passes
- [ ] 7.4 Live verification with a declared secret on both harnesses is outstanding: no batch machine is available. Record it as unverified in the resume note
