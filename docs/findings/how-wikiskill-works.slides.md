## What wikiskill answers

- **Does a skill help?** The same task, with its text and without
- **Does the model find it?** Installed and found, against forced into context
- **Does a change help?** The old text against the new, on every model
- **Does it hold across models?** The same suite on each model in use

::: notes
Every result in this deck is one of these comparisons, made on counts of tasks that passed a fixed
set of checks. The next two slides define the words used for them.
:::

## Terms: what is evaluated

| term | what it means here |
|---|---|
| skill | a file of instructions a model loads when a task matches it |
| agent | a separate model session with its own instructions and tools |
| doer | DSH's name for an agent that carries out one kind of job |
| component | the one skill or agent being evaluated; its version is the hash of its text |
| collection | the components installed together, from one manifest |
| harness | the program that runs the model and its tools: OpenCode or Claude Code |

::: notes
A skill is a SKILL.md file; an agent is started by delegation and runs as a child session. The
model under test is the one doing the task. A judge model may grade, and it is never a model under
test.
:::

## Terms: what is run and counted

| term | what it means here |
|---|---|
| task | a prompt, a starting state, and the checks that decide a pass |
| unit | one task, run once, on one model, under one condition |
| run | every unit of one suite, on the chosen models and conditions |
| pass | every one of the task's checks held |
| not run | the harness or machine failed, not the model; left out of rates |
| pass rate | units passed, out of the units that ran |

::: notes
Each task runs several times (repeats), so a rate per model and condition counts every repeat of
every task. Not run covers infra_error (a crash, a timeout) and skipped (a missing program, a failed
preflight).
:::

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

## Terms: comparing two rates

| term | what it means here |
|---|---|
| cell | one model under one condition: its units and their rate |
| n | the units that ran in a cell; 18 per cell in most of this deck |
| 95% interval | the rates the counts are consistent with (Wilson) |
| separates | the two intervals do not overlap |
| overlap | no detectable difference: not the same as no effect |
| lift | a version's rate minus OFF's, for the same model |

::: notes
At n = 18 an interval is about 40 points wide in the middle of the scale, so only large differences
separate. A "thinking off" entrant is its own cell, never pooled with the model at its default.
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
