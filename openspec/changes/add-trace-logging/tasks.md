## 0. Minimal working core

The schema and writer (1.1–1.3), the manifest (2.1–2.2), and a plugin that logs skill and task
activations and tool calls (3.1–3.4), installed on its own (4.3). That is enough to start collecting
real traces. Deferred: building wikiskill's own skills and agents (4.1–4.2) until `add-experience-wiki` adds the
first agent; backfill from `opencode.db`.

## 1. Raw event schema

- [ ] 1.1 Write `schemas/raw-event.schema.json` (`schema_version: 1`) with the envelope and the eight
  event types from design.md.
- [ ] 1.2 `src/wikiskill/rawlog.py`: reader, validator, and append-only writer; readers reject an
  unknown major `schema_version` with a clear message.
- [ ] 1.3 Add fixtures `tests/fixtures/raw/opencode-*.jsonl` and pytest cases that validate them.

## 2. Collection manifest

- [ ] 2.1 `src/wikiskill/collection.py`: load and validate the TOML manifest; `wikiskill collection
  init|show|check`.
- [ ] 2.2 `check` resolves source directories for both `opencode` and `claude-plugin` layouts, lists
  discovered skills and agents, reports unresolved watch-list names, and exits non-zero on any.
- [ ] 2.3 Reject a manifest whose judge model equals any configured target model.
- [ ] 2.4 Add `examples/collections/data-science-harness.toml` with an open-model alias table.

## 3. OpenCode logger plugin

- [ ] 3.1 `harness/opencode/plugin/wikiskill-logger.ts` using `event`, `tool.execute.after`, and
  `command.execute.before`.
- [ ] 3.2 Pure mapper module (OpenCode event → raw record); session ring buffer and watch-list flush;
  child sessions follow their root.
- [ ] 3.3 `source_hash`, redaction, 16 KB output truncation with length and hash.
- [ ] 3.4 Fail-open wrapper around every hook; error log under `raw/`.
- [ ] 3.5 Record real OpenCode 1.18.25 event fixtures and add `bun test` contract tests for the mapper.

## 4. Packaging

- [ ] 4.1 Create the `harness/source/` layout and document the neutral frontmatter in
  `harness/source/README.md`.
- [ ] 4.2 `wikiskill build --harness opencode` → `dist/opencode/` (agents with `mode: subagent`, a
  permission block, and a resolved model).
- [ ] 4.3 `wikiskill install --harness opencode --scope global|project` is idempotent, lists the files it
  writes, and records them; `--uninstall` removes exactly those.

## 5. Verify

- [ ] 5.1 `uv run pytest` — schema, manifest, and build tests pass.
- [ ] 5.2 `bun test harness/opencode/plugin` — mapper contract tests pass.
- [ ] 5.3 Smoke test: install into a temp project's `.opencode/`, watch a trivial skill, then run
  `opencode run --format json` against any endpoint with tool calling. `wikiskill log validate
  <collection>` should report at least one `component_activated` event and 0 schema errors. With no
  capable endpoint reachable, record the smoke test as unrun with the reason.
- [ ] 5.4 `git -C <source repo> status` is unchanged after `collection check` and `build`.
- [ ] 5.5 `openspec validate add-trace-logging --strict --no-interactive`.
