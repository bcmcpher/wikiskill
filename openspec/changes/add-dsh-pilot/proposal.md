## Why

wikiskill needs a real collection to prove its value. data-science-harness is the intended one. It has
dozens of skills across planner, doer, and toolbox layers, and it installs into both OpenCode and
Claude Code. Its routing suite already defines near-miss tasks, and its evaluation protocol is
written down but explicitly unrun. Its OpenCode installer maps models only to Anthropic ids, so it has
never been exercised on open models.

The first unit, `archive/archive-doer`, has been through the whole loop on two models. That showed the
loop works on DSH. It also left three gaps:
- Two models from two families, at n = 18 per cell, cannot say how a component's value depends on the
  model. The intervals are about 40 points wide.
- The one real finding, a readiness-script path that does not resolve outside a DSH checkout, was
  never tested as a change.
- The protocol's own probe, routing, has no results.

The GB10 now serves models from six families locally, from 1.7B to 120B, so a broader check needs no
remote endpoint.

## What Changes

- **Per-unit pilots on the loop from `add-minimal-loop`** (done for `archive/archive-doer`). A unit
  is one plugin's skills, or one doer with its toolbox, with its own collection, a capability suite
  checked by hand, a v1 run, a review, a proposal, a candidate run and a recorded decision.
- **A hand-written candidate for the readiness path**, through the same gate as a generated
  proposal: `refine --prepare`, a reply written by hand, `eval --proposal`, replay, and decide. If it
  is accepted, it goes to the DSH maintainer with its comparison.
- **A model sweep on the archive-doer suite.**
  - Every model the server offers is preflighted.
  - Every model that passes runs OFF and INJECTED, with repeats chosen up front for usable
    intervals.
  - A thinking arm runs for the models that reason.
  - A same-model rerun measures run-to-run noise.
  - Results are pooled with `wikiskill leaderboard`.
- **The routing probe, now required.**
  - `bench/tasks/routing-lifecycle.yaml` runs over the whole collection under OFF and ROUTED, with
    INJECTED as a supplement.
  - `route@1`, `route@k` and `capability@k` are reported per model.
  - `handoff@k` is scored by three judges.
- **The `datalad/datalad-doer` unit is retired.** Its doer was deleted upstream; its suite stays
  for the record and is not run.
- A DSH pilot report in the protocol's own terms: the named control, per-model reporting, and unrun
  probes stated.

**Moved out of this change:** passive logging in real use (old 5.x) and the Phase 2 provenance and
reproducibility probes (old 6.x). Neither is model evaluation, and both would keep this change open
indefinitely. Each becomes its own change when it is started.

## Capabilities

### New Capabilities

- `dsh-pilot`: running data-science-harness's evaluation protocol through wikiskill on open models.

## Impact

- **Depends on** `add-minimal-loop` for the per-unit loop, `add-explicit-eval` for the runner,
  `add-skill-refinement` for the gate, and on `wikiskill leaderboard` and `wikiskill diff`, all
  landed.
- Touches nothing in `~/Projects/claude/data-science-harness`. Results live under the wikiskill data
  directory; the summary is `docs/pilots/dsh.md` here.
- New: `pilots/dsh/` (the routing collection and suite), a handoff rubric, and new sections of
  `docs/pilots/dsh.md`.
- GPU time: the sweep and the routing probe take hours per model on the larger dense models. The
  design orders runs so that a partial sweep is still reportable.
