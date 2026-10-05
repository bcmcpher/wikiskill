## 0. Minimal working core

Follow-up turns (1.1–1.2) and explicit notes (3.1–3.3) — both are cheap and give the maintainer
something to read. Output-edit scanning (2.x) was deferred until follow-ups and notes had been used
on real sessions, then built ahead of that on 2026-10-05 so the Claude Code adapter could reuse it.

## 1. Follow-up turns and repeats

- [x] 1.1 Bump the raw schema minor version; add `user_turn`, `output_edit`, `note`, and
  `repeat_activation` with their payloads and the `confidence` field.
- [x] 1.2 Plugin: record user turns inside the follow-up window with attribution and confidence.
- [x] 1.3 Plugin: emit `repeat_activation` on re-activation within the window.

## 2. Output edits

- [x] 2.1 Plugin: add `produced_files` (path, hash) to write/edit/patch tool-call events.
- [x] 2.2 `src/wikiskill/corrections.py` + `wikiskill corrections scan`: compare hashes, exclude changes
  explained by later logged tool calls, and emit `output_edit` with a capped diff (git diff when
  tracked).
- [x] 2.3 Plugin triggers a background scan on `session_start`; scan failures are fail-open.

## 3. Explicit notes

- [x] 3.1 Plugin writes the active session id to `raw/.sessions/<project-hash>`.
- [x] 3.2 `wikiskill note [--session] [--component] <text>` writes a `note` event with confidence
  `explicit`.
- [x] 3.3 `harness/source/commands/wikiskill-note.md`; build it for OpenCode.

## Implementation notes (2026-10-05)

1.x and 3.x are built and unit-tested; nothing has run in a live OpenCode yet (4.3).

- The schema stays at major version 1. 1.1 is recorded in its `$comment`, and adds a top-level
  `confidence` that correction signals must carry and no other event may.
- User turns come from the `chat.message` hook's text parts, only for a live root session that is
  already logging. A subagent's prompt and an evaluation's task prompt are not user turns.
- A slash command's expansion is not a user turn and does not count against the window:
  `command.execute.before` marks the session and the next `chat.message` within 10 s is skipped.
  That this ordering holds is an assumption to confirm in 4.3.
- A repeat needs at least one user turn between the two activations; a model loading a skill twice
  in one answer is not anyone re-running it.
- The window lives on the root session. A component activated only inside a subagent opens it, but
  if the root session itself is not logging, its user turns are not recorded.
- `raw/.sessions/<sha256(directory)[:16]>.json` lists the logged root sessions active in a project
  for the past day. `wikiskill note` warns when more than one was active in the last hour.
- `[logging] follow_up_turns` (default 3) sets the window per collection.

Output edits (2.x), also built and unit-tested only:

- `produced_files` (path, hash; null when deleted) is on every successful write, edit, multiedit and
  patch call in a logged session, attributed or not, so a later write by anyone explains a change.
  Claude Code records it for Write, Edit, MultiEdit and NotebookEdit.
- The scan's last known content for a file is the latest of a logged write and an earlier
  `output_edit`, so each change is recorded once. The edit goes to the most recent component that
  wrote the file, into that session's log, at confidence `low`.
- "Explained by a later logged tool call" also covers a non-read-only call (a shell command, most
  often) whose input names the file: what it did cannot be known, so the change is not the user's.
- The `before` side of a diff is content a write call logged in full, or git's HEAD or index copy
  when that matches the recorded hash. An edit with neither is recorded with `diff: null`. Diffs are
  redacted and cut to 8 KB.
- Only logs written in the last 30 days are read, and at most 500 files compared. Eval events are
  ignored. A lock in `raw/.sessions/` stops two scans of one collection overlapping.
- The plugin learns how to run `wikiskill` from a new `cli` argv in `runtime.json`, and starts
  `wikiskill corrections scan --quiet` detached when a live root session is created, at most every
  10 minutes per OpenCode process. The Claude Code hooks do the same at `SessionStart`. `--quiet`
  prints nothing, exits 0, and writes failures to the logger error log.
- Open: whether the scan should also run on a timer (design.md) — session start plus on demand for
  now. Re-publish `runtime.json` (`wikiskill collection check --sync`) so the plugin sees `cli`.

## 4. Verify

- [x] 4.1 `uv run pytest tests/test_corrections.py`: fixtures for window closing, repeat detection,
  and edit-explained-by-tool-call exclusion. Window closing and repeat detection are plugin-side and
  tested in `logger.test.ts`; `test_corrections.py` covers the schema, the manifest setting and
  `wikiskill note`, and the scan: edits found once, explained by a later write or a shell command
  naming the file, unattributed files ignored, git and logged-content diffs.
- [x] 4.2 `bun test harness/opencode/plugin`: user-turn attribution cases.
- [x] 4.3 Manual check in OpenCode:
  1. Run a watched skill, then reply with a correction, then run `/wikiskill-note`.
  2. `wikiskill log tail <collection>` should show `user_turn` (high) and `note` (explicit) on that
     component.

  Done 2026-10-05 on OpenCode 1.18.34 with gemma4 via Ollama, `wikiskill-self` installed at project
  scope in a scratch repo. Three turns went to one `opencode serve`, through `opencode run --attach`.
  Session `ses_ef2ff779cffeY0rOzsY1rJnyBq` logged `component_activated`, then `user_turn` (high) for
  the correction, then `note` (explicit), all on `skill:wikiskill-trace`. The
  `/wikiskill-note` expansion logged no `user_turn`, so `command.execute.before` does precede
  `chat.message`, as assumed. Separate `opencode run -s <session>` processes instead do not work: each
  is a new plugin instance that does not know the session was logging, so the correction turn was
  not recorded (session `ses_ef30082d4ffepl3TJtzqxAmFWT`). Only the note was recorded, because
  `wikiskill note` reads the session list on disk. An interactive session is one process, so that
  limitation does not arise there.
- [x] 4.4 `openspec validate add-correction-capture --strict --no-interactive`.
