## ADDED Requirements

### Requirement: Claude Code evaluation backend

The runner MUST provide a Claude Code backend that executes tasks with `claude -p` stream-json output in
an isolated configuration directory. It MUST support:
- OFF: without the plugin
- ROUTED: with the built collection via `--plugin-dir`
- INJECTED: component text appended to the system prompt with the `Skill` tool disallowed

#### Scenario: Isolation from user configuration

- **WHEN** the user has personal plugins, skills, and MCP servers configured in Claude Code
- **THEN** a Claude Code evaluation run loads none of them, and its run manifest shows only the
  collection under test

#### Scenario: Shared outcome classes

- **WHEN** a Claude Code run ends with the model printing a tool call as text
- **THEN** it is classified `tool_call_as_text`, exactly as on OpenCode
