# wikiskill

Log what agent skills and subagents actually do with a model, capture what the user had to correct,
distil a persistent wiki of failure and success patterns, and propose gated refinements — inside the
harness, across more than one harness and many models.

Based on [WikiSkill](https://arxiv.org/abs/2608.27454), which produces its execution traces from
benchmark runs. wikiskill produces them from ordinary use as well, which is why everything it
records carries harness, provider and model identity.

**Status:** roadmap steps 1 and 2 (`add-trace-logging`, `add-explicit-eval`) are done and archived:
trace logging, task suites, the OpenCode eval backend with isolation and preflight, the OFF, ROUTED
and INJECTED conditions, verifiers, and reports. Step 3, `add-minimal-loop`, is archived: the
review, refine and compare loop is built, and its live v1-against-v2 run moved to step 4's pilots. `add-brainhack-readiness` adds what a workshop needs:
preflight that survives slow local models, `wikiskill leaderboard` to pool runs across machines, and
the quickstart below. Correction capture (step 5) and Claude Code
logging (step 6) are built and await live checks; steps 4 and 7–9 are designed and not yet built. See [`ROADMAP.md`](ROADMAP.md).

**New here?** [The quickstart](docs/quickstart.md) goes from a clean machine to a finished,
poolable run on a local model; [bring your own collection](docs/bring-your-own-collection.md) then
evaluates your own skills.

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

### Comparing versions of a component

Each version of a component is the hash of its file. `wikiskill diff` shows what changed between two
of them, in text and in results, from what wikiskill already stores; it never runs an evaluation.

```bash
wikiskill diff datalad/datalad-doer --list --collection data-science-harness
wikiskill diff datalad/datalad-doer p-003^ p-003 --collection data-science-harness
wikiskill diff datalad/datalad-doer run:<run-id> current --collection data-science-harness
```

A version is `current`, a hash prefix of 7 or more hex digits, a proposal (`p-003` is its candidate,
`p-003^` what it was made from) or `run:<run-id>`. The results half compares the newest pair of
finished runs of the two versions on the same suite; `--run-a`/`--run-b` choose them. The report is
printed and saved under `evals/diff/`.

With more than two versions, rank them across models instead. `leaderboard --by-version` pools
runs that differ only in that component's version:

```bash
wikiskill leaderboard <run-id>... --collection data-science-harness \
  --by-version archive/archive-doer --critical critical.yaml
```

For each model it gives every version's pass rate with its interval, and the best version with
its direction against the baseline (`current` unless `--baseline` names another). Overall, each
version's mean counts every model equally, over the models that ran every version.
- A version that regresses any one model is never named best overall. A regression is a
  clearly lower interval on the model, or any one task falling by more than a third.
- A version that fails a check listed in `--critical` even once is never named best at all. The
  file lists checks as `{task: <id or *>, verifier: <0-based index>}`.
- OFF does not load the component, so one OFF run per model serves every version.

Both boards list the models that failed preflight, with their reasons. The leaderboard also counts
each model's units by outcome (`permission_blocked`, `step_exhausted`, ...), with median time and
tokens. With `--critical`, the version board also lists the checks each bare model broke under OFF,
which never disqualify a version. `--models-file` takes a model catalogue
([`examples/models.toml`](examples/models.toml)) giving each model's family and size. Rows are then
grouped by family and ordered by size.

`wikiskill report <run> --models-file models.toml` rebuilds a finished run's report from its own
files and runs nothing. A rubric graded by a judge panel (`[roles.judge] models = [...]`) shows each
judge's levels. The report also marks a judge from the family of the model it judged, and gives the
other judges' majority beside the full one. A rubric with `shows: [delegations]` lets its judge see
each handoff the model made, to grade it.

The board is saved under `evals/versions/`. It ranks and never decides: a winner still goes
through `proposal replay` and `proposal decide`. `wikiskill review --model <model>` reviews only
one model's eval units and live sessions, so a proposal can target that model.

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

For every file wikiskill writes, its format and its location, see [docs/data.md](docs/data.md).

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
uv sync          # the package and its dev tools: pytest, ruff, pyright
bin/check        # everything a commit should pass
```

`bin/check` runs, stopping at the first failure:
1. `ruff check` and `ruff format --check`.
2. `pytest`: the Python core, and the cross-language contract.
3. For each of `harness/opencode/plugin` (the OpenCode mapper, against recorded events) and
   `harness/opencode/guard` (the evaluation guard's deny patterns): `bun test` and `tsc`. With bun
   absent, this step is skipped, and the script says so.

It also runs pyright over `src/`, and its errors fail the check. Two runner modules are excluded
until a later refactor fixes them (see `[tool.pyright]` in `pyproject.toml`). A package without
`node_modules` gets a `bun install --frozen-lockfile` first.

**Commit-time checks** are opt-in:

```bash
uv run pre-commit install    # once per clone; writes .git/hooks/pre-commit
```

At each commit, the hook checks the staged files:
- `ruff check` and `ruff format --check` on staged Python;
- a parse of staged JSON and YAML.

It leaves out tests and bun, which stay in `bin/check`. Git worktrees share their main checkout's
`.git/hooks`, so installing from any of them installs for all.

**CI** (`.github/workflows/check.yml`) runs `bin/check` on pull requests and on pushes to `main`.

The OpenCode logger targets the plugin API at **1.18.31 or newer**. Its mapper tests run against
payloads **captured from a real OpenCode session**, and read the version out of the fixture rather
than asserting a release, so upgrading the harness does not break them. See
`harness/opencode/plugin/test/fixtures/README.md` for what is recorded, what is constructed, and
how to re-capture after an upgrade.

## Licence

MIT — see [`LICENSE`](LICENSE).
