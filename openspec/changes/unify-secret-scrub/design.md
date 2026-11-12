## Context

`src/wikiskill/redact.py` has two families of scrubber.

- **Logger family** — `redact`, `redact_value`. A port of the OpenCode plugin's `redact.ts`, held
  to it by `tests/test_parity.py`. It replaces environment values in raw form only, then runs the
  secret-shaped patterns, counts what it found, walks values but not dict keys, and cuts nesting
  past depth 8 to `[TRUNCATED:depth]`.
- **Withheld family** — `withheld_forms`, `hide`, `hide_value`, `holds_withheld`. Added by
  `add-verifier-secrets`. It replaces each declared value in raw form and in both JSON-escaped
  forms, in strings and dict keys, with `MARKER`, and runs no patterns.

Eval call sites for declared secrets today:

| Site | Scrubber | Gap |
|---|---|---|
| `runner/run.py` `_result`, `_scrub_unit`, manifest; `cli/eval.py` preflight manifest | `hide_value` | — |
| `runner/common.py` `hide_in_files` | `withheld_forms` + bytes | reads all of `node_modules` |
| `score/verify.py` output | `hide` + `redact` (patterns) | — |
| `score/verify.py` JSON result | `hide_value` + `holds_withheld` | marker false positive |
| `score/judge.py` `_hidden` (answer, workdir files) | `redact` with values | raw form only |
| `runner/run.py` `_judge` stored answer | `redact_value` | no keys; depth cut |
| `runner/common.py` `Scrubber.value` (eval events into `raw/`) | `redact_value` | no keys; raw form only |

`hide_values_in` replaces forms one after another. A shorter form can match inside a `MARKER` an
earlier form inserted, and `holds_withheld` searches text that holds markers. Declared values are at
least 8 characters with no surrounding whitespace, so `env_value` and `REDACTED` are reachable.

`Task.suite_secrets` copies `Suite.secrets` into every task at load, so `Task.withheld` is the
suite's set on every task. Backends already hold the same set as `backend.withheld`.

## Goals / Non-Goals

**Goals:**

- One function for declared secrets in eval records, used at every site in the table.
- Marker-safe replacement and leak check.
- Unit scrub cost independent of the seeded `node_modules` size.
- The suite's secret set held in one place.

**Non-Goals:**

- Live-session logging. `hooks.py` and the OpenCode plugin keep the logger family, which must stay
  equal to `redact.ts`.
- Adding pattern redaction to `results.jsonl` or `run.json` outside verifier output and the judge
  exchange.
- Rewriting earlier runs.

## Decisions

### One entry point: `redact.withhold(obj, values, *, patterns=False)`

It walks strings and dict keys as `hide_value` does, replaces every form of every value, then, when
`patterns` is set, runs the `PATTERNS` pass on each string. A string input returns a string. It
does not count and does not cut depth: eval records keep their structure.

`hide`, `hide_value` and the judge's `_hidden` become thin calls to it or are removed. Each site
keeps its current pattern setting: on for verifier output and the judge exchange, off elsewhere.

Alternative: extend `redact_value` with keys and JSON forms. Rejected: it is held to `redact.ts`
parity, and changing it changes live logs too.

### Single-pass replacement

Build one alternation of the escaped forms, longest first, and replace with `re.sub` in one pass.
Inserted markers are never searched again. `holds_withheld` splits the JSON text on `MARKER` and
checks each piece, so a marker's own text never counts as a leak. Splitting rather than deleting
markers avoids joining two neighbours into a false match.

The bytes path in `hide_in_files` (non-UTF-8 files) gets the same single-pass treatment with a bytes
pattern.

### Eval events keep the logger scrubber, then withhold

`common.Scrubber.value` runs `redact_value` as now, so counts and parity hold, then `withhold` with
the declared values only, to reach keys and escaped forms. Environment values found by
`env_secrets` stay raw-form only, as in live logs.

### Unit scrub skips unchanged seeded files

`_harvest_seed` already scrubs the seed before it is renamed into place, and `_apply_seed` copies it
with `copy2`, keeping size and mtime. `hide_in_files` gains an optional `unchanged` predicate. The
OpenCode backend passes one that, for a file under a `SEED_PATHS` entry, compares size and
`st_mtime_ns` to the same path in the seed and returns true on a match. A match is skipped
unread. Any other file, including a seeded file the session rewrote, is scanned as today.

Alternative: skip every `node_modules` directory. Rejected as the default: a session runs as the
user and can write into its own config directory, and the spec promises no file under the unit
holds the value. Recorded as an open decision.

Claude Code units have no seed and are unchanged.

### Remove `Task.suite_secrets`

`Task.withheld` and `Task.withheld_values` go. Call sites take the suite's set explicitly:

- `common.without_secrets(env, task)` becomes `without_names(env, backend.withheld)` in the
  backends, which `run.py` already fills from `suite.secrets`.
- `run.py` (`_scrub_unit`, `_result`, `_judge`) uses `host_values(run.suite.secrets)`.
- `score/verify.py` takes the suite's names as a parameter for `others` and `hide`.
- `suite.env_problems` takes the suite's set as a parameter.

This is a mechanical change with one safety property: no site may end up with a smaller set. Each
replaced site gets a test that a secret declared only on another task is still withheld.

## Risks / Trade-offs

- [Risk] A call site moved to `withhold` loses a pattern pass it had → Mitigation: the table above
  is the checklist; a test per site prints an `sk-…` shaped string and asserts the expected result.
- [Risk] The judge's stored answer is no longer depth-cut, so a deeply nested answer is stored
  whole → Mitigation: the judge's answer is parsed to a fixed shape before storage; a test confirms
  the stored size is bounded by the existing caps.
- [Risk] A size-and-mtime match on a file the session rewrote in place with the same size within
  the same nanosecond → Mitigation: negligible; a session that does so also had to restore the
  mtime. Noted in the docstring.
- [Risk] Removing `Task.suite_secrets` misses a site and withholds less → Mitigation: the existing
  "another task's secret is withheld too" scenarios run against each backend; a grep for `.withheld`
  on a task must return nothing.
- [Risk] Single-pass regex on very many forms is slow → Mitigation: a suite declares a handful of
  secrets, three forms each; compile once per call site, not per string.

## Known limit, not fixed

Two declared values used as keys of one dict both become `MARKER`, so one entry is lost. A fix
would number the markers in keys, which changes the stored marker format. Left as it is and
documented in `docs/data.md`.

## Migration Plan

No data migration. Earlier runs are not rewritten. A run's records may now show a marker in a dict
key or in escaped JSON where an earlier run's did not; rates are unaffected.

## Open Questions

- **Seed skip rule.** Recommended: skip a seeded file only when its size and mtime match the seed.
  Alternative: skip `config/opencode/node_modules` outright, cheaper and simpler, at the cost of the
  spec's every-file guarantee. Needs the user's call before task 3.
- **Scope of `Task.suite_secrets` removal.** It is a separable refactor with no behaviour change.
  Recommended: keep it as the last task group here, since `add-run-archive` will also need the
  suite's set. It can split into its own change if the diff is too large to review with the rest.
- **`add-run-archive`.** Its pack-time scan matches the raw log's patterns over text files. Once this
  change lands, that scan should call `withhold(..., patterns=True)` on each file's text and
  compare. That change's design must be updated when it is applied.
