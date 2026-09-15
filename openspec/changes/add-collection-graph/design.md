## Context

The refinement gate (`add-skill-refinement`) replays a component's own motivating cases and regression bank. That
misses collateral damage.

GSE models dependency, co-usage, and conflict edges between skills, and replays neighbours before
accepting a change. HiSkill adds support and recovery edges for execution routing. We need only the
first three, for evaluation.

data-science-harness already declares `delegates_to` on planner skills. Its routing suite includes
deliberate near-miss pairs, such as checkpoint vs release and publish vs release, which are exactly
the conflict edges that description edits can disturb.

## Goals / Non-Goals

**Goals:**
- A graph built from what the collection declares and what logs and evals observe, with each edge's
  evidence.
- Wider replay and a trigger-theft check driven by it.

**Non-Goals:**
- **Joint multi-component proposals** — proposals stay atomic.
- **Using the graph at inference time** to route or recover (HiSkill-style) — out of scope.

## Decisions

**Edge sources and weights.**
- `dependency`: declared `delegates_to` (weight 1.0) and skill-name mentions in bodies (0.5).
- `co_usage`: count of sessions where both components activated, normalised by the rarer component's
  session count.
- `conflict`: routing-confusion rate from eval reports (expected A, routed B), taken as the maximum
  across models, with per-model values kept.

Each edge stores its evidence: frontmatter location, session ids, or eval run ids.

**Storage.** `wiki/graph.json`, rebuilt by `wikiskill graph build` and committed with the wiki, so
graph changes are versioned alongside patterns.

**Neighbours for replay.**
- Dependency neighbours at depth 1 in both directions.
- Co-usage neighbours above 0.2.
- All conflict neighbours above 0.05.

Thresholds are configurable.

**Trigger-theft check.** When a proposal edits a skill's `description`, the gate adds routing tasks
whose expected route is a conflict neighbour to the replay. If the candidate lowers any neighbour's
`route@1` on any model beyond tolerance, that is a listed regression.

## Risks / Trade-offs

- [Prose-reference edges are noisy] → lower weight; evidence shown; can be excluded per collection.
- [Sparse logs give weak co-usage] → co-usage requires a minimum session count before an edge is kept.
- [Replay cost grows with neighbours] → depth-1 only; a cap on neighbour tasks per proposal, reporting
  what was capped.

## Open Questions

- Should conflict edges also come from passive logs, for example a user correction that re-invokes a
  different skill?
