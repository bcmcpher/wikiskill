## Why

WikiSkill learns only from task scores. In real use, most of the signal is what the user had to fix:
a follow-up like "no, use a mixed model", a re-run of the same skill, a hand edit to the notebook the
agent produced. Work on developer interaction histories (arXiv 2608.10319) shows such traces are
usable but noisy. So capture should be broad and cheap now, classification should be left to the wiki
maintainer, and the user needs one explicit, high-confidence way to say "this was wrong".

## What Changes

- `user_turn` events for user messages that follow a watched component's activity within a
  configurable window, attributed to that component with a confidence level.
- `output_edit` events when files a watched component wrote are later changed by something other
  than a logged tool call, with a bounded diff.
- `repeat_activation` events when the same component is re-activated within the window.
- `/wikiskill-note [component] <text>` command and `wikiskill note` CLI for explicit correction flags.
- No labelling: nothing in this change decides whether an event is a correction or an approval.

## Capabilities

### New Capabilities

- `correction-signal`: capture of follow-up turns, output edits, repeated activations, and explicit
  notes as raw events attributed to components.

## Impact

- **Depends on `add-trace-logging`**: extends its raw schema (minor version bump) and its OpenCode
  plugin.
- Consumed by `add-experience-wiki`, which classifies these signals.
- This change implements OpenCode capture; `add-claude-code-adapter` adds the Claude Code equivalent
  against the same event types.
- New: `harness/source/commands/wikiskill-note.md`, `src/wikiskill/corrections.py`, plugin additions.
