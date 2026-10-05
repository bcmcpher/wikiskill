## ADDED Requirements

### Requirement: Correction capture on Claude Code

On Claude Code, wikiskill MUST record follow-up turns from `UserPromptSubmit`, repeated activations from
`PostToolUse`, produced files from Write and Edit tool calls, and `/wikiskill-note` flags. They MUST use
the same event types and attribution rules as on OpenCode.

#### Scenario: Correction after a skill in Claude Code

- **WHEN** a watched skill runs in Claude Code and the user's next prompt corrects its output
- **THEN** a `user_turn` event with confidence `high` and `harness: claude-code` is attributed to that
  skill
