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
- [x] 3.2 `produced_files` on Write/Edit; reuse `wikiskill corrections scan`. Built with
  `add-correction-capture` 2.x: Write, Edit, MultiEdit and NotebookEdit record it, and
  `SessionStart` starts the scan detached, at most every 10 minutes per session.
- [x] 3.3 `/wikiskill-note` built as a Claude Code command.

## Implementation notes (2026-10-05)

Parts 1–3 are built (3.2 later, with `add-correction-capture` 2.x). The hook shapes come from Claude Code 2.1.289, captured with a
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

Stream-json captured 2026-10-05 from Claude Code 2.1.289 against local Ollama 0.34.2 (no API key,
no cost), with a throwaway plugin of one skill (`word-count`) that delegates to one agent
(`counter`), a temp `CLAUDE_CONFIG_DIR`, `--setting-sources project --strict-mcp-config
--permission-mode dontAsk` and `--plugin-dir`. Fixtures in `tests/fixtures/claude-code/`, with all
but three `thinking_tokens` lines dropped: `stream-skill-2.1.289.jsonl` (gemma4: `Skill`, then a
text answer that never delegates) and `stream-subagent-2.1.289.jsonl` (qwen3:30b-a3b: `Skill`, two
rejected `Agent` calls, one background subagent). What the normaliser has to handle:

- The subagent tool is offered as `Task` in `init.tools` but called as `Agent` in `tool_use`.
  `subagent_type` is plugin-qualified (`capture:counter`); a bare `counter` is refused with
  `Agent type 'counter' not found`, and a call missing `description` with an
  `InputValidationError`. Both come back as `tool_result` with `is_error: true`, and neither is an
  activation.
- A `Skill` call's result is `Launching skill: capture:word-count`, and `tool_use_result` is
  `{success, commandName}`.
- The subagent's own messages carry `parent_tool_use_id` = the `Agent` call's id. Its lifecycle is
  in `system` events `task_started` (with `subagent_type`, `is_backgrounded`, `spawn_depth`),
  `task_progress`, `task_updated` and `task_notification` (`status`, `summary`, `usage`).
- The model ran that subagent in the background unasked. The first turn then ends with a `result`
  before the subagent finishes; its completion starts a second turn (a second `init`) and a second
  `result` with `origin.kind: task-notification` and `result_index: 1`, which holds the real
  answer. A unit is over at the last `result`, not the first.
- `result.subagent_stats` counts spawned, completed, failed and refused subagents by type.
- 2625 of 2657 lines were `system/thinking_tokens` progress events: skip them.
- `total_cost_usd` (0.39 here) and `modelUsage.costUSD` are invented for a model Claude Code does
  not know (`costBasis: unknown`); it also assumes `contextWindow: 200000` whatever Ollama serves.
  So `--max-budget-usd` would cut open-model runs on a fictional price: use turn and time limits
  for them, and record cost only for Anthropic-hosted models.
- Isolation gap, like OpenCode's `customize-opencode`: an empty `CLAUDE_CONFIG_DIR` still offers 18
  built-in skills (`deep-research`, `debug`, `simplify`, …), built-in agents (`general-purpose`,
  `Explore`, `Plan`, …) and three built-in plugins. OFF is not "no skills" until those are denied.

- [x] 4.1 `src/wikiskill/runner/claude.py`: temp `CLAUDE_CONFIG_DIR`, fixture workdir, isolation flags,
  and a budget cap. No cost cap: `--max-budget-usd` would act on the price Claude Code invents for
  an open model, so the unit's `timeout_s` and the guard's step budget bound it, as for OpenCode.
- [x] 4.2 Conditions: OFF, ROUTED (`--plugin-dir`), and INJECTED (`--append-system-prompt` with the
  `Skill` tool disallowed). An injected agent runs as the session's agent, `--agent <collection>:<name>`.
- [x] 4.3 Stream-json normaliser with Skill/Agent detection and subagent linkage; outcome classes shared
  with OpenCode.
- [x] 4.4 A `PreToolUse` guard hook in the run config mirroring the suite's deny rules.
- [x] 4.5 Harness axis in `report.json` and `report.md`; same-model cross-harness table. A run is one
  harness, so every report row names it (`opencode` for runs from before the field). The cross-harness
  table lives in `wikiskill leaderboard`, the one place runs combine: runs of one suite in different
  harnesses now pool as separate entrants (`model [harness]`, like thinking on and off), each cell
  carries `harness` and a `route@1` rate beside its pass rate, and a "Same model across harnesses"
  table sets each harness's pass rate and route@1 side by side per model and condition. A
  harness-version warning now fires only within one harness. Live: pooling the gemma4 toy-routing
  runs `01M46AZ1DKYBZ64FHQ13F8ZSZ7` (OpenCode) and `01M46DDDH1GZ0RA5G55G7X08P3` (Claude Code) gives
  ROUTED route@1 2/2 under OpenCode and 1/2 under Claude Code, intervals overlapping.

How 4.1–4.4 were built, and what live runs on 2026-10-05 changed:

- `wikiskill eval --harness claude-code`, with `--claude` for the executable and `--base-url` for an
  Anthropic-compatible endpoint (Ollama's native root; a trailing `/v1` is dropped).
- Isolation is a `settings.json` in the unit's own `CLAUDE_CONFIG_DIR`, read with `--setting-sources
  user`: `disableBundledSkills`, `skillOverrides` off for `design` and `doctor`, the three
  `cc-plugin-*@builtin` plugins off in `enabledPlugins`, an allow list of tools (`-p` cannot ask),
  `WebFetch`/`WebSearch` denied, and the guard hook. With those, OFF was offered no skill and no
  plugin, and ROUTED only the collection's. Every unit checks its own `init`: anything else offered
  makes it `infra_error`. Inherited `CLAUDE_CODE_*` and `ANTHROPIC_*` variables are dropped, and an
  open-model run never carries `ANTHROPIC_API_KEY`. Every model Claude Code would choose itself
  (`ANTHROPIC_DEFAULT_*_MODEL`, `CLAUDE_CODE_SUBAGENT_MODEL`) is the one under test.
- `skillOverrides` does not reach a plugin's skill in 2.1.289: under INJECTED the skill stayed
  offered and the model loaded it. A permission rule, `Skill(<collection>:<name>)` in `deny`, refuses
  the call (`Skill execution blocked by permission rules`, recorded `blocked`), and an injected
  skill that is loaded anyway makes the unit `infra_error`.
- `--add-dir` and `--plugin-dir` are variadic and swallowed the prompt; the prompt now follows `--`.
- Subagents run in the background when the model asks; `--foreground-agents` sets
  `CLAUDE_CODE_DISABLE_BACKGROUND_TASKS`, recorded in `run.json`.
- Stream messages report usage as of their first block, so `output_tokens` is always 0 there.
  `step_usage` comes from each `result` (one per turn), and a unit's tokens from the last result's
  cumulative `modelUsage`, subagents included. Cost is never recorded.
- `system/permission_denied` events carry `message` as a string.
- The guard is `wikiskill guard`, a port of `guard.ts`: same patterns, same refusal wording, the
  step count kept in a locked file because each call is a new process. Checked live: `wc -w` under
  a `wc *` deny came back `blocked by the wikiskill evaluation guard: ...`.
- `--agent <collection>:<name>` resolves a plugin agent; an unknown one is refused before any
  session starts, which the runner reports as `infra_error`.

## 5. Open models in Claude Code

- [x] 5.1 Preflight for Anthropic-compatible endpoints: a Messages request with a tool returns
  `tool_use`, and context is at least 16k. `preflight.messages_check`; an Anthropic-hosted model
  instead needs `ANTHROPIC_API_KEY`, since the unit's config directory holds no login.
- [x] 5.2 Check whether the installed Ollama serves the Messages API; otherwise document a LiteLLM proxy
  setup in `docs/design/architecture.md`. Ollama 0.34.2 does, at `ANTHROPIC_BASE_URL=
  http://localhost:11434` with any `ANTHROPIC_AUTH_TOKEN`: a direct `/v1/messages` request with a
  tool returned `thinking` and `tool_use` blocks, and Claude Code 2.1.289 drove gemma4 and
  qwen3:30b-a3b through `Skill` and `Agent` calls (see 4.). No proxy is needed. Claude Code warns
  `unrecognized_model` on stderr and carries on.

## 6. Verify

- [x] 6.1 `uv run pytest tests/test_hooks.py`: recorded hook payloads map to schema-valid events,
  identical to OpenCode fixtures except for harness, model, and session fields.
- [x] 6.2 `uv run pytest tests/test_runner_claude.py`: normaliser over recorded stream-json, including a
  subagent. Also drives `execute` through a stand-in `claude` that replays a capture, so the
  command line, environment and working directory the harness sees are tested, not only the
  parser; and `tests/test_guard.py` runs `wikiskill guard` as the hook does.
- [x] 6.3 Manual check:
  1. Start `claude --plugin-dir dist/claude-code`.
  2. Trigger a watched skill.
  3. `wikiskill log tail` shows `component_activated` with `harness: claude-code`.
- [x] 6.4 Cross-harness smoke test: a 3-task suite on one open model under both backends, or the
  preflight failure recorded per harness. toy-routing on gemma4 (GB10, Ollama 0.34.2), 2026-10-05:
  OpenCode 1.18.34 OFF/ROUTED `01M46AZ1DKYBZ64FHQ13F8ZSZ7`; Claude Code 2.1.289 OFF/ROUTED/INJECTED
  `01M46DDDH1GZ0RA5G55G7X08P3` (8 completed, 0 infrastructure errors, 0 schema errors) and INJECTED
  again after the deny fix, `01M46DV04VWFRM58C9T6STSPX0` (the denied skill recorded `blocked`).
  One repeat each, so this shows the path works, not how the harnesses compare.
- [x] 6.5 `openspec validate add-claude-code-adapter --strict --no-interactive`.
