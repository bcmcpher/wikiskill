## Why

Redaction covers only part of what reaches `raw/`. Eval-run events are truncated but never redacted,
`wikiskill note` text is stored as typed, and both live loggers copy a delegation's `description`,
an activation's `input_summary` and a tool's `error` from the tool arguments unredacted. They do this
even though they redact those same arguments inside `tool_call`. A secret typed or produced in any of
these places is written to disk in the clear, and can be pooled with the run.

## What Changes

- Every event written to `raw/` is redacted, live or eval, when the collection's `[logging] redact`
  is on (the default). That covers each free-text field: assistant text, user turns, notes, tool
  input, output and error, delegation descriptions, activation input summaries, and error messages.
- **Eval runs (OpenCode and Claude Code backends):** events are redacted before they are truncated,
  as live logging already does. The environment snapshot is the unit's own environment, the one
  passed to the harness, which includes the suite's `env`. `[logging] redact = false` turns it off,
  as for live logging. `output_length` stays the original length.
- **Notes:** `wikiskill note` redacts its text using the environment of the process that runs it.
- **Live loggers (OpenCode plugin and Claude Code hooks):** `description`, `input_summary` and
  `error` go through the same redaction as the tool call's own fields. The Python and TypeScript
  sides stay in parity: new cases go in the shared fixtures.
- **Unchanged, and documented:** eval unit transcripts under `evals/<run>/units/` (`exports/`,
  `data/`, `stream.jsonl`, `run.ndjson`) are the harness's own records, and stay unredacted.
  `docs/data.md` says so plainly.

## Capabilities

### New Capabilities

None.

### Modified Capabilities
- `trace-log`: the redaction requirement covers every event written to the raw log, live and eval,
  and every free-text field in it, and states that transcripts are excluded.
- `correction-signal`: a note's text is redacted before it is stored.

## Impact

- `runner/opencode.py` and `runner/claude.py` normalisers, `runner/run.py` (passing the redaction
  setting and the unit's environment), and one shared helper in `runner/common.py`.
- `corrections.write_note`.
- `hooks.py`, `harness/opencode/plugin/wikiskill/mapper.ts` and `wikiskill-logger.ts` (the three
  extra fields), and `tests/fixtures/parity/` with both sides' parity tests.
- `docs/data.md`: its "Things to be aware of" section is updated.
- No schema change. `redactions[]` already exists on every event type.
- Existing logs are not rewritten. Events written before this change keep whatever they hold.
- No dependency on other open changes. `add-skill-diff` is independent of it.
