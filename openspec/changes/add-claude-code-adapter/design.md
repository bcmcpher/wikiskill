## Context

Claude Code exposes its lifecycle through hooks configured in a plugin's `hooks/hooks.json`. Each hook
receives JSON on stdin with the session id, transcript path, and tool input/response.
- Skills load through a `Skill` tool.
- Subagents run through an `Agent` tool whose input names `subagent_type`.
- Headless runs use `claude -p --output-format stream-json`.

Two existing local tools already do parts of this:
- skill-creator's `scripts/run_eval.py` detects skill triggering from stream-json `Skill` tool_use
  events.
- The user's `my-skills` code-graph evaluation harness (`run.sh`) isolates headless runs with
  `--setting-sources project --strict-mcp-config --permission-mode dontAsk --max-budget-usd` and
  allowed/disallowed tool lists.

Open models can serve Claude Code when `ANTHROPIC_BASE_URL` points at an endpoint speaking the Anthropic
Messages API. Options are a translating proxy such as LiteLLM, or a model server with native Anthropic
compatibility. Whether the installed Ollama (0.14.3) provides the latter must be checked, not assumed.

## Goals / Non-Goals

**Goals:**
- Claude Code events land in the same raw schema, indistinguishable except for harness and model fields.
- The same suite and the same model can run under both harnesses for a direct comparison.
- No duplicated component sources and no Claude-only logic in the core.

**Non-Goals:**
- **Making Claude Code primary** — OpenCode behaviour defines the defaults.
- **Anthropic-specific features** in wikiskill's own agents (e.g. `model: opus` aliases resolve through
  the manifest like any other).
- **Cost probe parity** with Claude Code's priced transcripts — tokens and time only, unless the provider
  reports cost.

## Decisions

**Plugin build.**
- *Agents:* `wikiskill build --harness claude-code` emits `dist/claude-code/`. Agents get `tools:` from
  neutral capabilities: `read`→Read, `search`→Grep/Glob, `bash`→Bash, `edit`→Edit/Write, `web`→WebFetch.
  Model aliases resolve through `[aliases.claude-code]`.
- *Hooks:* the command is the absolute path from `wikiskill install`
  (e.g. `~/.local/bin/wikiskill hook <event>`).
- *Install:* `wikiskill install --harness claude-code` supports `--plugin-dir` use or a local
  marketplace entry.

**Hooks logger.** `wikiskill hook <event>` reads stdin JSON, maps it with a pure function to raw events,
and appends to the root session file. It always exits 0 and never writes to stdout, so it never blocks
or alters the session.

| Hook | Records |
|---|---|
| `PostToolUse`, Skill | `component_activated` |
| `PostToolUse`, Agent | `delegation` |
| `PostToolUse`, other tools | `tool_call`, with `produced_files` for Write/Edit |
| `UserPromptSubmit` | `user_turn` within the follow-up window |
| `SubagentStop` | closes the child |
| `Stop` | `session_end`, token usage parsed from the transcript |

Watch-list gating and buffering use a small per-session state file, because each hook is a separate
process. Model and provider come from the transcript's assistant messages, with `ANTHROPIC_BASE_URL`
recorded as the provider endpoint.

**Eval backend.**
- *Command:* `claude -p --output-format stream-json --verbose`, run in the fixture workdir with
  `--setting-sources project --strict-mcp-config --permission-mode dontAsk --max-budget-usd <cap>`, an
  allowed/disallowed tool list derived from the suite guard, and `--model`.
- *Isolation:* a temp `CLAUDE_CONFIG_DIR`, so user plugins, skills, and memory do not load.
- *ROUTED:* `--plugin-dir <built collection>`.
- *INJECTED:* `--append-system-prompt` with the component text, and the `Skill` tool disallowed for that
  run.
- *OFF:* no plugin dir.
- *Normalizing:* `Skill`/`Agent` tool_use detection is adapted from skill-creator's `run_eval.py`.
  Subagent events come from the stream's `parent_tool_use_id` linkage.
- *Guard:* a `PreToolUse` hook in the run's config dir denies mutating commands, matching the
  OpenCode guard's rules.

**Open models in Claude Code.** The manifest's `[providers.anthropic-compatible]` entry gives a base URL
and model names. Preflight checks that:
- a Messages API request with a tool definition returns a `tool_use` block
- the context limit is at least 16k

The pilot documents which proxy was used.

**Report axis.** `harness` becomes a first-class report dimension: task × model × harness × condition,
plus a same-model harness comparison table.

## Risks / Trade-offs

- [Hook stdin schemas change between Claude Code versions] → pure mappers with recorded fixtures;
  `harness_version` recorded.
- [Proxy translation distorts tool calling, confounding the harness comparison] → preflight per
  endpoint; the report names the proxy and version; comparisons flagged when a proxy sits in only
  one harness's path.
- [Hook latency slows sessions] → append-only writes, no model calls, no network.
- [Temp `CLAUDE_CONFIG_DIR` loses authentication for Anthropic-hosted baselines] → pass credentials
  through env only for runs targeting Anthropic models; never for open-model runs.

## Open Questions

- Does the installed Ollama serve the Anthropic Messages API well enough to skip a proxy?
- Should Anthropic-hosted models be a standing baseline row in every matrix, or opt-in?
