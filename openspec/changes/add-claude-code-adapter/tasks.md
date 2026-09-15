## 0. Minimal working core

The plugin build (1.1–1.2) and the hooks logger for Skill/Agent activations and `Stop` (2.1–2.3), so
real Claude Code development sessions start producing raw logs. Deferred: the eval backend (4.x), until
the OpenCode backend's report format has settled, and open-model preflight (5.x).

## 1. Plugin build

- [ ] 1.1 `wikiskill build --harness claude-code`: `.claude-plugin/plugin.json`, skills, commands,
  agents with a `tools:` mapping, and aliases from `[aliases.claude-code]`.
- [ ] 1.2 `hooks/hooks.json` with absolute `wikiskill hook <event>` commands; `wikiskill install --harness
  claude-code`.
- [ ] 1.3 Confirm the hook command resolves without a login shell: `env -i PATH=/usr/bin:/bin bash -c
  '<abs path>/wikiskill --version'`.

## 2. Hooks logger

- [ ] 2.1 `src/wikiskill/hooks.py`: pure stdin-JSON → raw-event mappers for `PostToolUse`,
  `UserPromptSubmit`, `SubagentStop`, and `Stop`.
- [ ] 2.2 Per-session state file for watch-list gating, buffering, and follow-up windows.
- [ ] 2.3 Fail-open: always exit 0, no stdout; errors to the logger error log.
- [ ] 2.4 Token usage and model identity parsed from the transcript at `Stop`.

## 3. Corrections on Claude Code

- [ ] 3.1 `user_turn` and `repeat_activation` from `UserPromptSubmit` and `PostToolUse`.
- [ ] 3.2 `produced_files` on Write/Edit; reuse `wikiskill corrections scan`.
- [ ] 3.3 `/wikiskill-note` built as a Claude Code command.

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

- [ ] 6.1 `uv run pytest tests/test_hooks.py`: recorded hook payloads map to schema-valid events,
  identical to OpenCode fixtures except for harness, model, and session fields.
- [ ] 6.2 `uv run pytest tests/test_runner_claude.py`: normaliser over recorded stream-json, including a
  subagent.
- [ ] 6.3 Manual check:
  1. Start `claude --plugin-dir dist/claude-code`.
  2. Trigger a watched skill.
  3. `wikiskill log tail` shows `component_activated` with `harness: claude-code`.
- [ ] 6.4 Cross-harness smoke test: a 3-task suite on one open model under both backends, or the
  preflight failure recorded per harness.
- [ ] 6.5 `openspec validate add-claude-code-adapter --strict --no-interactive`.
