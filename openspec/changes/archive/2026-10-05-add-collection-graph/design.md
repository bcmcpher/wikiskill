## Context

The refinement gate (`add-skill-refinement`, `src/wikiskill/gate.py`) compares a baseline run of a
suite at the proposal's `source_hash` with a candidate run of the same suite made by `wikiskill eval
--proposal`. The motivating cases are the suite tasks the cited patterns came from, and the
regression bank is every other task. Replay re-runs nothing and chooses no suite.

So "replay a neighbour" cannot mean adding runs. The bank already holds every task of the suite, and
every task that fell is already listed per model. What the gate lacks is knowledge of the collection:
which tasks belong to a neighbour, which neighbours the suite leaves out, and whether a description
edit moved another component's routing. `compare` scores verifiers only, so a routing-only task that
loses its route does not show as a fallen task at all.

GSE models dependency, co-usage, and conflict edges between skills, and replays neighbours before
accepting a change. HiSkill adds support and recovery edges for execution routing. We need only the
first three, for evaluation, and build two now.

data-science-harness declares `delegates_to` on planner skills, naming plugins, such as
`delegates_to: [archive]` on `disseminate/dataset-release`. Its routing suite includes deliberate
near-miss pairs, such as checkpoint vs release and publish vs release, which are exactly the conflict
edges that description edits can disturb.

## Goals / Non-Goals

**Goals:**
- A graph built from what the collection declares and what eval runs observe, with each edge's
  evidence.
- Replay that names neighbours and their tasks, warns on uncovered neighbours, and checks description
  edits for trigger theft.

**Non-Goals:**
- **Adding runs to a replay.** The user chooses the suite; replay says what it cannot see.
- **Joint multi-component proposals** — proposals stay atomic.
- **Using the graph at inference time** to route or recover (HiSkill-style) — out of scope.
- **Co-usage edges, for now.** Every raw log on this machine was counted on 2026-10-05: 48 eval units
  and 2 live sessions activated one component, 1 eval unit activated two, and no live session
  activated two. Eval co-activation reflects the suite's design, not use. The edge waits for live logs.

## Decisions

**Edge sources and weights.**
- `dependency`:
  - Declared `delegates_to` (weight 1.0). An entry naming a plugin points at that plugin's agents,
    the doers. An entry naming a component, by full or unique bare name, points at it. An entry that
    resolves to nothing in the collection is kept as an unresolved delegation and shown, since a
    collection often selects only some plugins.
  - Component mentions in bodies (0.5): a full `plugin/name` as a whole word, or a bare name in
    backticks. Bare names in prose are too common a word to count.
  - Declared and mentioned together make one edge of weight 1.0 with both pieces of evidence.
- `conflict`: from the ROUTED condition of eval runs, the share of a task's scored repeats whose
  first activation was another component, by expected route and model, pooled over runs. The edge
  runs from the expected component to the one that took its trigger. Its weight is the maximum over
  models; the per-model rates are kept. Candidate runs (`run.json` names a proposal) are left out:
  they test a version that was never accepted.

Each edge stores its evidence: the file and line, or the run, task and model with counts.

**Storage.** `wiki/graph.json`, rebuilt by `wikiskill graph build` from every run under the
collection (or the runs named), and committed with the wiki, so graph changes are versioned alongside
patterns. The build is deterministic: edges sorted, no timestamps beyond the build time.

**Neighbours.** Dependency edges at depth 1 in both directions, and conflict edges at or above 0.05 in
either direction. Both thresholds are parameters of `Graph.neighbours`; `graph neighbours` exposes the
conflict one. A mention edge is a dependency neighbour: it is the planner-mentions-doer case.

**Replay coverage.** With a graph, replay lists each neighbour with its edge kinds, its weight, and
the suite tasks whose expected route or expected agents name it. Their fallen tasks are already in the
regression list. A neighbour no task expects is listed as not covered, with a reason line. Coverage
alone does not change the recommendation, except for conflict neighbours of a description edit.

**Trigger-theft check.** `refine` records in `meta.json` whether the proposal changed the component's
`description` frontmatter. Older proposals fall back to reading the source when it still has the
proposal's `source_hash`. When the description changed and a graph exists:
- for each conflict neighbour, each task expecting it as primary route, each model: `route@1` under
  ROUTED in the baseline and in the candidate
- a drop beyond the tolerance is a theft regression and the recommendation is "do not accept"
- a conflict neighbour with no such task in the suite makes an "accept" into "none", because the
  check the change most needs cannot be made

Without a graph, a description edit gets a reason line saying the check was not made.

## Risks / Trade-offs

- [Prose-reference edges are noisy] → lower weight; evidence shown; bare names count only in
  backticks.
- [Conflict edges only exist where a confusion was observed] → a broadened description can take
  triggers from a component it was never confused with. Fallen tasks in the bank still show it when
  they have verifiers; routing-only tasks outside the conflict neighbours do not. Rebuild the graph
  after each eval.
- [A stale graph] → the build records the runs it read; `graph show` prints them.

## Open Questions

- Should conflict edges also come from passive logs, for example a user correction that re-invokes a
  different skill?
- Should `route@1` regressions be checked on every routing task, not just conflict neighbours', once
  suites are large enough that the noise floor allows it?
