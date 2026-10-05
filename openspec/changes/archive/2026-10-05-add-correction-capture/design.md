## Context

`add-trace-logging` records what a component did. It does not record what happened next. The user's
reaction is the strongest evidence a skill fell short, and it shows up in three places: the next
messages in the same session, later edits to files the agent produced, and the user re-running the
same component. OpenCode's plugin API exposes user messages through `chat.message` and bus events, and
file writes through the `edit`/`write`/`patch` tool calls the logger already sees.

## Goals / Non-Goals

**Goals:**
- Capture correction signals from ordinary use with no extra user effort.
- Give the user one explicit, unambiguous way to flag a correction.
- Attribute every signal to a component with a stated confidence.

**Non-Goals:**
- **Classifying** signals as correction, rework, approval, or unrelated — that is the maintainer's job
  (`add-experience-wiki`), where a model can read context.
- **Watching arbitrary files**: only files a watched component wrote are checked.
- **Claude Code capture** — `add-claude-code-adapter`.

## Decisions

**Follow-up window.** After a component activates, subsequent user turns in the same session are
recorded as `user_turn` until either three user turns have passed (configurable) or a different
watched component activates. Each records redacted text, turns since activation, and seconds since
the component's last tool call.

**Attribution confidence.** `explicit` for notes naming a component; `high` for the first follow-up
turn; `medium` for turns two and three; `low` for output edits detected in a later session.

**Output edits via recorded hashes.** When a watched component writes a file, the logger records its
path and content hash in a `produced_files` payload on the tool-call event. `wikiskill corrections
scan` — run at `session_start` by the plugin in the background and on demand — compares current
content with the last recorded hash. A change not explained by a later logged tool call becomes an
`output_edit` with a unified diff capped at 8 KB. Own hashes rather than OpenCode's `snapshot/`
keep this harness-neutral; a git diff is used when the file is tracked.

**Repeat activation.** Re-activation of the same component within the window writes
`repeat_activation`, a common signal of "that didn't work, try again".

**Explicit notes.** `/wikiskill-note` expands to `wikiskill note --session <id> [--component X] "<text>"`.
The plugin writes the current session id to `raw/.sessions/<project-hash>` so the command can find it.
Without `--component`, the note attaches to the last activated component.

## Risks / Trade-offs

- [False positives: the user moves on to unrelated work] → low confidence past turn one; the maintainer
  filters; the window closes on the next component activation.
- [Output-edit scan cost on large projects] → only files in `produced_files`; bounded count per scan.
- [User text is sensitive] → same local-only storage and redaction as the raw log.
- [Session id lookup races with concurrent sessions in one project] → note command accepts
  `--session` explicitly and warns when more than one session is active.

## Open Questions

- Should a session abandoned right after a component ran (no follow-up, no end) count as a signal?
- Should output-edit scanning run on a timer, or is session start plus on-demand enough?
