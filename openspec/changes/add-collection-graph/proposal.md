## Why

Refining one component of a collection can silently break another. A clearer description steals
triggers from its near-miss neighbour. A planner's tightened steps stop handing off to the doer that
depended on them. The globalized skill evolution work (GSE, arXiv 2608.06153) addresses this with a
typed relation graph and replay of affected neighbours before accepting an update. data-science-harness
makes the need concrete: planners delegate to doers, and toolbox descriptions overlap with planner
descriptions.

## What Changes

- A typed graph over a collection's components:
  - `dependency`, from `delegates_to` frontmatter and prose references
  - `co_usage`, from components activated together in logged or eval sessions
  - `conflict`, from routing confusions in eval reports
- `wikiskill graph build|show|neighbours <component>`, with the graph stored in the wiki.
- The refinement gate widens replay to a component's neighbours.
- Description changes are checked against conflict neighbours so they do not take triggers from them.

## Capabilities

### New Capabilities

- `collection-graph`: construction of the typed relation graph and its use to widen replay and guard
  against trigger theft.

## Impact

- **Depends on `add-trace-logging`** (co-usage from raw events) and **`add-explicit-eval`** (conflict
  edges from routing confusion matrices).
- Extends `add-skill-refinement`'s gate when present. Without it, the graph is still useful as a
  report.
- New: `src/wikiskill/graph.py`, `wiki/graph.json`.
