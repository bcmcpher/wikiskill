## Why

Most skill development happens in Claude Code, and many collections (data-science-harness included)
are written as Claude Code plugins first. Comparing the same skill across harnesses separates harness
effects from model effects. Refining skills without seeing how they behave where they are authored
would miss half the picture. Claude Code can reach open models through an Anthropic-compatible
endpoint, so the same model can run under both harnesses. This change adds Claude Code as the
secondary target on the harness-neutral core, with no second copy of anything.

## What Changes

- A Claude Code plugin build of wikiskill's single-source components: `.claude-plugin/plugin.json`,
  skills, commands, agents with `tools:` mapped from neutral capabilities, and `hooks/hooks.json`.
- A hooks logger: `PostToolUse` (Skill, Agent, other tools), `UserPromptSubmit`, `Stop`, and
  `SubagentStop` call the `wikiskill` CLI by explicit path and write the same raw schema. It is
  fail-open.
- Correction capture on Claude Code: follow-up turns via `UserPromptSubmit`, output edits via the shared
  scanner, and `/wikiskill-note`.
- A `claude -p --output-format stream-json` eval backend with isolation, ROUTED via `--plugin-dir`, and
  INJECTED via `--append-system-prompt`.
- Preflight for Anthropic-compatible endpoints set with `ANTHROPIC_BASE_URL`.
- A harness axis in eval reports.

## Capabilities

### New Capabilities

- `claude-code-adapter`: Claude Code logging via hooks, the stream-json backend, and running open models
  in Claude Code.

### Modified Capabilities

- `harness-packaging`: adds the Claude Code plugin build target.
- `correction-signal`: adds the Claude Code capture path.
- `eval-runner`: adds the Claude Code backend and harness as a matrix axis.

## Impact

- **Depends on `add-trace-logging`**, **`add-correction-capture`**, and **`add-explicit-eval`**. It adds
  requirements to their capabilities without changing existing ones.
- Fifth on the roadmap, so real Claude Code development sessions feed the raw log before the wiki is
  built.
- `add-dsh-pilot` gains a Claude Code arm: same suite, same models, both harnesses.
- New: `harness/claude-code/hooks/`, `src/wikiskill/runner/claude.py`, `src/wikiskill/hooks.py`.
- Hook commands use an explicit path to `wikiskill`. Hooks run in non-interactive shells, where
  PATH-dependent names may not resolve.
