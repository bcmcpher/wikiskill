## ADDED Requirements

### Requirement: Claude Code plugin build

`wikiskill build --harness claude-code` MUST produce a Claude Code plugin from the same single-source
tree, with a plugin manifest, skills, commands, agents whose `tools:` are derived from neutral
capabilities, and hooks that reference the `wikiskill` CLI by absolute path.

#### Scenario: Neutral agent built for Claude Code

- **WHEN** a neutral agent declares `capabilities: [read, search]`
- **THEN** the Claude Code build gives it `tools: Read, Grep, Glob` and no Bash, Edit, Write, or web
  tools

#### Scenario: Hook command resolution

- **WHEN** the built `hooks/hooks.json` is inspected
- **THEN** every hook command is an absolute path that runs in a non-interactive shell with a minimal PATH
