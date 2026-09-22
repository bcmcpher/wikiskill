## Why

wikiskill needs a real collection to prove its value. data-science-harness is the intended one. It has
dozens of skills across planner, doer, and toolbox layers, and it installs into both OpenCode and
Claude Code. Its routing suite already defines near-miss tasks, and its evaluation protocol is
written down but explicitly unrun. Its OpenCode installer maps models only to Anthropic ids, so it has
never been exercised on open models. A pilot turns the protocol's routing probe into first results,
per model, and starts passive logging in real use.

## What Changes

- **Per-unit pilots on the loop from `add-minimal-loop`.** A unit is one plugin's skills, or one doer
  with its toolbox. Each unit gets:
  - its own collection in `pilots/<unit>/`, narrowed with `plugins = [...]`
  - a capability suite whose `setup` builds the starting state, with verifiers checked by hand
  - tasks that only the unit's own instructions can pass, so OFF does not reach a ceiling
  - a v1 run, a review, a proposal, a v2 run, and a `wikiskill compare` with the decision recorded

  `datalad/datalad-doer` is the first unit, done in `add-minimal-loop`.
- A DSH pilot report in the protocol's own terms: the named control, per-model reporting, and unrun
  probes stated.
- **The routing probe, optional.** `bench/tasks/routing-lifecycle.yaml` through explicit eval under
  OFF, ROUTED and INJECTED across the whole collection. It runs once per-unit pilots have shown the
  loop works on DSH components.
- Passive logging and correction capture enabled for a watch list of planner skills and doer agents.
- **Phase 2 (specified, deferred):** provenance and reproducibility probes. They need a sandbox with
  fake credentials, local siblings, `DATALAD_AUTOSAVE=0` for the auto-commit Stop hook, and a
  synthetic BIDS dataset.

## Capabilities

### New Capabilities

- `dsh-pilot`: running data-science-harness's evaluation protocol through wikiskill on open models, and
  logging its real use.

## Impact

- **Follows `add-minimal-loop`** (roadmap step 3). This change will be reshaped into per-unit
  pilots built on that loop, and its full-collection routing probe becomes optional.
- **Depends on `add-minimal-loop`** for the per-unit loop, and on `add-explicit-eval` for the runner. Passive use needs `add-trace-logging`,
  `add-correction-capture`, and `add-experience-wiki`; refinement needs `add-skill-refinement`.
- Gains a Claude Code arm once `add-claude-code-adapter` lands: the same suite and models across both
  harnesses.
- Touches nothing in `~/Projects/claude/data-science-harness`. Results live under the wikiskill data
  directory; a summary goes in `docs/pilots/dsh-routing.md` here.
- New: `examples/collections/data-science-harness.toml` (extended), `pilots/dsh/`, `docs/pilots/`.
