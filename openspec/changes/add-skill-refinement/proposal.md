## Why

The wiki says what goes wrong; nothing yet changes the skill. WikiSkill's proposer makes one atomic,
evidence-grounded edit per iteration, and a gate keeps it only if validation improves. Passive logs
have no validation split. Runs on open models are noisy, and a small validation set with a strict
"greater than" rule would accept luck. So the gate here is stricter and human-owned: proposals are
patches the user reviews, backed — once the eval runner exists — by replaying the cases that
motivated them and checking for regressions across every configured model.

## What Changes

- A `wikiskill-proposer` agent and `/wikiskill-refine <component>` command producing exactly one
  `create`, `patch`, or `no_action` proposal.
- Harness-side enforcement:
  - a minimum number of trace digests actually read, verified from the proposer's own logged session
  - a single target component
  - no evaluation content (task ids, expected outputs, rubric anchors) in proposals
  - pooled edits preferred over model-specific variants
- Proposals delivered as a patch plus rendered preview under `wiki/proposals/<id>/`. A source-repo
  branch only when asked.
- A gate with states `proposed → replayed → accepted | rejected | withdrawn`:
  - human decision required
  - per-model replay deltas and listed regressions
  - every outcome appended to `skill-impact.md`, rejected content kept in full

## Capabilities

### New Capabilities

- `refinement-proposal`: the proposer contract, its enforcement, and patch delivery.
- `refinement-gate`: the replay-backed, human-decided acceptance gate and its impact record.

## Impact

- **Depends on `add-experience-wiki`** for patterns, component pages, and the skill-impact file.
- Replay uses **`add-explicit-eval`**, which comes earlier on the roadmap. If it is not installed, the
  gate still works with replay recorded as unrun and the reason stated.
- Graph-neighbour replay arrives with `add-collection-graph`.
- wikiskill's own agents are logged under an internal `_wikiskill` collection so proposer trace reads
  can be verified from the raw log.
- New: `src/wikiskill/{propose,gate}.py`, `schemas/proposal.schema.json`,
  `harness/source/agents/wikiskill-proposer.md`, `harness/source/commands/wikiskill-refine.md`.
