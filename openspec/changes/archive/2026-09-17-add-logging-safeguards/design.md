## Context

See proposal.md — Why. The three behaviours exist in code as of `8baedeb`; this design records the
decisions behind them, because each has a non-obvious rationale that a later reader would otherwise
have to rediscover from a review.

The constraint that shapes all three: OpenCode's plugin API is the only window the logger has, and it
was not designed for logging. `tool.execute.after` receives `{tool, sessionID, callID, args}` and
`{title, output, metadata}` — no status, no timing — and it is not called at all when a tool throws.
Timing and failure exist only on OpenCode's tool *parts*, which arrive on the event bus as
`message.part.updated` with a terminal `state.status` of `completed` or `error`.

## Goals / Non-Goals

**Goals:**

- One event per tool call, whichever source describes it first.
- A memory bound that holds for a server running for days, without dropping state from a session
  that is merely slow.
- A destructive build step that cannot destroy anything the build did not create.

**Non-Goals:**

- Recording a call that is still running. Only terminal states are logged; a partial call has no
  outcome to record.
- Recovering the state of a session that was released. A session that resumes after its state was
  dropped starts buffering again and re-activates on its next watched component.
- Reconstructing failed calls for Claude Code. Its `PostToolUse` hook reports success and failure
  directly, so its adapter satisfies the same requirement without any of this machinery.

## Decisions

**Tool outcomes come from tool parts, with the hook as a fallback writer.** Both sources claim the
call id; the first to describe a call writes it. Taking outcomes only from parts was rejected because
tool parts have never been observed in a captured session — the capture run for `add-trace-logging`
never reached a tool call — so making them the sole source would stake all tool logging on an
unverified assumption. Keeping only the hook was rejected because it cannot report a failure at all.
With both, a call is logged even if parts never arrive, and gains a real duration and error when they
do. The cost is a bounded map of call ids, which is cheaper than the alternative of correlating after
the fact.

**Staleness is measured from last activity, and logged sessions are not exempt.** Exempting them —
the original behaviour — meant the sessions holding the most state, including their buffers, were
precisely the ones never released, so a long-lived `opencode serve` grew without bound. Measuring
from the session's start instead of its last activity was worse than useless: it would drop an
actively streaming session at six hours while keeping an idle one that had just been created.

**A build directory is identified by a marker file, not by its path.** The alternative — allowing a
clear only under the default `dist/` — was rejected because `--out` exists precisely to build
elsewhere, so it would turn a supported flag into a trap. A marker also makes the rule legible from
the filesystem: a directory either announces that a build owns it or it does not. An empty directory
is accepted, so a first build into a fresh path needs no ceremony. The marker is excluded from what
`install` stages, so it never reaches a harness config directory.

## Risks / Trade-offs

- [A released session resumes and its earlier context is gone] → The window is hours of inactivity,
  and the events already written are untouched; only the in-memory buffer and the current component
  attribution are lost. A resumed session re-activates on its next watched component.
- [Both sources describe the same call and one is dropped] → Deduplication is by call id, which
  OpenCode assigns; the two sources carry the same input and output, so whichever wins produces an
  equivalent record. Only the duration differs, and the part-sourced one is the better of the two.
- [A build directory loses its marker and refuses to rebuild] → The error names the directory and
  says what to do. The failure mode is an inconvenient error, not data loss, which is the direction
  the trade-off should fall.
- [A user's directory happens to contain the marker] → It is a wikiskill-specific dotfile name, and
  the build writes it only into output it created.

## Open Questions

- Whether Claude Code's hooks report a tool duration, or only its start and end times, which decides
  whether `add-claude-code-adapter` derives the duration or leaves it null.
