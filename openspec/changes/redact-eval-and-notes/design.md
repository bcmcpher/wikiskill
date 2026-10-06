## Context

See proposal.md for why. What exists today:

- **Live, Python** (`hooks.py`): `env_secrets(os.environ)` is taken once per hook process.
  `Logger.text` redacts before `bound()`. A tool call's input goes through `redact_value`, and
  `merge()` combines the redaction counts. The delegation `description`, the activation
  `input_summary` (`str(args…)[:500]`) and the tool `error` are not redacted.
- **Live, TypeScript** (`mapper.ts`): the same, through `redact`, `redactValue` and `bound` gated on
  `options.redactEnabled`, with the same three fields left out.
- **Eval** (`runner/opencode.py` and `runner/claude.py` normalisers): each calls `redact.bound()`
  only. `run._write_events` appends whatever `normalize` returns. Each backend already knows
  `output_limit_bytes` (set by `cli/eval.py` from the collection) and can rebuild a unit's
  environment with `env_for(unit, root)`. `Trajectory.unit` is available inside `normalize`.
- **Notes** (`corrections.write_note`): the text is written as given.
  `corrections.scan` already redacts its diffs with `env_secrets`.
- `Collection.redact` (`[logging] redact`, default true) already reaches both live loggers through
  `runtime.json`.

## Goals / Non-Goals

**Goals:**
- One redaction behaviour for everything in `raw/`, with redaction before truncation everywhere.
- Python and TypeScript stay identical, shown by the shared parity fixtures.

**Non-Goals:**
- Redacting harness transcripts in eval unit directories. The user chose to keep them as evidence
  and document them.
- Rewriting existing logs. There will be no migration command; a user who needs to can delete old
  day directories.
- New redaction patterns. The pattern table is unchanged.

## Decisions

**D1. One eval helper, used by both normalisers.** Add a `Scrubber` to `runner/common.py`, built
from `(enabled, secrets, limit)`. Its `text(raw)` returns `(text, truncated, redactions)`: `redact()`
first, then `bound()`. That is the order and return shape of `hooks.Logger.text`. Its `value(obj)`
wraps `redact_value`. Every normaliser site that calls `redact.bound(...)` today calls
`scrubber.text(...)` instead, and the tool-call sites also run `input` through `value`. Each event
passes its collected redactions through `redact.merge`. Alternative: a post-pass in
`run._write_events` that walks every event. Rejected, because by then text is already truncated, so
a secret cut at the bound could leak its first part. It would also have to know every event shape.

**D2. The environment snapshot is the unit's harness environment.** In `normalize`, the backend
calls `env_secrets(self.env_for(trajectory.unit, unit_root))`, the same mapping it passed to the
harness subprocess. On OpenCode that is `os.environ` plus the suite's `env` and the isolation
overrides. On Claude Code it is the filtered inherited environment plus the suite's `env` plus its
overrides. `env_secrets` already skips allow-listed names, short values and plain paths, so the
unit's own directories are not masked. Alternative: `os.environ` of the `wikiskill eval` process.
Rejected, because it would miss the suite's `env`, the likeliest place for a task credential.

**D3. The redaction switch comes from the collection.** `cli/eval.py` passes
`redact=coll.redact if coll else True` to both backends, next to `output_limit_bytes`, and the
backends hand it to the `Scrubber`. A run without a collection redacts, the safe default.

**D4. Notes are redacted at write time.** `write_note` takes the collection's `redact` and
`env_secrets(os.environ)` of the process running `wikiskill note`. It runs the text through
`redact()`, and sets `redactions` on the event when something matched. It does not bound the text:
notes have no size limit today, and adding one is out of scope.

**D5. The three live fields.** In `hooks.py` and `mapper.ts`, the delegation `description`, the
activation `input_summary` and the tool-call `error` are redacted, and their counts merged into the
event's `redactions`. Redaction happens before the existing 500-character cut, consistent with D1.
The eval normalisers get the same treatment through the `Scrubber`. New parity cases go in
`tests/fixtures/parity/redact.json`, or a sibling `events.json` if the cases need event shapes.
Both `test_parity.py` and the bun parity test read them.

**D6. Docs.** In `docs/data.md`, "Things to be aware of" now says that `raw/` is redacted throughout
and that unit transcripts are not. The `redactions` row in the event table needs no change.

## Risks / Trade-offs

- [Over-redaction from the unit environment: a long, non-secret variable such as a model name is
  masked wherever it appears] → This is the same behaviour as live logging, which takes the whole
  process environment. `env_secrets`' allow list and minimum length already apply. The masked event
  still records the kind, and a collection can set `redact = false`.
- [Eval normalising gets slower: running the regex table over every text] → It is the same cost per
  event as live logging. The texts are bounded at 16 KB after redaction, but redaction runs on the
  full text. A pathological multi-megabyte output could cost noticeable time. Since live logging
  does the same, accept it, and note it in the tests' timing if seen.
- [A secret in an eval transcript remains on disk] → This is the user's decision. `docs/data.md`
  states it, and the transcripts are never pooled (only `run.json` and `results.jsonl` are shared).
- [Python and TypeScript drift on the three new fields] → Shared parity fixtures, run by
  `bin/check` on both sides.
- [Old logs keep unredacted eval events] → This is documented. Deleting the old `raw/` day
  directories is the remedy.

## Open Questions

- Should `wikiskill log validate` gain a warning when an `origin: eval` event lists no `redactions`
  and holds a secret-shaped string? That would detect old unredacted logs. It can be added later
  without changing this design.
