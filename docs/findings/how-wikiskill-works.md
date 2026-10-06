### The loop

wikiskill measures what agent skills and subagents do for a model, and keeps the evidence needed to
improve them. One loop runs from logging to a decision:

1. **Log.** Every session in a watched collection is logged as raw events: which component was
   activated, what it delegated to, and what the user had to correct. Logging makes no model calls,
   and a logging failure never stops the session.
2. **Evaluate.** A task suite runs each task in fresh, isolated, headless sessions, over a matrix of
   models, conditions and repeats. Each run keeps a `run.json` (what ran, with every component's
   source hash, the models' served contexts and the run options) and a `results.jsonl` (one line
   per unit).
3. **Review.** A maintainer model distils one component's evidence, failed units and corrected
   sessions first, into pattern pages in a persistent wiki.
4. **Refine.** A proposer model writes one patch to one component, grounded in those patterns.
   wikiskill never applies it.
5. **Gate.** The patched text is evaluated from a copy of the source, replayed against the baseline
   on every model, and accepted or rejected by the user alone. Every decision is recorded.

### Conditions

Every task can run under three conditions. Comparing them separates a component's content from
whether a model finds it:

- **OFF:** the model works without the collection: the bare model.
- **ROUTED:** the collection is installed and the model must discover and choose the component
  itself.
- **INJECTED:** the component's text is put into context, and loading it is denied, or the agent is
  invoked directly. This measures the content alone.

INJECTED against OFF is the component's *content value*. INJECTED against ROUTED is its *routing
loss*: what is lost because the model does not reach for it.

### Scoring

Scoring is verifier-first. A task declares deterministic verifiers: commands, file checks and
patterns run in the work directory the session left. A unit passes only when every verifier passes.
A task with no verifiers counts on its route, whether the expected component was the first one
activated, and only under ROUTED. A unit that did not run (`infra_error`, `skipped`) is reported
beside the rate and never counted in it. A model that fails the endpoint preflight runs no units,
and the reason is stated.

A model judge is used only for rubric dimensions, never for pass or fail. It is never a model under
test, and it never sees the expected route. Several judges can form a panel. Each opinion records
the judge's model, and a judge from the same family as the judged model is marked.

### Statistics

- **Rates** print as `passed/total (rate, low-high)`, with a Wilson 95% interval. Wilson intervals
  stay honest at small *n* and at 0% or 100%.
- **Direction.** Two rates are *up* or *down* only when their intervals do not overlap. Otherwise
  there is "no detectable difference", and the table says so rather than ranking noise.
- **Pooling.** Runs of one suite pool across machines and days per model and condition. Runs whose
  suite or component versions differ are refused. A model's thinking settings are separate entrants
  and never pooled together.
- **Ranking.** A model whose interval overlaps the leader's is marked `≈`: its place is not a
  finding.

### Comparing versions of a component

The **version board** ranks several versions of one component across models:

- OFF is shared across versions, since it does not load the component, and each version's *lift* is
  its rate less OFF's.
- The best version per model is the highest rate that is neither disqualified nor a regression.
- The best version overall is the highest mean over a *panel*, the models every version ran on.
  Each model is weighted equally, and versions are paired over (model, task) cells with an exact
  sign test.
- A **regression** is a version that falls on any model: its rate is *down*, or one task falls by
  more than the gate's tolerance (a third). A version that regresses any model is never named best
  overall.
- **Critical checks** name verifiers that must never fail, such as "never invent a DOI". A version
  that fails one even once is disqualified. Failures under OFF are listed too, as what the bare
  model does, and disqualify nothing.

### The gate

A proposal is accepted only by the user. `proposal replay` compares a candidate run with the
baseline on every model:
- the *motivating cases*, the tasks behind the evidence
- the *regression bank*, every other task
- every task that fell, listed individually, never folded into an average

It recommends acceptance only when a motivating case improved on some model and no task on any model
fell beyond the tolerance. Description edits are also checked for *trigger theft* from neighbouring
components.

### What a study keeps

A study keeps its runs' `run.json` and `results.jsonl` in the repository, without transcripts.
Every table, data file and figure is regenerated from them, so each number in a report can be
traced to the runs that produced it.
