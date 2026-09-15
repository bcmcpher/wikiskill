## 0. Minimal working core

Follow-up turns (1.1–1.2) and explicit notes (3.1–3.3) — both are cheap and give the maintainer
something to read. Deferred: output-edit scanning (2.x) until follow-ups and notes have been used on
real sessions.

## 1. Follow-up turns and repeats

- [ ] 1.1 Bump the raw schema minor version; add `user_turn`, `output_edit`, `note`, and
  `repeat_activation` with their payloads and the `confidence` field.
- [ ] 1.2 Plugin: record user turns inside the follow-up window with attribution and confidence.
- [ ] 1.3 Plugin: emit `repeat_activation` on re-activation within the window.

## 2. Output edits

- [ ] 2.1 Plugin: add `produced_files` (path, hash) to write/edit/patch tool-call events.
- [ ] 2.2 `src/wikiskill/corrections.py` + `wikiskill corrections scan`: compare hashes, exclude changes
  explained by later logged tool calls, and emit `output_edit` with a capped diff (git diff when
  tracked).
- [ ] 2.3 Plugin triggers a background scan on `session_start`; scan failures are fail-open.

## 3. Explicit notes

- [ ] 3.1 Plugin writes the active session id to `raw/.sessions/<project-hash>`.
- [ ] 3.2 `wikiskill note [--session] [--component] <text>` writes a `note` event with confidence
  `explicit`.
- [ ] 3.3 `harness/source/commands/wikiskill-note.md`; build it for OpenCode.

## 4. Verify

- [ ] 4.1 `uv run pytest tests/test_corrections.py`: fixtures for window closing, repeat detection,
  and edit-explained-by-tool-call exclusion.
- [ ] 4.2 `bun test harness/opencode/plugin`: user-turn attribution cases.
- [ ] 4.3 Manual check in OpenCode:
  1. Run a watched skill, then reply with a correction, then run `/wikiskill-note`.
  2. `wikiskill log tail <collection>` should show `user_turn` (high) and `note` (explicit) on that
     component.
- [ ] 4.4 `openspec validate add-correction-capture --strict --no-interactive`.
