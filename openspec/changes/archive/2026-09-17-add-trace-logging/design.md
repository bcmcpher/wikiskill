## Context

WikiSkill (arXiv 2608.27454) keeps an immutable raw layer of execution traces that its wiki maintainer
and skill proposer read. The paper produces those traces from benchmark runs. wikiskill must also
produce them from ordinary use inside a harness, across more than one harness and many models, so
the record has to be harness-neutral and carry model identity on every event.

OpenCode exposes what we need through its plugin API: `event` receives every bus event, and
`tool.execute.after` sees completed tool calls. Skills load through a `skill` tool
(`state.input.name`, `metadata.dir`), and subagents run through a `task` tool whose metadata carries
the child `sessionId`. Step parts carry token counts and cost.

## Goals / Non-Goals

**Goals:**
- One raw event schema that OpenCode (now) and Claude Code (`add-claude-code-adapter`) both write.
- Passive, opt-in capture limited to sessions that touch watched components.
- Every activation tied to the exact component version that ran.
- Zero effect on the user's session when logging fails.

**Non-Goals:**
- **Correction signals** (follow-ups, output edits, notes) — `add-correction-capture`.
- **Any model call or classification** during logging.
- **Backfilling** historical sessions from `opencode.db` — see Open Questions.
- **Claude Code** hooks and plugin build — `add-claude-code-adapter`.

## Decisions

**Event envelope.** Every line is one JSON object:
`schema_version`, `event_id` (ULID), `ts`, `origin` (`live` | `eval`), `harness` (`opencode` |
`claude-code`), `harness_version`, `provider`, `model`, `collection`, `session_id`,
`root_session_id`, `parent_session_id`, `component` (`{kind: skill|agent|command, name, source_hash}`
or null), `type`, `payload`, `redactions`. Types in this change: `session_start`,
`component_activated`, `delegation`, `tool_call`, `assistant_turn`, `step_usage`, `error`,
`session_end`. `add-correction-capture` adds `user_turn`, `output_edit`, `note`, `repeat_activation`.

**One file per root session.** `raw/<YYYY-MM-DD>/<root_session_id>.jsonl`, append-only. Child
sessions write into their root's file so a delegation chain reads as one trajectory.

**Watch-list gating with a buffer.** The plugin keeps a per-session ring buffer (default 200 events).
When a watched skill, agent or command activates, the buffer flushes and the session is logged from
then on. Sessions that never touch a watched component write nothing. A child session of a logged
session is always logged.

**Component detection (OpenCode).** `skill` tool → skill name from input; `task` tool →
`subagent_type`; `command.execute.before` → command name. A `read` of a watched component's
`SKILL.md` path also counts as activation, because models sometimes read skills directly.

**Version identity.** `source_hash` is the SHA-256 of the component's main file at activation time,
read from `metadata.dir` or the resolved agent path. Refinement (`add-skill-refinement`) compares before/after on it.

**Redaction and bounds.** Environment values and secret-shaped strings are replaced with
`[REDACTED:<kind>]` and listed in `redactions`. Tool outputs above 16 KB are truncated; the record
keeps the original length and a hash.

**Plugin writes directly.** The plugin appends with Bun file APIs — no Python process per event. The
Python side validates and reads. The event→record mapping is a pure function in its own module so it
can be contract-tested against recorded OpenCode events.

**Fail-open.** Every hook body is wrapped; failures go to `raw/_logger-errors.log` when writable and
are otherwise dropped. Hooks never throw.

**Manifest.** `${XDG_CONFIG_HOME:-~/.config}/wikiskill/collections/<name>.toml`:

```toml
name = "data-science-harness"
sources = [{ path = "~/Projects/claude/data-science-harness/plugins", layout = "claude-plugin" }]
watch = { skills = ["govern/preregister", "analyze/*"], agents = ["datalad-doer"] }

[roles.judge]
base_url = "http://gpu-box:8000/v1"
model = "qwen3-32b"

[aliases.opencode]
haiku = "ollama/qwen3:30b-a3b"
sonnet = "vllm/qwen3-32b"
```

**Single source.** `harness/source/{skills,agents,commands}/`. Agents use neutral frontmatter:
`description`, `role_model` (an alias), and `capabilities` (`read`, `search`, `bash`, `edit`, `web`).
The OpenCode build emits `mode: subagent` plus a `permission` block that denies everything not listed,
and resolves `role_model` through the alias table. Build output goes to `dist/` (git-ignored).

**CLI install.** `uv tool install .` puts `wikiskill` on PATH. Skills and commands call it by name;
`wikiskill install` prints the resolved path so hooks (`add-claude-code-adapter`) can use it explicitly.

## Risks / Trade-offs

- [OpenCode plugin API or event shapes drift between versions] → declare a floor of `^1.18.31` for
  `@opencode-ai/plugin` rather than an exact pin, because the harness is updated regularly;
  contract tests over payloads recorded from a real session; record `harness_version` on every
  event, so a drift is visible in the log itself rather than only at install time.
- [Logging private work] → opt-in watch list, local-only storage, redaction on by default.
- [Missed activations when a model reads skill text some other way] → path-based `read` detection;
  `wikiskill log stats` reports sessions with watched-path reads but no activation.
- [Storage growth] → per-collection retention setting; `log stats` reports size.

## Open Questions

- Should `wikiskill log backfill` import past sessions via `opencode export`, tagged `origin: backfill`?
- Is a 200-event pre-activation buffer the right default for long sessions?
