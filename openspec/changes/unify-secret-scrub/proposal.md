## Why

Declared secrets are kept out of an eval's records by three scrubbers with different coverage.
`results.jsonl`, `run.json` and verifier JSON use one that replaces every JSON form of a value and
reaches dict keys. The rubric judge's input and stored answer use the logger's, which replaces only
the raw form and leaves dict keys alone. Verifier output adds a pattern pass. A secret the judge
path misses is a leak the spec forbids. Two bugs sit beside this: a value that occurs inside the
redaction marker makes the leak check refuse a clean result, and the per-unit file scrub reads
every file of OpenCode's seeded `node_modules`, about 63 MB per unit.

## What Changes

- One scrubber for declared secrets in every eval record: every JSON form of each value, in every
  string and dict key, with an optional pattern pass for secret-shaped text. The judge's input and
  its stored answer move to it, so a value in a dict key or in escaped JSON no longer reaches them.
- The pattern pass applies to the same places as today: verifier output and the judge exchange,
  only when the suite declares a secret.
- Replacement is a single pass, so a value that occurs inside `[REDACTED:env_value]` cannot nest or
  mangle markers, and the leak check ignores the markers themselves.
- The per-unit file scrub skips a seeded OpenCode file that is unchanged from the seed, which was
  scrubbed when it was harvested. A seeded file the session changed is still scrubbed.
- `Task.suite_secrets` is removed. The suite's declared secrets are held once and passed to the
  places that withhold them.
- Live-session logging (`hooks.py`, the OpenCode plugin) is unchanged: it keeps the logger's
  scrubber, which must match `redact.ts`.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `eval-runner`: the secret requirement covers dict keys and every JSON form in the judge exchange,
  and a value inside the redaction marker no longer breaks the leak check.

## Impact

- `src/wikiskill/redact.py`: one entry point for declared secrets; single-pass replacement;
  marker-aware `holds_withheld`.
- `src/wikiskill/score/judge.py`, `src/wikiskill/runner/run.py` (`_judge`, `_scrub_unit`),
  `src/wikiskill/score/verify.py`, `src/wikiskill/runner/common.py` (`Scrubber`, `hide_in_files`).
- `src/wikiskill/runner/opencode.py`: the seed paths and seed location reach the unit scrub.
- `src/wikiskill/suite.py`, `runner/base.py`, `runner/claude.py`, `runner/opencode.py`,
  `score/verify.py`: `Task.suite_secrets` and `Task.withheld` replaced by the suite's set.
- Tests in `tests/test_redact.py`, `tests/test_runner_common.py`, `tests/test_verify.py`,
  `tests/test_judge.py`, `tests/test_suite.py`.
- No suite hash changes. Stored results of earlier runs are not rewritten.
- `add-run-archive` adds a pack-time secret scan. It should reuse this scrubber, so this change
  should be archived first.
