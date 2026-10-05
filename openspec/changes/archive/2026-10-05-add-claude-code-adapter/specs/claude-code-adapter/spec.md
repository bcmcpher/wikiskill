## Purpose

Defines Claude Code as wikiskill's secondary harness: hook-based logging into the shared raw schema, a
headless stream-json evaluation backend, and running open models inside Claude Code through
Anthropic-compatible endpoints.

## ADDED Requirements

### Requirement: Claude Code sessions are logged through hooks into the shared schema

On Claude Code, logging MUST be provided by plugin hooks that call the `wikiskill` CLI by explicit path.
The hooks MUST write events to the same raw schema as OpenCode, with `harness: claude-code`.

#### Scenario: Skill activation in Claude Code

- **WHEN** a watched skill is loaded through the `Skill` tool in a Claude Code session
- **THEN** a `component_activated` event is written with `harness: claude-code`, the skill's
  `source_hash`, and the session's model

#### Scenario: Subagent delegation

- **WHEN** a logged session calls the `Agent` tool with a watched `subagent_type`
- **THEN** a `delegation` event is written and the subagent's tool calls are linked to it

### Requirement: Hooks never block or alter the session

Every wikiskill hook MUST exit with status 0, MUST NOT write to stdout, and MUST NOT make model or
network calls, whatever errors occur inside it.

#### Scenario: Corrupt state file

- **WHEN** the per-session state file cannot be parsed during a `PostToolUse` hook
- **THEN** the hook exits 0 with no stdout, and the error is recorded in the logger error log

### Requirement: Open models are preflighted for Claude Code

Before evaluating an open model under Claude Code, wikiskill MUST verify that the configured
Anthropic-compatible endpoint returns a structured `tool_use` block for a tool-bearing request and
offers at least the minimum context. It MUST name the endpoint and any proxy in the run manifest.

#### Scenario: Proxy without tool support

- **WHEN** the endpoint returns tool calls as plain text
- **THEN** preflight fails for that model under Claude Code, and the report lists it as unrun for that
  harness only

### Requirement: The same model can be compared across harnesses

Evaluation reports MUST treat harness as a dimension. When a model ran under both harnesses on the same
suite, reports MUST include a same-model comparison.

#### Scenario: One model, two harnesses

- **WHEN** a suite runs on `qwen3-32b` under OpenCode and under Claude Code
- **THEN** the report shows each harness's route metrics and pass rates for that model side by side
