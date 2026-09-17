# Roadmap

Implementation order for the OpenSpec changes in [`openspec/changes/`](openspec/changes/). Change ids
carry no order; this file is the single source for sequencing. Design background:
[`docs/design/architecture.md`](docs/design/architecture.md).

## Ordering principles

1. **Measure before learning.** A refinement loop tuned against unmeasured behaviour overfits to noise, so
   the controlled evaluation path comes before the wiki and proposer.
2. **Real trajectories early.** Explicit eval produces trajectories on demand, which tests the raw
   schema against real OpenCode output long before passive logs have accumulated.
3. **Start capture early; data accrues with time.** Correction and Claude Code logging go in before the
   wiki, so the maintainer has real sessions to read when it arrives.
4. **Collection awareness last.** The relation graph needs routing confusions (from evals) and co-usage
   (from logs) to contain anything, and it extends a gate that must already exist.

## Sequence

Step 1 is **done**: implemented, archived under
[`openspec/changes/archive/`](openspec/changes/archive/), and its three capabilities are live in
[`openspec/specs/`](openspec/specs/).

`add-logging-safeguards` is also done and archived. It is not a step: it is a post-hoc amendment to
two of step 1's capabilities, recording three behaviours that a review of the implementation added
after step 1 was archived. It reorders nothing below and blocks nothing.

| # | Change | Capabilities | Hard dependencies | Why here |
|---|---|---|---|---|
| 1 ✅ | `add-trace-logging` | collection-config, trace-log, harness-packaging | — | Schema, manifest, and packaging underpin everything. |
| 2 | `add-explicit-eval` | task-suite, eval-runner, eval-scoring | 1 | Controlled measurement; real trajectories; the replay engine the gate needs. |
| 3 | `add-dsh-pilot` (Phase 1) | dsh-pilot | 2 | First real results, and an early stress test of preflight and open-model tool calling. |
| 4 | `add-correction-capture` | correction-signal | 1 | Starts accumulating the strongest learning signal from real use. |
| 5 | `add-claude-code-adapter` | claude-code-adapter (+ harness-packaging, correction-signal, eval-runner) | 1, 2, 4 | Captures sessions where most development happens; adds the harness axis. |
| 6 | `add-experience-wiki` | experience-wiki | 1, 4 | Distils sessions and eval failures that have accumulated since steps 2–5. |
| 7 | `add-skill-refinement` | refinement-proposal, refinement-gate | 2, 6 | Proposals grounded in the wiki, with replay available from the start. |
| 8 | `add-collection-graph` | collection-graph | 1, 2, 7 | Needs confusion and co-usage data; widens the existing gate. |

## Phases and milestones

### A — Foundation and measurement (1–3)

- **Milestone A:** OpenCode logs validate against the raw schema. A data-science-harness routing report
  exists per open model under OFF and ROUTED — or states which models failed preflight and why.
- The pilot's passive-use tasks (its group 4) wait for Milestone C; Phase 2 stays deferred.

**Milestone A progress.** The schema half holds: logs written by the OpenCode logger validate against
`schemas/raw-event.schema.json` with zero errors, checked both from the plugin's own mapper and from
the installed artifact driven with payloads captured from a real OpenCode 1.18.31 session. Not yet
shown: a live OpenCode-driven session producing those logs, because **no locally reachable endpoint
completes a tool call** — one model rejects tools outright, the others produce nothing within the
default context on a CPU-only machine (see the archived change's task 5.3 for the four attempts). That
is the first concrete evidence for the preflight check `add-explicit-eval` introduces, and it is what
the routing report will have to state per model.

### B — Signals in both harnesses (4–5)

- **Milestone B:** follow-ups, output edits, and notes are logged from real OpenCode and Claude Code
  sessions. A three-task suite runs on one open model under both harnesses.
- The pilot gains its Claude Code arm here.

### C — Learning loop (6–7)

- **Milestone C:** `/wikiskill-review` produces validated, scoped patterns from real logs. Then
  `/wikiskill-refine` delivers one data-science-harness patch with cross-model replay, decided by a
  human and recorded in `skill-impact.md`.
- Resume the pilot's passive-use tasks.

### D — Collection awareness (8)

- **Milestone D:** description edits are checked against conflict neighbours, and replay includes graph
  neighbours.

## Parallel work

With more than one person working:
- `add-correction-capture` (4) can start alongside `add-explicit-eval` (2) as soon as 1 lands.
- `add-claude-code-adapter` (5) can split: its plugin build and hooks logger need only 1 and 4; its eval
  backend waits for 2.

The table above is the single-track order.

## Carried forward

- **data-science-harness pilot Phase 2** (provenance and reproducibility): needs a sandbox with fake
  credentials, local siblings, and a synthetic BIDS dataset. Schedule it after Milestone C.
- **Open questions** tracked in the changes' `design.md` files:
  - neutral-proposal acceptance
  - wiki pruning
  - `opencode serve` backend
  - simulated multi-turn users
  - Ollama's Anthropic API compatibility
