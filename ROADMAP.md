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
5. **End to end before depth.** The whole loop has to run once, on one unit, before any stage of it is
   deepened:
   - scope a unit
   - evaluate it
   - review what was observed
   - propose one patch
   - the user applies it
   - re-evaluate and compare

   Evaluation is deliberate and scoped to one plugin or one subagent. Refinement is started by the
   user and tied to a component version, never iterated silently. The target findings are per-model
   comparisons of skill versions, reported with intervals.

## Sequence

Step 1 is **done**: implemented, archived under
[`openspec/changes/archive/`](openspec/changes/archive/), and its three capabilities are live in
[`openspec/specs/`](openspec/specs/).

Step 3 is **closed**: archived on 2026-10-05 with its three capabilities live. The loop is built
and review and refine ran live on `datalad/datalad-doer`, but DSH deleted that unit upstream before
its v1-against-v2 comparison, so that comparison moved to step 4's first per-unit pilot.

Step 4 has its first unit through the loop, and the change stays open for its passive-use tasks.
- `archive/archive-doer` ran on two local open models with OFF as the control. Its instructions
  lifted the pass rate from 44–50% to 89–100%, with non-overlapping intervals. No reply on either
  model invented a DOI.
- The local proposer's patch was tested as a candidate run, replayed and rejected: it restated a
  readiness-script path that does not resolve outside a DSH checkout, which is the doer's real
  defect.
- The pilot fixed two wikiskill bugs. Review let OFF units crowd out the component's own. The
  proposer's prompt dropped cited eval evidence.
- The report is `docs/pilots/dsh/report.md` on the `results/dsh-pilot` branch, with the runs and
  tables behind it. The routing probe, passive use and Phase 2 stay deferred.

Step 7 is **done**: archived on 2026-10-05, built on step 3's wiki rather than beside it. Review
now samples by signal, with explicit notes first and clean evidence last, each up to a quota. A
watermark shows each review only what is new. The prompt budget follows the maintainer's context.
`/wikiskill-review` runs the maintainer subagent in the harness against a persisted sample, and
wikiskill validates and applies its answer. Its live check ran on a local maintainer, which turned
a logged correction into a pattern.

Step 8 is **done**: archived on 2026-10-05, built on step 3's `refine` and `compare` rather than
beside them.
- The proposer is shown the evidence behind its patterns and the component's earlier decisions. A
  patch must cite enough of that evidence and only that evidence, and must name one component.
- The text a patch adds is checked for evaluation content (task ids, verifier literals, rubric
  anchors, long notes) and for unmarked model-specific guidance.
- `wikiskill eval --proposal` runs a candidate from a copy of the source.
- `wikiskill proposal replay` reports each model's motivating cases and every task that fell, and
  recommends.
- Only `wikiskill proposal decide` reaches a final state, and every decision lands in
  `skill-impact.md`.

Its live check ran the whole gate on `wikiskill-trace` without touching the source. A replay with a
motivating eval task waits on a pattern drawn from a verifier suite, which step 4's pilot provides.

Step 9 is **done**: archived on 2026-10-05, rebased onto step 8's gate before it was built.
- `wikiskill graph build` writes `graph.json` to the wiki. Dependency edges come from `delegates_to`
  (a plugin name stands for its agents) and from component names in bodies. Conflict edges come from
  routing confusions in eval runs, per model. Candidate runs are left out.
- Replay runs nothing extra. With a graph, it names each neighbour and the suite tasks that expect
  it, and lists neighbours the suite does not cover.
- A description edit gets a trigger-theft check: conflict neighbours' `route@1`, per model. A
  conflict neighbour the suite cannot route keeps the recommendation from "accept".
- Co-usage edges are deferred: no live session on hand has activated two components.

Built read-only on this machine's runs, the graph finds a real near-miss pair in `my-skills`,
`analysis-plan` and `analysis-refactor`, confused in opposite directions by two models. Against the
real data-science-harness it finds `disseminate/dataset-release -> archive/archive-doer`.

Steps 5 and 6 are **done**: both archived on 2026-10-05 with their capabilities live.
- Step 5 captures corrections. Its last check ran live in OpenCode: a watched skill, a correction
  reply and `/wikiskill-note` logged `user_turn` (high) and `note` (explicit).
- Step 6 adds Claude Code as a second harness:
  - the plugin build and hooks logger;
  - `wikiskill eval --harness claude-code`, with open models served through an Anthropic-compatible
    endpoint;
  - a harness axis, so a leaderboard pools runs from both harnesses as separate entrants and sets
    the same model's harnesses side by side.

Step 2 is **done**: implemented, archived under
[`openspec/changes/archive/`](openspec/changes/archive/), and its three capabilities are live in
[`openspec/specs/`](openspec/specs/). The task-suite format and `wikiskill suite check`; the
OpenCode backend with per-run isolation and endpoint preflight; OFF, ROUTED and INJECTED; route
metrics, deterministic verifiers and the rubric judge; the full outcome taxonomy with step and time
budgets; the derived measures; `/wikiskill-eval`; and the data-science-harness adapter.

A defect found on 2026-09-21 is worth carrying forward as a habit rather than a note: the evaluation
guard had never run in any evaluation. OpenCode calls every export of a plugin module as a plugin
factory, so exporting an error class alongside the factory made the whole plugin fail to load, in
one ERROR line, while runs carried on unguarded. Its unit tests passed the whole time because they
tested pure functions and never the contract with the loader. Anything wikiskill hands to a harness
needs at least one test that exercises the harness's own entry point.

Two more of the same shape turned up the same day, both while checking INJECTED against a live run
rather than against a fixture: `opencode export` exits without draining a pipe, so every session
over 64 KiB was silently discarded and its unit scored as having activated nothing; and a tool call
the harness refused was counted as an activation, which gave INJECTED a perfect `route@1` for a
route it forbids by construction. Neither was visible from the recorded fixtures, because every
recorded session was short and nothing in them had been refused.

`add-logging-safeguards` is also done and archived. It is not a step: it is a post-hoc amendment to
two of step 1's capabilities, recording three behaviours that a review of the implementation added
after step 1 was archived. It reorders nothing below and blocks nothing.

| # | Change | Capabilities | Hard dependencies | Why here |
|---|---|---|---|---|
| 1 ✅ | `add-trace-logging` | collection-config, trace-log, harness-packaging | — | Schema, manifest, and packaging underpin everything. |
| 2 ✅ | `add-explicit-eval` | task-suite, eval-runner, eval-scoring (+ trace-log) | 1 | Controlled measurement; real trajectories; the replay engine the gate needs. |
| 3 ✅ | `add-minimal-loop` | experience-wiki, refinement-proposal, version-comparison (+ collection-config, harness-packaging, eval-runner) | 1, 2 | The whole loop once, on one unit (`datalad-doer`), with a light gate: a human decision informed by a v1-vs-v2 comparison with intervals. |
| 4 | pilots on a real collection | — | 3 | Per-unit pilots on the loop, each kept with its suites and results on a `results/<study>` branch, not on `main`. First unit done; passive use waits for Milestone C. |
| 5 ✅ | `add-correction-capture` | correction-signal | 1 | Starts accumulating the strongest learning signal from real use. |
| 6 ✅ | `add-claude-code-adapter` | claude-code-adapter (+ harness-packaging, correction-signal, eval-runner) | 1, 2, 5 | Captures sessions where most development happens; adds the harness axis. |
| 7 ✅ | `add-experience-wiki` | experience-wiki | 3, 5 | Extends step 3's minimal wiki with sampling at scale, digests and a watermark. |
| 8 ✅ | `add-skill-refinement` | refinement-proposal, refinement-gate (+ version-comparison) | 3, 7 | Extends step 3's proposals with gate states and cross-model replay. |
| 9 ✅ | `add-collection-graph` | collection-graph (+ refinement-gate) | 1, 2, 8 | Dependency and conflict edges; replay names neighbours and checks description edits for trigger theft. Co-usage deferred. |

Steps 7 and 8 were rebased onto step 3's capabilities before they were built (`add-minimal-loop`
task 7.1). Step 9 extends step 8's gate the same way.

## Phases and milestones

### A — Foundation, measurement and a first loop (1–4)

- **Milestone A:** OpenCode logs validate against the raw schema. One unit (first `datalad/datalad-doer`,
  now step 4's first pilot unit after that one was retired upstream) has been through the whole loop once, with every step started by the user:
  1. evaluated
  2. reviewed into wiki patterns
  3. patched
  4. re-evaluated
  5. compared, with a `skill-impact.md` entry recording the decision

  The comparison states pass rates with intervals per model, and states which models failed
  preflight and why.
- Per-unit pilots follow (step 4), each on its own results branch. Their passive-use tasks wait for
  Milestone C, and provenance and reproducibility probes stay deferred.

**Milestone A progress.** The schema half holds: logs written by the OpenCode logger validate against
`schemas/raw-event.schema.json` with zero errors, checked both from the plugin's own mapper and from
the installed artifact driven with payloads captured from a real OpenCode 1.18.31 session. Not yet
shown: a live OpenCode-driven session producing those logs, because **no locally reachable endpoint
completes a tool call** — one model rejects tools outright, the others produce nothing within the
default context on a CPU-only machine (see the archived change's task 5.3 for the four attempts). That
is the first concrete evidence for the preflight check `add-explicit-eval` introduces, and it is what
the routing report will have to state per model.

That preflight now exists and says so. Run against the local Ollama endpoint on 2026-09-18,
`ollama/qwen2.5-coder:1.5b` was refused on two counts — it answers a tool-call probe with text, and
it is served with Ollama's 4096-token default against a 16k minimum — so a three-task suite under OFF
and ROUTED skipped all six units and reported both reasons rather than recording six zeroes.

A usable endpoint has since been found, and finding it corrected the preflight. `opencode/big-pickle`
is served by OpenCode's own free tier, which refuses a direct HTTP request
(`FreeTierError: OpenCode's free tier can only be used from within OpenCode`) while working perfectly
through `opencode run` — so the original probe would have rejected a model the runner can drive. The
probe now takes whichever path the units will take, and on 2026-09-18 that model passed: a real
`write` tool call and a 200000-token context, at no cost and with no API key.

Verifiers (task 4.2) landed on 2026-09-21, and with them the first pass/fail number: the toy suite's
verifier-only task scored 0% on `opencode/big-pickle` under both OFF and ROUTED, with the report
naming the check that failed (`/count/ not found in the final text`) and classifying the unit
`completed` rather than broken. Every report row now says whether its pass rate came from a verifier,
from `route@1`, or from nothing at all, so the two are never compared by accident. What the routing
report still wants is the data-science-harness suite itself (task 1.3) and the pilot (step 4) — not
hardware, and no longer scoring. Step 3 comes first: the loop on one unit.

**Milestone A is met** (2026-10-05). `archive/archive-doer` went through the whole loop, every step
started by hand:
- evaluated (`01M46QWP6CTEM5DN807VS7GQMW`)
- reviewed into a pattern
- patched by the local proposer (`p-002`)
- re-evaluated as a candidate (`01M46VFM331Y2MXZ8DNPTY5R6J`)
- replayed against v1, with the rejection recorded in `skill-impact.md`

Both models passed preflight, and the comparison gives pass rates with intervals per model. The
loop worked, but its patterns and proposals were weak: the local maintainer misread the defect,
which the report describes.

### B — Signals in both harnesses (5–6)

- **Milestone B:** follow-ups, output edits, and notes are logged from real OpenCode and Claude Code
  sessions. A three-task suite runs on one open model under both harnesses.
- The pilot gains its Claude Code arm here.

**Milestone B met (2026-10-05)**, apart from the pilot's Claude Code arm, which has no task in
`add-dsh-pilot` (now on `results/dsh-pilot`) and moves there. Live sessions logged every signal in both harnesses:

- **OpenCode 1.18.34 on gemma4:**
  - Follow-ups and notes: `add-correction-capture` 4.3.
  - Output edits: session `ses_ef2a08120ffeeLv1O4tb29AHBZ` loaded `wikiskill-trace` and wrote a
    file. After a hand edit, `wikiskill corrections scan` logged one `output_edit` (`low`, with a
    diff). A second scan found nothing new.
- **Claude Code 2.1.289:**
  - Follow-ups and notes: `add-claude-code-adapter` implementation notes.
  - Output edits: the same check on gemma4 via Ollama's Messages API, session
    `abcc5e37-4bf4-4078-b7c9-9cd07a5786ee`.
- **Both harnesses:** toy-routing ran on gemma4 under each (`add-claude-code-adapter` 6.4).

### C — Learning loop at depth (7–8)

- **Milestone C:** `/wikiskill-review` produces validated, scoped patterns from sampled real logs. Then
  `/wikiskill-refine` delivers one patch to a real collection with cross-model replay, decided by a
  human and recorded in `skill-impact.md`.
- Resume the pilot's passive-use tasks.

### D — Collection awareness (9)

- **Milestone D:** description edits are checked against conflict neighbours, and replay includes graph
  neighbours.

## Parallel work

With more than one person working:
- `add-correction-capture` (5) can start alongside `add-explicit-eval` (2) as soon as 1 lands.
- `add-claude-code-adapter` (6) can split: its plugin build and hooks logger need only 1 and 5; its eval
  backend waits for 2.

The table above is the single-track order.

## Carried forward

- **Provenance and reproducibility probes**: need a sandbox with fake credentials and local
  siblings. Schedule them after Milestone C.
- **Open questions** tracked in the changes' `design.md` files:
  - neutral-proposal acceptance
  - wiki pruning
  - `opencode serve` backend
  - simulated multi-turn users
  - Ollama's Anthropic API compatibility
