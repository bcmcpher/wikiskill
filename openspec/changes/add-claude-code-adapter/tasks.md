## 0. Minimal working core

The plugin build (1.1–1.2) and the hooks logger for Skill/Agent activations and `Stop` (2.1–2.3), so
real Claude Code development sessions start producing raw logs. Deferred: the eval backend (4.x), until
the OpenCode backend's report format has settled, and open-model preflight (5.x).

## 1. Plugin build

- [x] 1.1 `wikiskill build --harness claude-code`: `.claude-plugin/plugin.json`, skills, commands,
  agents with a `tools:` mapping, and aliases from `[aliases.claude-code]`.
- [x] 1.2 `hooks/hooks.json` with absolute `wikiskill hook <event>` commands; `wikiskill install --harness
  claude-code`.
- [x] 1.3 Confirm the hook command resolves without a login shell: `env -i PATH=/usr/bin:/bin bash -c
  '<abs path>/wikiskill --version'`.

## 2. Hooks logger

- [x] 2.1 `src/wikiskill/hooks.py`: pure stdin-JSON → raw-event mappers for `PostToolUse`,
  `UserPromptSubmit`, `SubagentStop`, and `Stop`.
- [x] 2.2 Per-session state file for watch-list gating, buffering, and follow-up windows.
- [x] 2.3 Fail-open: always exit 0, no stdout; errors to the logger error log.
- [x] 2.4 Token usage and model identity parsed from the transcript at `Stop`.

## 3. Corrections on Claude Code

- [x] 3.1 `user_turn` and `repeat_activation` from `UserPromptSubmit` and `PostToolUse`.
- [ ] 3.2 `produced_files` on Write/Edit; reuse `wikiskill corrections scan`. Waits for
  `add-correction-capture` 2.x, which is deferred there.
- [x] 3.3 `/wikiskill-note` built as a Claude Code command.

## Implementation notes (2026-10-05)

Parts 1–3 are built, except 3.2. The hook shapes come from Claude Code 2.1.289, captured with a
throwaway plugin into `tests/fixtures/claude-code/` (about $0.08 of Haiku). A further live check
(about $0.06) ran the built plugin through `claude --plugin-dir`. Its hooks logged a skill
activation, a follow-up `user_turn` (high) on resume, and a `wikiskill note` run from the same
directory, all with 0 schema errors.

What the capture showed, and what the logger does about it:

- A subagent's tool calls carry the parent's `session_id` plus `agent_id`/`agent_type`, so a
  subagent is a child session named by its `agent_id`. A background agent's `PostToolUse` arrives
  before its own work, with `agentId` in the response, so the child's calls are attributed to it.
- Names are plugin-qualified (`govern:preregister`), and are matched as `govern/preregister`. A flat
  build (one plugin, bare component names) falls back to the bare name, but only against patterns
  without a plugin, so another plugin's same-named skill is never claimed.
- A slash command reaches hooks only as a `UserPromptSubmit` starting with `/`. It can activate a
  watched command, and it is never a user turn.
- A background agent's completion is a `UserPromptSubmit` holding `<task-notification>`. It is
  ignored.
- The model, version and token usage are only in the transcript. Assistant messages repeat once per
  content block, so usage is counted once per message id.
- Each hook is a process, so state (the gate, the buffer, the window) is a per-session JSON file
  under `$XDG_STATE_HOME/wikiskill/claude-code/sessions/`, updated under `flock`.
- Redaction is ported to Python (`redact.py`), and tested against the plugin's own cases.
- `install --harness claude-code` writes a one-plugin local marketplace. Enable it with
  `claude plugin marketplace add <dir>` and `claude plugin install wikiskill@wikiskill-local`.
- A hook call takes about 0.17 s, and always exits 0 with no stdout.

## 4. Eval backend

- [ ] 4.1 `src/wikiskill/runner/claude.py`: temp `CLAUDE_CONFIG_DIR`, fixture workdir, isolation flags,
  and a budget cap.
- [ ] 4.2 Conditions: OFF, ROUTED (`--plugin-dir`), and INJECTED (`--append-system-prompt` with the
  `Skill` tool disallowed).
- [ ] 4.3 Stream-json normaliser with Skill/Agent detection and subagent linkage; outcome classes shared
  with OpenCode.
- [ ] 4.4 A `PreToolUse` guard hook in the run config mirroring the suite's deny rules.
- [ ] 4.5 Harness axis in `report.json` and `report.md`; same-model cross-harness table.

## 5. Open models in Claude Code

- [ ] 5.1 Preflight for Anthropic-compatible endpoints: a Messages request with a tool returns
  `tool_use`, and context is at least 16k.
- [ ] 5.2 Check whether the installed Ollama serves the Messages API; otherwise document a LiteLLM proxy
  setup in `docs/design/architecture.md`.

## 6. Verify

- [x] 6.1 `uv run pytest tests/test_hooks.py`: recorded hook payloads map to schema-valid events,
  identical to OpenCode fixtures except for harness, model, and session fields.
- [ ] 6.2 `uv run pytest tests/test_runner_claude.py`: normaliser over recorded stream-json, including a
  subagent.
- [x] 6.3 Manual check:
  1. Start `claude --plugin-dir dist/claude-code`.
  2. Trigger a watched skill.
  3. `wikiskill log tail` shows `component_activated` with `harness: claude-code`.
- [ ] 6.4 Cross-harness smoke test: a 3-task suite on one open model under both backends, or the
  preflight failure recorded per harness.
- [x] 6.5 `openspec validate add-claude-code-adapter --strict --no-interactive`.
