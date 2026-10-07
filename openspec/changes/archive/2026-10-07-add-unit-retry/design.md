## Context

`run_suite` runs every unit once and appends one line per unit to `results.jsonl`. Each backend
turns a harness failure into an `infra_error` trajectory, and every reader leaves `infra_error`
and `skipped` out of its denominators. The DSH sweep (`pilots/dsh-sweep/sweep.sh`) records a run
only when no more than `MAX_NOT_RUN` (0) units did not run. Otherwise it leaves the run unrecorded
and runs the whole suite again on the next invocation.

`infra_error` covers several different things:

| reason | example | transient? |
|---|---|---|
| harness exited without a session | `opencode produced no session (exit -5)` (Bun crash) | yes |
| session export failed | truncated or unparseable export | yes |
| harness could not be launched | `OSError` from `subprocess` | yes |
| workdir could not be prepared | `setup` failed | no: the suite or environment is broken |
| unit timed out | gemma4:31b at 600 s | no: a retry costs another 600 s and usually times out again |
| agent mismatch | the pinned doer ran on another model | no: configuration |
| verifier could not run | missing program in a verifier command | no: environment |

## Goals / Non-Goals

**Goals:**
- A unit lost to a transient harness failure is rerun without rerunning the others.
- Every attempt stays on the record; nothing is overwritten without a copy.
- A filled run is scored exactly like a run that never needed filling.

**Non-Goals:**
- Retrying a scored unit. Rerunning failures until they pass is selection, and would bias every
  pass rate upward. Only units that produced no score are repaired.
- Retrying timeouts. A raised `timeout_s` is a new suite, as now.
- Resuming a run killed partway through. `run.json` is written only when a run ends, so a killed
  run has no record of its settings to fill from, and `--fill` refuses it. It is rerun in full, as
  now.

## Decisions

### Transient is a property the backend sets, not a pattern the runner matches

Each backend already knows which branch produced the `infra_error`. OpenCode sets
`trajectory.transient = True` on three branches (no session, export failure, launch `OSError`), and
Claude Code on two (no session, launch `OSError`); it has no export step. The runner retries on that flag alone. Matching error strings in `run.py` was rejected:
the strings differ between OpenCode and Claude Code, and they would drift.

### Retry in place, with the earlier attempt kept

When a transient `infra_error` is retried, the unit directory is renamed to `<slug>.attempt-<n>`
first, so the crashed attempt's files stay for reading. The rerun gets a fresh unit directory and
workdir from `prepare`, as the first attempt did. Only the final attempt's result goes into
`results.jsonl`. It carries:

```json
"attempts": 2,
"retried": [{"outcome": "infra_error", "error": "opencode produced no session (exit -5). https://bun.report/...",
             "duration_ms": 41200, "kept": "units/auto-backend-structured__ollama_ministral-3-3b__off__r0.attempt-1"}]
```

`attempts` is 1 and `retried` is absent for a unit that ran once, so existing runs need no
migration. Raw events are written only for the final attempt; a crashed attempt has none.

`--retries` defaults to 1. A second crash on the same unit is more likely the unit than chance, and
should surface as `infra_error`.

### `--fill` replaces lines; it does not append them

Every reader of `results.jsonl` assumes one line per unit. Appending a second line for a filled unit
would need a "last line wins" rule in nine readers (`report`, `leaderboard`, `compare`, `findings`,
`version_board`, `diff`, `graph`, `review`, `gate`). Instead, `--fill` writes the new results to a
temporary file and replaces `results.jsonl` atomically, keeping one line per unit in the original
order. The lines it replaces are appended to `results.superseded.jsonl` in the run directory, with
the fill's timestamp.

`run.json` gains:

```json
"fills": [{"at": "2026-10-07T18:40:12Z", "units": ["auto-backend-structured__ollama_ministral-3-3b__off__r0"],
           "harness_version": "1.18.34", "wikiskill_version": "0.1.0"}]
```

Each entry also carries the fill's `outcomes` `before` and `after`, its `retries`, its own
`preflight` and its `duration_s`. The original `duration_s` is kept; `outcomes` and
`events_written` are updated to count the run as it now stands.

### `--fill` checks that the run can still be continued

It loads `run.json` and refuses, saying which check failed and naming no fallback, when:
- the suite file's hash differs from `suite_hash`;
- the installed harness version differs from `harness_version`;
- a component version read from the collection differs from the recorded one; or
- the run is a `--proposal` run and the proposal's candidate is no longer there.

Suite, models, conditions, tasks, repeats, thinking, output cap, seed cache, proposal and workers
are all taken from `run.json`; given beside `--fill`, any of them is refused. `--collection` is
required, to find the run. The base URL defaults to the one the run's preflight recorded, and a
different one is refused. The API key, executables and `--retries` come from the command line. A
fill runs preflight again for the models it needs, so a model that has since been removed is
`skipped` again rather than failing the fill. Units are filled one at a time.

A unit needs filling when its result is `infra_error` or `skipped`. A unit still unscored after a
fill keeps its new line, so a fill never makes a run look more complete than it is.

### The sweep fills, then judges completeness as before

`sweep.sh` lives only on `results/dsh-pilot`, and is not edited while a sweep runs it: bash reads a
script as it executes. The change is staged as `sweep-fill.patch` and applied after the running
sweeps end. `run_one` calls `wikiskill eval --fill "$run_id"` up to `MAX_FILLS` times while
`state finished` reports the run incomplete. It logs each fill, and stops filling when a fill is refused (exit 2). The completeness rule and
`MAX_NOT_RUN` are unchanged, so a run is recorded only when it is complete. `findings add` needs no
change: the run id is the same.

## Risks / Trade-offs

- **A filled unit ran later than its neighbours.** Ollama, the model weights or the GB10's load may
  differ. → `fills` records when, and the harness and wikiskill versions. The report states how many
  units were filled.
- **Retries hide an unstable harness.** → `attempts` and `retried` stay on every result, and the run
  report counts retried units, so a crash rate is still visible.
- **Atomic replace of `results.jsonl` while something reads it.** → Write, `fsync`, then `rename`;
  readers see the old file or the new one, never a mix.
- **Retrying doubles the cost of a crash-prone model.** → One retry by default, transient errors
  only, and `--retries 0` restores today's behaviour.
