## 0. Minimal working core

The smallest shippable slice is groups 1 and 2: eval events in `raw/` are redacted on both
backends, using the unit's environment and the collection's switch. That closes the largest gap,
since every eval tool output reaches disk today. Notes (group 3), the three live fields (group 4) and
docs (group 5) follow. Each group is small, so all of them can land in one pass.

Deferred: a `log validate` warning for old unredacted logs (design Open Questions), and any
redaction of unit transcripts (excluded by decision).

## 1. Shared helper

- [x] 1.1 Add `Scrubber(enabled, secrets, limit)` to `runner/common.py`, with `text(raw) ->
  (text, truncated, redactions)` (redact, then bound) and `value(obj) -> (obj, redactions)`. Verify:
  unit tests in `tests/test_runner_common.py` for a key, an env value, a key straddling the bound
  (the marker stored, no partial key), `enabled=False`, and a nested input.

## 2. Eval runs

- [x] 2.1 Pass `redact` from `cli/eval.py` to both backends (`coll.redact`, defaulting to `True`),
  next to `output_limit_bytes`. Verify: a CLI-level test with `[logging] redact = false` reaches the
  backend as `False`.
- [x] 2.2 OpenCode normaliser: build the `Scrubber` from `env_secrets(self.env_for(unit, root))`.
  Then:
  - route assistant text, tool output, tool error, delegation description, activation input summary
    and error messages through it;
  - route tool `input` through `value`;
  - attach the merged `redactions` to each event.

  Verify: fixture-based normaliser tests in `tests/test_runner_opencode.py`:
  - a token in tool output and in input;
  - a suite `env` value echoed in assistant text;
  - `redact=False` keeps both;
  - `output_length` is unchanged.
- [x] 2.3 Claude Code normaliser: the same as 2.2, using its own `env_for`. Verify: the same cases
  in `tests/test_runner_claude.py`, against `tests/fixtures/claude-code/` stream data.
- [x] 2.4 Check the unit transcripts are untouched. Verify: a test asserts that a secret in a fixture
  `stream.jsonl` or export is still present in the unit directory after normalising, and is
  redacted in the written raw event.

## 3. Notes

- [x] 3.1 `corrections.write_note` redacts the text with `env_secrets(os.environ)` when
  `collection.redact`, and sets `redactions`. Verify: tests in `tests/test_corrections.py` for a key in
  a note, an env value, and `redact = false`; the event still validates against the schema.

## 4. Live loggers: the three fields

- [x] 4.1 Add parity cases for the delegation `description`, the activation `input_summary` and the
  tool `error`: a password assignment, a key, and the 500-character cut after redaction. Verify:
  `test_parity.py` and the bun parity test both read the new cases, and both fail before 4.2/4.3.
- [x] 4.2 `hooks.py`: redact the three fields, before the 500-character cut, and merge the counts.
  Verify: the 4.1 parity cases pass on the Python side, and `tests/test_hooks.py` covers a delegation
  event end to end.
- [x] 4.3 `mapper.ts` and `wikiskill-logger.ts`: the same as 4.2. Verify: the parity cases pass in
  `bun test`, and the plugin contract test still runs and passes.

## 5. Docs

- [x] 5.1 Update `docs/data.md`. "Redaction, truncation, and what is never recorded" now says it
  covers eval events and notes. "Things to be aware of" drops the two gaps and keeps the statement
  that unit transcripts are unredacted. Verify: the doc's claims match the code (grep for the
  `Scrubber` call sites and `write_note`).

## 6. Verify

- [x] 6.1 `bin/check` passes (ruff, pyright, pytest, both bun suites and tsc), and the pytest and bun
  counts only grow.
- [x] 6.2 End to end on a scratch collection: a toy suite whose task echoes a fake `ghp_…` token and
  a suite `env` value. After `wikiskill eval`, `grep -r ghp_ raw/` finds nothing and
  `grep -r ghp_ evals/<run>/units/` still finds the transcript copy. With `redact = false`, the raw
  event keeps the token.

  Run 2026-10-06 on the GB10, `ollama/gemma4:latest`, OFF, in a scratch XDG under `/tmp`. The task
  set `DATASET_TOKEN: "s3cr3t-value-123"`, wrote `ghp_` + 36 `A` to `secret.txt` in `setup`, and
  asked for `cat secret.txt; echo $DATASET_TOKEN`; a `final_text` regex verifier on `s3cr3t` passed
  both times. Run `01M490PDCPZZMSVNYAHDK45KVH` (redact on): no hit in `raw/`, two events carry
  `redactions: [{api_key: 1}, {env_value: 1}]`, and the unit's `run.ndjson`, export and
  `opencode.db` keep both values. Run `01M490QWASXDQ1J0HX1ABWR2P7` (`[logging] redact = false`):
  `raw/` keeps the token and the env value, twice each.
- [x] 6.3 `openspec validate redact-eval-and-notes --strict --no-interactive`.
