## Why

Steps 1 and 2 built the logger and the eval runner, but the loop they exist for has never run. The
tool cannot yet be taken from a skill to an observed, reviewed, revised and re-measured skill. The
findings wanted are per-model comparisons of skill versions, reported the way the OHBM 2026 skills
abstract reports them: pass rates with intervals, the direction per model, and a shift in tool choice.
That needs the whole loop working once, on one small unit, with a light human gate. It should come
before the full DSH routing probe, and before cross-model replay.

## What Changes

- **Units.** A manifest can narrow a claude-plugin source to chosen plugins or components, so one
  plugin's skills or one subagent with its tooling is evaluated, watched and refined on its own.
- **Build of claude-plugin sources.**
  - Claude `tools:` becomes OpenCode permissions. Today every DSH agent builds with bash denied.
  - `model:` resolves through tier aliases (`haiku` → `small`, `sonnet`/`opus` → `large`).
  - Flat-name collisions fail the build.
  - `wikiskill build --collection` builds the collection's own sources.
- **Eval.** Subagents inherit the model under test, so model pins are stripped in eval runs. Suites may
  set environment variables.
- **A first unit with its own suite:** `datalad/datalad-doer`. About five capability tasks with
  verifiers run in a disposable DataLad dataset, with the guard denying push and siblings.
- **Minimal review.** `/wikiskill-review <component>` and a `wikiskill-maintainer` agent turn a unit's
  eval results and raw sessions into validated pattern pages under `<collection>/wiki/`.
- **Minimal refine.** `/wikiskill-refine <component>` produces exactly one patch plus a preview. The
  user applies it; nothing is applied automatically.
- **Version comparison as the light gate.** `wikiskill compare <run-a> <run-b>` compares two runs of the
  same suite whose component `source_hash` differs. It reports:
  - per-model and pooled pass rates with Wilson 95% intervals
  - the direction per model
  - "no detectable difference" when the intervals overlap
  - the tool-choice distribution
  - a sensitivity row with timeouts excluded

  The user's accept or reject decision is recorded in `skill-impact.md`.

## Capabilities

### New Capabilities

- `experience-wiki`: the minimal wiki (pattern pages, index, log, skill-impact record), the maintainer's
  validated output contract, and `/wikiskill-review`, scoped to one component. Sampling and digests at
  scale stay with `add-experience-wiki`.
- `refinement-proposal`: `/wikiskill-refine` producing one user-applied patch and preview per
  invocation, grounded in the wiki. Replay and gate states stay with `add-skill-refinement`.
- `version-comparison`: comparing two runs of one suite across component versions, with intervals,
  per-model direction, tool choice and timeout sensitivity. This is the light gate.

### Modified Capabilities

- `collection-config`: unit scoping within a source; aliases may chain to a tier alias.
- `harness-packaging`: building a collection's claude-plugin sources, including `tools:` translation,
  `model:` resolution and collision detection.
- `eval-runner`: model pins stripped under evaluation; per-suite environment.

## Impact

- Depends on `add-trace-logging` (raw log, `source_hash`) and `add-explicit-eval` (runner, suites,
  reports). Both are archived.
- Precedes `add-dsh-pilot`, which becomes per-unit pilots built on this loop. The full routing probe
  across the whole collection becomes optional.
- `add-experience-wiki` and `add-skill-refinement` extend the capabilities introduced here rather than
  adding them. Their delta specs must be rebased onto these before they are applied.
- Touches nothing in `~/Projects/claude/data-science-harness`. Patches for it are files the user
  applies.
- New code:
  - `src/wikiskill/{compare,wiki,refine}.py`
  - `harness/source/agents/{wikiskill-maintainer,wikiskill-proposer}.md`
  - `harness/source/commands/{wikiskill-review,wikiskill-refine}.md`
  - `schemas/maintainer-output.schema.json`
  - `pilots/datalad-doer/`
- Changed code:
  - `build.py`, `collection.py`, `runner/opencode.py`, `suite.py`, `cli.py`
  - `examples/collections/data-science-harness.toml`
