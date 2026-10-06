## How wikiskill works

- **Log** what skills and subagents do, and what users correct
- **Evaluate** task suites in fresh, isolated sessions, over models × conditions × repeats
- **Review** one component's evidence into wiki patterns
- **Refine** one patch to one component; wikiskill never applies it
- **Gate** the patch on every model; the user alone decides

::: notes
The loop is log, evaluate, review, refine, gate. Every run keeps run.json and results.jsonl, which
is everything the tables in this deck are made from.
:::

## Three conditions

| condition | what the model has | measures |
|---|---|---|
| OFF | no collection | the bare model |
| ROUTED | the collection, found on its own | content and routing |
| INJECTED | the component's text in context | content alone |

::: notes
Comparing the three separates what a component's text does from whether a model reaches for it.
INJECTED against OFF is the component's content value; INJECTED against ROUTED is its routing loss.
:::

## Scoring and statistics

- **Verifier-first:** a unit passes only when every deterministic check passes
- Units that did not run are reported, never counted
- Rates: `passed/total (rate, low-high)`, Wilson 95% interval
- *Up* or *down* only when intervals do not overlap
- A judge grades rubric dimensions only. It is never a model under test and never sees the route

::: notes
Wilson intervals stay honest at small n and at 0% or 100%. Overlapping intervals are reported as no
detectable difference rather than as a ranking.
:::

## Choosing the best version

- **Lift** = version − OFF; OFF is shared across versions
- **Best per model:** highest rate, not disqualified, not a regression
- **Best overall:** highest mean over the models every version ran on
- **Regression:** down on any model, or a task falling by over a third
- **Critical checks** (e.g. no invented DOI) disqualify on one failure

::: notes
A version that regresses any model is never named best overall. Versions are also paired over
(model, task) cells with an exact sign test. The board ranks; the gate and the user decide.
:::

## The gate

- Candidate evaluated from a copy of the source
- Replay against the baseline on **every** model
- Every fallen task listed, never averaged away
- Accepted only by the user, and recorded

::: notes
Replay recommends acceptance only when motivating cases improved somewhere and no task fell beyond
tolerance anywhere.
:::
