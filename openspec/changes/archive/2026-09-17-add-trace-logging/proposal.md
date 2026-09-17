## Why

Every later stage — the wiki, refinement, cross-model comparison — needs a record of what a skill or
subagent actually did with a model. Nothing provides one today: OpenCode keeps sessions in a private
SQLite store and Claude Code in per-project transcripts, in different shapes, with no notion of which
skill was active, which version of it, or which model ran it. WikiSkill's raw layer assumes such a
record exists. A harness-neutral raw log, filled passively by a thin OpenCode plugin, is the foundation.

## What Changes

- A collection manifest (TOML) naming source directories, a watch list of skills and agents, per-role
  meta-model endpoints, and per-harness model alias tables.
- A versioned, harness-neutral raw event schema (JSON Schema) with a Python reader, validator and
  append-only writer.
- An OpenCode logger plugin (TypeScript) that writes raw JSONL for sessions touching watched components.
- A single-source tree for wikiskill's own skills, commands and agents, with a build and install step
  for OpenCode.
- A `wikiskill` CLI skeleton: `collection init|show|check`, `log validate|stats|tail`, `build`, `install`.

## Capabilities

### New Capabilities

- `collection-config`: the manifest declaring what is watched, where it lives, and which models serve
  each role in each harness.
- `trace-log`: the append-only, harness-neutral raw event log and the OpenCode plugin that fills it.
- `harness-packaging`: building wikiskill's single-source components into harness layouts and
  installing them.

## Impact

- New: `pyproject.toml`, `src/wikiskill/`, `schemas/raw-event.schema.json`, `harness/source/`,
  `harness/opencode/plugin/`, `tests/`, `examples/collections/`.
- Writes only under the wikiskill XDG config and data directories and the chosen OpenCode config
  directory; never into a collection's source repository.
- First on the roadmap (`ROADMAP.md`); every other change depends on it.
- Targets the OpenCode plugin API at **1.18.31 or newer**. The plugin declares its own floor
  (`^1.18.31`) rather than inheriting the user's global OpenCode config, which pins
  `@opencode-ai/plugin` 1.14.22 against a much newer binary. The harness is updated often, so
  drift is *detected* rather than pinned away: contract tests run against recorded payloads and
  every event carries `harness_version`.
