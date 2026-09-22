## Context

wikiskill can log sessions (`add-trace-logging`) and run isolated evaluations (`add-explicit-eval`), but
the loop those exist for has never run end to end. Reviewing the architecture before `add-dsh-pilot`
settled what the tool is for, and what the first milestone has to show.

**What the findings look like.** The target is the shape of the OHBM 2026 skills abstract:
- the same tasks with and without a skill, across several open models, repeated
- pass rates with intervals
- the direction per model (a skill helped three models and hurt two)
- a shift in tool choice
- two independently authored skill versions compared on the same baseline, and "we cannot say they
  differ" when the intervals overlap

A skill version comparison *is* that last comparison.

**How the tool is used.**
- Evaluation is **deliberate**. The user turns it on for one unit — a plugin's skills, or one subagent
  with its tooling — then runs it as tests or in ordinary use, then reviews what was observed.
- Logging makes no model call and costs no tokens, so leaving it on for a scoped unit is cheap.
  Review, refinement and eval are what spend tokens, and each is started by the user.
- Refinement is **user-triggered and versioned**; nothing is revised silently.

**Units are independent.** data-science-harness exposes tools and stages a project may or may not use,
so the first target is one unit, not the whole collection.

**Current gaps found while planning the pilot.**
- `build._harness_meta` reads only the neutral `capabilities` key. A DSH agent declaring
  `tools: Read, Bash, Grep, Glob` therefore builds with every permission denied, and ROUTED runs
  already install those broken agents, through `runner/opencode.py:_install_collection`.
- `model:` never goes through the alias table.
- `_merge_tree` lets one plugin silently overwrite another plugin's component of the same name.
- `wikiskill build --collection` builds only `harness/source`.
- Reports carry no intervals and no tool-choice data. Nothing compares two runs.

**Endpoint.** `opencode/big-pickle` is the only model that passes preflight here. Its probe times out
about half the time and passes on retry. The judge and maintainer can use local Ollama, since they
need only chat.

## Goals / Non-Goals

**Goals:**
- One unit goes through the whole loop once, with a readable v1-vs-v2 report at the end: scope, suite,
  eval, review, refine, apply, re-eval, compare.
- The build produces working subagents from claude-plugin sources.
- The comparison report is the light gate, and later the base of the replay gate.

**Non-Goals:**
- **Cross-model replay, gate states, and proposer enforcement.** These remain in
  `add-skill-refinement`, where the replay gate is a next step, not a first one.
- **Sampling at scale, digests, and watermarks.** These remain in `add-experience-wiki`.
- **The full DSH routing probe.** It becomes optional, after per-unit pilots.
- **Correction capture, the Claude Code adapter, and the collection graph.**
- **Editing data-science-harness.** Patches are files the user applies.

## Decisions

**Scoping is a manifest filter, not a new source type.**
- Source entries gain `plugins = [...]`, and the watch list already names components.
  `collection.discover()` and `_component_roots` honour the filter, so eval, watch and build all see
  the same unit.
- *Alternative:* point `path` at a single plugin directory. This fails today because the
  claude-plugin layout expects a root of plugins, and it would make the `plugin/name` prefix
  unrecoverable.

**`tools:` becomes neutral capabilities before anything else.**
- The map is:
  - Read → read
  - Grep and Glob → search
  - Bash → bash
  - Edit, Write, MultiEdit and NotebookEdit → edit
  - WebFetch and WebSearch → web
- Unknown tools warn. An explicit `capabilities:` wins over `tools:`. The source `tools` key is
  dropped from the output, because OpenCode's `tools` is a map that the build sets.
- *Alternative:* pass Claude tool names through. OpenCode ignores them, and the result is the
  current deny-all.

**Tier aliases, one level of indirection.**
- `[aliases.<harness>]` may map an alias to another alias: `haiku = "small"`, then
  `small = "opencode/big-pickle"`.
- Resolution follows at most one hop. `collection check` rejects cycles and chains that do not end
  in `provider/model`.
- `model:` is treated as an alias when `role_model` is absent.
- *Alternative:* map `haiku` straight to a model. This works, but it duplicates the tier choice for
  every Anthropic name and hides the design's small/large intent.

**Eval strips model pins; build and install keep them.**
- A subagent pinned to another model would mix models in a per-model row. So `build_collection(...,
  strip_models=True)` is used by the runner only.
- *Alternative:* keep pins and report them. That breaks the per-model reading the findings depend
  on.

**One `build_collection` shared by the CLI and the runner.**
- It moves `_component_roots` out of `runner/opencode.py`, builds each root into staging, and fails
  on a flat-name collision before merging, naming both plugins. It returns the `plugin/name → name`
  mapping.
- *Alternative:* keep two code paths. The runner already diverges silently, which is how the
  deny-all went unnoticed.

**First unit: `datalad/datalad-doer`.**
- It is a subagent with a specific job and real tooling, and `datalad` is installed locally.
- Each task's fixture setup runs `datalad create` in the run's own workdir, `DATALAD_AUTOSAVE=0` is
  set through the new suite `env`, and the guard denies `datalad push|siblings`, `git push` and
  network CLIs.
- Tasks are invoked directly, the INJECTED path for agents, and under OFF (no doer: the model is
  asked to do the same work unaided). This measures the doer's content, not the routing to it.
- *Alternatives:*
  - `bids-doer` is read-only, but `bids-validator` is absent and it needs a BIDS fixture.
  - A planner plus doer pair has two components in one outcome, so failures are harder to
    attribute.
- The choice stays open for revision.

**The minimal wiki reuses the planned layout.**
- `<collection>/wiki/` holds `index.md`, `patterns/*.md`, `log.md` and `skill-impact.md`, in a git
  repository per collection, as `add-experience-wiki` specifies. That change then adds sampling,
  digests and the watermark on top instead of migrating a layout.
- The maintainer's JSON contract is the paper's (create, update, index, log), validated by
  `schemas/maintainer-output.schema.json`, with bounded re-prompts.
- Its input is small by construction: one component's eval results plus that component's raw
  sessions, capped by characters.
- It runs headless against `roles.maintainer`, or in-harness via `/wikiskill-review`.

**Refinement output is a patch, not an edit.**
- `/wikiskill-refine <component>` writes `wiki/proposals/<id>/{patch.diff,preview.md,meta.json}`.
  `meta.json` holds the target `source_hash`, the patterns cited, and the proposer model.
- The user applies the patch in the source repository, and the next eval run's `source_hash` shows
  that a new version exists.
- *Alternative:* a branch in the source repository. Deferred to `add-skill-refinement`, which already
  specifies it, and only on request.

**Compare is computed from results, not re-run.**
- `wikiskill compare <run-a> <run-b>` reads both runs' `results.jsonl`. It requires the same suite
  name and task ids, and a differing `source_hash` for the component under test; it warns otherwise.
- It reports, per model and pooled, the pass rate with a Wilson 95% interval, and the direction:
  up, down, or no detectable difference when the intervals overlap. It never claims a difference the
  intervals do not support.
- The **tool-choice distribution** counts tool calls per condition and version from the trajectories
  already in the raw log.
- A sensitivity row repeats the pooled comparison with `timeout` outcomes excluded.
- *Alternative:* a statistical test (Fisher's exact test). The overlap of intervals is cruder but
  matches how the findings are reported and is hard to misread. The test can come later.

**The gate is a human decision, recorded.**
- `wikiskill compare --record accept|reject --proposal <id>` appends the decision, both run ids,
  both hashes and the pooled result to `skill-impact.md`.
- Nothing is applied or reverted automatically.

## Risks / Trade-offs

- [Big-pickle preflight flakes] → Retry once. The comparison refuses runs whose models differ, so a
  partial run cannot be misread as a model effect.
- [Five tasks × few repeats gives wide intervals] → The report says "no detectable difference"
  rather than implying one. Repeats are a flag, and the user chooses the cost.
- [The weak maintainer produces invalid JSON] → Schema validation with bounded re-prompts, and
  nothing is written on failure, as `add-experience-wiki` specifies.
- [A patch touches the DSH source] → wikiskill only writes the patch file. The user applies it. The
  source repository's `git status` is checked unchanged by every wikiskill command.
- [Capability names collide with later changes] → `add-experience-wiki` and `add-skill-refinement`
  must rebase their `ADDED` deltas to `MODIFIED` or `ADDED` against these specs before they are
  applied. This is recorded in their tasks.
- [DataLad side effects in the workdir] → The dataset is created per unit inside the run's temp root.
  `DATALAD_AUTOSAVE=0` is set, and the guard blocks anything that leaves the machine.

## Open Questions

- Should the tier values stay `opencode/big-pickle` for both tiers until a second endpoint exists, or
  should `small` point at a local model once one passes preflight?
- Should OFF for a doer task be "no doer available" or "a generic subagent with the same tools"? The
  second isolates content from tooling more cleanly.
- Should tool-choice distributions be reported for OFF as well? This matters for the "the skill
  shifted tool choice" finding. The design currently says yes.
