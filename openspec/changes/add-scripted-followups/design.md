## Context

See proposal.md for why. Each backend runs a unit as one harness process: OpenCode as `opencode run
--format json … <prompt>` (`runner/opencode.py`), Claude Code as `claude -p --output-format
stream-json …` (`runner/claude.py`). Both read the session id back from the stream. `timeout_s` is
the subprocess timeout. `max_steps` is enforced by the guard: under Claude Code by the Python hook
(`guard.py`), which keeps its count in a file; under OpenCode by the guard plugin
(`harness/opencode/guard/wikiskill-guard.ts`), which keeps its count in process memory.

## Goals / Non-Goals

**Goals:**
- Send `followups` in the same session, with one verdict after the last turn.
- Keep a single-turn unit's behaviour, files and results unchanged.

**Non-Goals:**
- A simulated user that reacts to the model. Turns are fixed text, as the schema says.
- Per-turn verifiers or per-turn budgets.
- Follow-ups conditioned on logged corrections (the archived `add-explicit-eval` open question).

## Decisions

**One process per turn, continuing the session.** OpenCode: `opencode run -s <session_id> …
<followup>`. Claude Code: `claude -p --resume <session_id> …`. Each turn reuses the unit's
isolated directories and environment, so isolation is unchanged. Alternative: one long-lived
process fed over stdin. Rejected: neither harness's headless mode takes further turns that way, and
a turn boundary is where the runner must check budgets anyway.

**Budgets shared by subtraction.** The runner keeps a deadline for the unit and passes each turn's
subprocess the remaining time. For steps, the OpenCode guard moves to a file counter in the unit's
root (`WIKISKILL_STEP_FILE`), as the Python guard already does, so the count survives across turn
processes; both guards then enforce one budget per unit. Alternative: pass each turn the remaining
step budget computed from the stream. Rejected: the guard counts refused calls too, and the stream
count could drift from the guard's.

**Stop on the first non-`completed` turn.** A turn that times out, exhausts steps, is blocked or
errors classifies the unit as it does today, and no further turn is sent. The unit records
`turns_sent`, so the report can tell a unit cut short in turn 1 from one cut short in turn 3.

**Read back once, from the whole session.** After the last turn, the backend exports the session as
it does now. `final_text` is taken from the last assistant message, `transcript` from every turn,
and activations from the whole session, so route@1 is the first activation overall.

**Pooling marker in `run.json` options.** `options.followups = "sent"` on every run from this
version. A run without it counts as `"not sent"`. Pooling refuses a mix only when the suite declares
`followups`, so the check never blocks single-turn suites.

## Risks / Trade-offs

- [OpenCode `run -s` may re-read project config or start a new session on some versions] → a
  contract test against the recorded harness version, and preflight confirms that continuing a
  session keeps its id.
- [Each turn re-pays harness start-up time] → counted inside `timeout_s`, which is the honest
  measure; suite authors raise `timeout_s` for multi-turn tasks, and the guide says so.
- [The guard counter file moves OpenCode state onto disk] → it lives in the unit's own root, which
  is deleted with the unit's harness directories like every other unit file.

## Migration Plan

Lands after `warn-unsent-followups` is archived. New runs carry `options.followups`. Old runs of
multi-turn suites are kept apart from new ones by the pooling check; old runs of single-turn suites
pool as before. Rollback is a revert; runs made in between stay readable.
