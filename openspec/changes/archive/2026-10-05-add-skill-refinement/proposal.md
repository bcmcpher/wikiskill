## Why

The wiki says what goes wrong, and `add-minimal-loop` made `wikiskill refine` turn it into one patch
the user applies by hand. That proposer is held only to citing a pattern. Nothing checks that it
looked at the evidence behind the pattern, that it kept evaluation content out of the skill, or that
it avoided a special case for one model. Its decision gate is one pooled comparison.

WikiSkill's proposer makes one atomic, evidence-grounded edit per iteration, and a gate keeps it only
if validation improves. Passive logs have no validation split. Runs on open models are noisy, and a
small validation set with a strict "greater than" rule would accept luck. So the gate here is
stricter and human-owned. Proposals stay patches the user reviews. They are backed by replaying the
cases that motivated them, with every regression listed, on every model the runs cover.

## What Changes

- `wikiskill refine` is extended rather than replaced:
  - the proposer is shown the digests of the evidence its patterns cite, and the component's earlier
    `skill-impact.md` entries
  - it must cite at least four evidence labels, or every label when fewer were shown
  - the reply names its single target component
  - `refine --prepare` persists the prompt for `/wikiskill-refine`, which runs the proposer subagent
    in the harness
- Machine checks before anything is written:
  - single component
  - only evidence that was shown
  - no evaluation content: task ids, verifier literals, rubric anchors, long note text
  - model-specific guidance only when marked and backed by scoped patterns with enough evidence
- Proposals keep `wiki/proposals/<id>/`, gaining `proposal.json` and `rendered/`.
- A new `wikiskill proposal list|show|apply [--branch]` group. `apply` writes nothing unless
  `--branch` is given.
- A gate with states `proposed → replayed → accepted | rejected | withdrawn`:
  - `wikiskill eval --proposal <id>` evaluates the candidate from a copy of the source, never the
    source itself
  - `wikiskill proposal replay <id> <baseline> <candidate>` reports, per model, the motivating
    delta and every regressed task, and gives a recommendation
  - `wikiskill proposal decide <id> accept|reject|withdraw --note` is the only way to a final state
  - every outcome is appended to `skill-impact.md`, rejected content in full
- `compare --record` goes through the same gate.

## Capabilities

### New Capabilities

- `refinement-gate`: replay of a proposal from a baseline and a candidate run, the human-decided
  acceptance gate, and its impact record.

### Modified Capabilities

- `refinement-proposal`: evidence shown and cited, the single-component, leakage and pooled-first
  checks, richer delivery, and the `proposal` commands.
- `version-comparison`: `--record` decides through the gate.

## Impact

- **Builds on `add-minimal-loop`** (`refine.py`, `compare.py`) and **`add-experience-wiki`**
  (digests and samples in `review.py`, patterns and `skill-impact.md` in `wiki.py`).
- Replay uses the eval runner from **`add-explicit-eval`**. It adds `--proposal` to `wikiskill
  eval`, and `proposal` to `run.json`.
- Graph-neighbour replay arrives with `add-collection-graph`.
- New: `src/wikiskill/gate.py`, `harness/source/commands/wikiskill-refine.md`. Changed:
  `refine.py`, `review.py`, `compare.py`, `cli.py`, `runner/run.py`,
  `harness/source/agents/wikiskill-proposer.md`.
