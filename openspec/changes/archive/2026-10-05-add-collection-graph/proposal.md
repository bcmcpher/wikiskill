## Why

Refining one component of a collection can silently break another. A clearer description steals
triggers from its near-miss neighbour. A planner's tightened steps stop handing off to the doer that
depended on them. The globalized skill evolution work (GSE, arXiv 2608.06153) addresses this with a
typed relation graph and replay of affected neighbours before accepting an update. data-science-harness
makes the need concrete: planners delegate to doers, and toolbox descriptions overlap with planner
descriptions.

Step 8's gate replays a baseline and a candidate run of one suite. It already lists every task that
fell on every model, so a neighbour whose tasks are in that suite is covered. What it cannot say is
which tasks belong to a neighbour, whether the suite has any, and whether a description edit moved
another component's routing. The graph supplies the first; the gate does the rest.

## What Changes

- A typed graph over a collection's components, stored in the wiki as `graph.json`:
  - `dependency`, from `delegates_to` frontmatter and prose references
  - `conflict`, from routing confusions in eval runs, per model
  - `co_usage` is deferred: the raw logs on hand hold no session that activated two components
- `wikiskill graph build|show|neighbours <component>`.
- Replay names each neighbour of the proposal's component and the suite tasks that expect it, and
  warns about neighbours the suite does not cover. It does not choose or add runs: replay compares
  the two runs it is given.
- A proposal that edits a skill's `description` gets a trigger-theft check: `route@1` of each conflict
  neighbour's routing tasks, per model, baseline against candidate. A drop beyond tolerance is a
  regression, and a conflict neighbour with no routing task in the suite blocks an "accept"
  recommendation.

## Capabilities

### New Capabilities

- `collection-graph`: construction of the typed relation graph, its storage, and neighbour queries.

### Modified Capabilities

- `refinement-gate`: replay reports neighbour coverage, and description edits are checked for
  trigger theft.

## Impact

- **Depends on `add-explicit-eval`** (conflict edges from routing scores) and **`add-skill-refinement`**
  (the gate it extends). Without a graph, replay behaves as before and says so for description edits.
- New: `src/wikiskill/graph.py`, `wiki/graph.json`, `wikiskill graph`.
- Changed: `src/wikiskill/gate.py` (neighbours, theft check), `src/wikiskill/refine.py` (records
  whether a proposal changed the description).
