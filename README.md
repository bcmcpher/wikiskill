# wikiskill

Log what agent skills and subagents actually do with a model, capture what the user had to correct,
distil a persistent wiki of failure and success patterns, and propose gated refinements — inside the
harness, across more than one harness and many models.

Based on [WikiSkill](https://arxiv.org/abs/2608.27454), which produces its execution traces from
benchmark runs. wikiskill produces them from ordinary use as well, which is why everything it
records carries harness, provider and model identity.

**Status:** `add-trace-logging` (roadmap step 1) is implemented, and `add-explicit-eval` (step 2) has
its minimal working core: task suites, the OpenCode eval backend with isolation and preflight, the
OFF and ROUTED conditions, routing metrics and reports. Steps 3–8 are designed and not yet built —
see [`ROADMAP.md`](ROADMAP.md).

## What works today

A harness-neutral raw log, a collection manifest describing what is watched, an OpenCode plugin that
fills the log passively, and the packaging that installs them.

```bash
uv tool install .

# Declare what to watch; edit the generated watch list.
wikiskill collection init data-science-harness --source ~/Projects/claude/data-science-harness/plugins
wikiskill collection check data-science-harness --sync

# Install the logger into OpenCode.
wikiskill install --harness opencode --scope global --collection data-science-harness

# Use OpenCode normally, then look at what was recorded.
wikiskill log stats data-science-harness
wikiskill log validate data-science-harness
wikiskill log tail data-science-harness -f
```

A worked manifest with an open-model alias table is in
[`examples/collections/data-science-harness.toml`](examples/collections/data-science-harness.toml).

### Explicit evaluation

Passive logs cannot answer "is this skill better on model X than model Y?". A task suite can: the
same prompts, across a list of models, with and without the collection, repeated.

```bash
wikiskill suite check examples/suites/toy-routing.yaml

wikiskill eval --suite examples/suites/toy-routing.yaml \
  --collection data-science-harness \
  --models ollama/qwen2.5-coder:1.5b \
  --condition off,routed
```

Every run happens in a **fresh headless OpenCode session** with its own XDG directories, an inline
config carrying only the target provider, project config and Claude Code discovery switched off, no
MCP servers, and a guard plugin refusing the commands the task denies. Results land in
`${XDG_DATA_HOME:-~/.local/share}/wikiskill/<collection>/evals/<run-id>/` as `run.json`,
`results.jsonl`, `report.json` and `report.md`, and the trajectories are appended to the raw log with
`origin: eval`.

Before any task runs, each model is preflighted for reachability, tool calling and context window.
A model that fails is skipped with an actionable message rather than scoring zero — on a CPU-only
laptop with Ollama's 4096-token default, that is the usual outcome, and the report says so.

## What it records, and what it will not

- Only sessions that activate a **watched** skill, agent or command are logged. A session that never
  touches one writes nothing. When an activation happens mid-session, the buffered turns that
  preceded it are written with it.
- Every activation carries a `source_hash` — SHA-256 of the component's file as it was at that
  moment — so two runs of a skill that changed in between are distinguishable.
- A delegation chain is one file: a child session's events are written into its root's log.
- Logging is **fail-open** and makes **no model call**. A logging failure never interrupts or alters
  a session; it goes to `raw/_logger-errors.log` when that is writable, and is dropped otherwise.
- Environment values and secret-shaped strings become `[REDACTED:<kind>]`; tool output above a bound
  is truncated, with the original length kept.
- Nothing is ever written into a collection's source repository.

## Layout

| Path | What lives there |
|---|---|
| `src/wikiskill/` | the harness-neutral Python core and the `wikiskill` CLI |
| `schemas/raw-event.schema.json` | the versioned raw event schema — the contract between harnesses |
| `schemas/task-suite.schema.json` | the declarative task suite format |
| `harness/opencode/plugin/` | the OpenCode logger (TypeScript), with its own contract tests |
| `harness/opencode/guard/` | the evaluation guard, installed only into an eval run's own config |
| `harness/source/` | wikiskill's own skills, commands and agents, authored once |
| `examples/collections/` | worked manifests |
| `examples/suites/` | a small worked task suite |
| `openspec/` | the change proposals, specs and roadmap this is built from |
| `docs/design/architecture.md` | why it is shaped this way |

Storage follows XDG: config in `${XDG_CONFIG_HOME:-~/.config}/wikiskill/`, data in
`${XDG_DATA_HOME:-~/.local/share}/wikiskill/<collection>/{raw,wiki,evals}`.

## Development

```bash
uv sync --extra dev
uv run pytest                                 # Python core, and the cross-language contract
cd harness/opencode/plugin && bun test test   # the OpenCode mapper against recorded events
cd harness/opencode/guard && bun test test    # the evaluation guard's deny patterns
```

The OpenCode logger targets the plugin API at **1.18.31 or newer**. Its mapper tests run against
payloads **captured from a real OpenCode session**, and read the version out of the fixture rather
than asserting a release, so upgrading the harness does not break them. See
`harness/opencode/plugin/test/fixtures/README.md` for what is recorded, what is constructed, and
how to re-capture after an upgrade.

## Licence

MIT — see [`LICENSE`](LICENSE).
