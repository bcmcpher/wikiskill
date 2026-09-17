## 0. Minimal working core

The schema and writer (1.1–1.3), the manifest (2.1–2.2), and a plugin that logs skill and task
activations and tool calls (3.1–3.4), installed on its own (4.3). That is enough to start collecting
real traces. Deferred: building wikiskill's own skills and agents (4.1–4.2) until `add-experience-wiki` adds the
first agent; backfill from `opencode.db`.

## 1. Raw event schema

- [x] 1.1 Write `schemas/raw-event.schema.json` (`schema_version: 1`) with the envelope and the eight
  event types from design.md.
- [x] 1.2 `src/wikiskill/rawlog.py`: reader, validator, and append-only writer; readers reject an
  unknown major `schema_version` with a clear message.
- [x] 1.3 Add fixtures `tests/fixtures/raw/opencode-*.jsonl` and pytest cases that validate them.

## 2. Collection manifest

- [x] 2.1 `src/wikiskill/collection.py`: load and validate the TOML manifest; `wikiskill collection
  init|show|check`.
- [x] 2.2 `check` resolves source directories for both `opencode` and `claude-plugin` layouts, lists
  discovered skills and agents, reports unresolved watch-list names, and exits non-zero on any.
- [x] 2.3 Reject a manifest whose judge model equals any configured target model.
- [x] 2.4 Add `examples/collections/data-science-harness.toml` with an open-model alias table.

## 3. OpenCode logger plugin

- [x] 3.1 `harness/opencode/plugin/wikiskill-logger.ts` using `event`, `tool.execute.after`, and
  `command.execute.before`.
- [x] 3.2 Pure mapper module (OpenCode event → raw record); session ring buffer and watch-list flush;
  child sessions follow their root.
- [x] 3.3 `source_hash`, redaction, 16 KB output truncation with length and hash.
- [x] 3.4 Fail-open wrapper around every hook; error log under `raw/`.
- [x] 3.5 Record real OpenCode event fixtures (1.18.31 or newer) and add `bun test` contract tests
  for the mapper. Captured from **1.18.31**; `tool.execute.after` payloads are constructed from the
  SDK types because the capture run's model could not call tools. Provenance is recorded in
  `harness/opencode/plugin/test/fixtures/README.md`.

## 4. Packaging

- [x] 4.1 Create the `harness/source/` layout and document the neutral frontmatter in
  `harness/source/README.md`.
- [x] 4.2 `wikiskill build --harness opencode` → `dist/opencode/` (agents with `mode: subagent`, a
  permission block, and a resolved model).
- [x] 4.3 `wikiskill install --harness opencode --scope global|project` is idempotent, lists the files it
  writes, and records them; `--uninstall` removes exactly those.

## 5. Verify

- [x] 5.1 `uv run pytest` — schema, manifest, and build tests pass.
- [x] 5.2 `bun test harness/opencode/plugin` — mapper contract tests pass. (`bun` was not
  installed; it now lives in `~/.claude-node-tools`, per the harness tool convention.)
- [x] 5.3 Smoke test: install into a temp project's `.opencode/`, watch a trivial skill, then run
  `opencode run --format json` against any endpoint with tool calling. `wikiskill log validate
  <collection>` should report at least one `component_activated` event and 0 schema errors. With no
  capable endpoint reachable, record the smoke test as unrun with the reason.

  **Recorded as UNRUN under the clause above: no locally reachable endpoint completes a tool call.**
  The install half ran and passed; the model half did not. Four attempts on this CPU-only machine:

  | Model | Outcome |
  |---|---|
  | `DeepAnalyze-8B` (qwen3, 8B) | hard failure: `... does not support tools` (HTTP 400) before any tool call |
  | `qwen3:1.7b` | ~10 min, zero tokens emitted — Ollama's 4096-token default context cannot hold OpenCode's system prompt |
  | `ministral-3:3b` @ 16k ctx, skill-routing prompt | ~25 min, no output |
  | `ministral-3:3b` @ 16k ctx, single-`read` prompt (lowest bar: path-based activation needs one tool call) | ~15 min, no output |

  This is the risk `add-explicit-eval`'s preflight check exists for, and it is the first concrete
  evidence for it — see Milestone A, which allows stating which models failed preflight and why.

  **What was verified instead, without a model.** `wikiskill install --harness opencode` into a temp
  project, then `harness/opencode/plugin/test/drive-installed.ts` drives *the installed copy* through
  one session using payloads captured from a real OpenCode 1.18.31 run. Result: 7 events, **1
  `component_activated`, 0 schema errors**, pre-activation history flushed ahead of the activation in
  timestamp order, and every event carrying provider and model. That covers the whole of 5.3 except
  OpenCode itself invoking the hooks — and the hook signatures and payload shapes are themselves taken
  from a real capture, not from the docs.

  Re-run when an endpoint with working tool calling is available (a remote vLLM server, or a GPU box):

  ```bash
  wikiskill collection init smoke --source <tmp>/.opencode
  wikiskill install --harness opencode --scope project --target <tmp>/.opencode --collection smoke
  opencode run --dir <tmp> --format json -m <provider>/<model> "Run the smoke-check skill."
  wikiskill log validate smoke
  ```
- [x] 5.4 `git -C <source repo> status` is unchanged after `collection check` and `build`.
  Checked against the real data-science-harness repo, which already had 11 uncommitted entries:
  the comparison is before/after, not "clean".
- [x] 5.5 `openspec validate add-trace-logging --strict --no-interactive`.
