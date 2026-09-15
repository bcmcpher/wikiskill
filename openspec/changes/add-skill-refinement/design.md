## Context

WikiSkill's Proposer is a ReAct agent that starts from the wiki index and the skill-impact history. It
must read at least four raw traces and submits one atomic proposal: create a skill, patch one, or do
nothing. The harness scores the result on validation and keeps it only if the score strictly beats the
best so far; otherwise skills roll back and the wiki stays. One unofficial implementation only asks
for the four-trace minimum in prompt text; the other enforces it through its tool server. We enforce
it.

Two things differ for wikiskill. Collections are real repositories users own, so nothing is applied
silently. Components serve many models: a patch that helps the model that failed may hurt another. So
evidence and replay must be cross-model. The study of personalised skills (arXiv 2608.10319) found
generic pooled skills beat per-user ones under limited data, which argues for general edits by
default.

## Goals / Non-Goals

**Goals:**
- One reviewable, evidence-grounded change per proposal.
- Machine-enforced proposer discipline, not prompt-only.
- A gate decision the user makes with replay evidence in front of them.

**Non-Goals:**
- **Automatic acceptance** — never in this change.
- **Multi-component proposals** — graph-aware joint proposals are left open (`add-collection-graph` only widens
  replay).
- **Description-only trigger tuning** — needs routing metrics from `add-explicit-eval` and conflict edges from
  `add-collection-graph`.

## Decisions

**Proposer inputs.** The wiki index, pattern pages for the target component, `components/<name>.md`,
the component's `skill-impact.md` history including rejected proposals in full, and an outcome summary
of sampled sessions. It reads digests through a read-only tool scoped to the digest directory.

**Enforced reads.** wikiskill's own agents are always logged under the internal `_wikiskill`
collection. After the proposer finishes, `wikiskill propose check` counts distinct digest reads in
that session's raw log. The default minimum is four, as in the paper, lowered to the number available
when fewer exist. A proposal claiming reads that aren't in the log is rejected.

**Contract.**
`{action: create|patch|no_action, component: {kind, name}, rationale, patterns_addressed: [...], read_digest_ids: [...], create?: {files: {...}}, patch?: {edits: [{file, op: append|replace|insert_after, anchor?, text}]}}`.
Anchors must occur exactly once. Edits may only touch files belonging to the target component.

**Leakage ban.** Proposal text is rejected if it contains:
- task ids from any suite
- expected output values recorded in task suites
- rubric anchor text
- verbatim user note text longer than 200 characters

This is a string check plus a normalised n-gram overlap check.

**Pooled first.** Model-specific guidance (for example, a section only for small models) is allowed
only when the addressed patterns are scoped to those models with at least three evidence items. The
proposal must mark it as such.

**Delivery.** `wiki/proposals/<id>/` holds `proposal.json`, `patch.diff`, the rendered new files, and
a summary. `wikiskill refine apply <id> --branch` creates `wikiskill/<component>/<id>` in the source
repository; otherwise the user applies the diff themselves.

**Gate.**
- **States:** `proposed → replayed → accepted | rejected | withdrawn`.
- **Replay (via `add-explicit-eval`):**
  - Runs two sets under baseline (current `source_hash`) and candidate, k repeats, across every
    target model in the manifest:
    - *motivating cases*: evidence sessions converted to tasks — first user prompt plus fixtures
      where reproducible
    - the component's *regression bank*: previously successful sessions and eval tasks
  - Cases whose state can't be reproduced are marked non-replayable with the reason.
- **Report:** per model, motivating-case delta and each regression listed individually, never only
  an average.
- **Recommendation:** "accept" only if motivating cases improve on at least one model and no
  regression exceeds the tolerance on any model. It is a recommendation; the user decides.
- **Record:** `skill-impact.md` gets decision, reviewer note, diff, evidence ids, and replay summary;
  rejected proposals keep full content, per the paper's appendix.

## Risks / Trade-offs

- [Overfitting to one user or one model] → pooled-first rule; replay across all configured models.
- [Live sessions rarely replayable] → explicit non-replayable marking; eval suites become the main
  regression bank.
- [Weak proposer produces noise] → `no_action` is a valid, common outcome; contract validation with
  bounded retries as in `add-experience-wiki`.
- [Human review becomes a bottleneck] → `wikiskill refine list` shows pending proposals with replay
  summaries.
- [Leakage check false positives on short common phrases] → n-gram threshold; ban message names the
  match so the user can override with `--allow-overlap`.

## Open Questions

- Should neutral proposals that simplify a skill without changing scores be recommendable? The paper's
  strict gate rejects them, which it lists as a limitation.
- What regression tolerance is sensible for k=3 repeats on small suites?
