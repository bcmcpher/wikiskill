---
title: "data-science-harness pilot"
subtitle: "Evaluating and refining DSH components on open models with wikiskill"
---

## The pilot

- Runs data-science-harness (DSH) components through wikiskill's loop on open models, one unit at
  a time
- Reports in the terms of DSH's evaluation protocol: a named control, results per model, and
  every unrun probe stated
- Nothing in the DSH repository is written; proposals run from a copy of the source

::: notes
Every number in this deck is generated from the runs bundled with the study (docs/pilots/dsh/runs),
so it can be regenerated and checked from the repository.
:::

<!-- include: ../../findings/how-wikiskill-works.slides.md -->

## Setup

- DSH commit `c6f6079` (`main`), clean before and after
- OpenCode 1.18.34; Ollama 0.34.2 on a GB10
- Models: `gemma4:latest` (128k context), `qwen3:30b-a3b` (256k); both passed preflight
- Thinking at each model's default; 8192 output tokens per turn
- Maintainer and proposer: `qwen3:30b-a3b`, which only reads evidence and is never scored

## Unit 1: `archive/archive-doer`

- The doer's central rule: **never fabricate a DOI**
- 6 tasks × 3 repeats; every credential empty, every archive host refused
- Any DOI in a reply is invented, and every task checks that none appears
- Control: **OFF**, the same prompt without the doer; **INJECTED** runs the doer directly

::: notes
The other rules each leave something checkable offline: no tag invented or moved, no commit, and a
structured unminted or ledger-only result.
:::

## v1: pass rates

<!-- include: tables/pilot.slim.md -->

::: notes
INJECTED beats OFF with non-overlapping intervals on both models. Across all 144 units of both runs
no reply contained a DOI, and no run created or moved a tag.
:::

## v1: pass rates per model

![](figures/pilot-rates.png)

## What the transcripts showed

- The doer ran the readiness check in 30 of 36 INJECTED units
- In 30 of them it failed: `No such file or directory`
- The doer names `archive-cli` by repository-relative paths, which resolve only inside a DSH checkout
- Both models then reported `unminted` without naming the missing credential

## Versions: best per model

<!-- include: tables/archive-doer-versions.slim.md -->

::: notes
p-002 adds "Use EXACTLY the path specified in the backend skill". OFF pools across both runs, n = 36
per model, and lift is a version's rate less OFF's.
:::

## Versions: overall

<!-- include: tables/archive-doer-versions.overall.slim.md -->

::: notes
p-002 lost one cell, mint-without-token on gemma4 under INJECTED, within the tolerance. It regresses
no model, but it improves none either.
:::

## Lift over OFF

![](figures/archive-doer-versions-lift.png)

## Review, proposal and decision

- **Review** wrote the pattern `archive-doer-ignores-skill-path`, which misreads the cause
- **p-001** was withdrawn: the evidence was not shown to the proposer, which is now fixed
- **p-002** was evaluated as a candidate from a copy of the source
- **Replay: do not accept.** The motivating task was already 3/3; nothing improved
- **Decision: rejected**, recorded in `skill-impact.md`

::: notes
This is the first unit through the whole loop: evaluated, reviewed, proposed, re-evaluated as a
candidate, replayed and decided.
:::

## Model sweep

**Pending** (`add-dsh-pilot` section 4)

- About twenty local models, OFF and INJECTED, 10 repeats per task
- Per-model rates grouped by family and ordered by size
- A thinking arm, and a run-to-run noise check

## Best version

**Pending** (`add-dsh-pilot` section 4b)

- Screening, finals and confirmation on the version board
- Critical checks: no DOI, tags unmoved, no commit
- The best version overall and per model, then the gate

## Routing probe

**Pending** (`add-dsh-pilot` section 5)

- `route@1`, `route@k` and `capability@k` per model under OFF and ROUTED
- `handoff@k` graded by a three-model judge panel that sees each delegation

## For the DSH maintainer

- No patch was accepted, so none is handed over
- Untested as a change: `archive-doer.md` names `archive-cli` by repository-relative paths
- Referring to it through `${CLAUDE_PLUGIN_ROOT}` would let the readiness check run anywhere
- Any such change should go through a candidate run first

## Not run

- Routing probe, and provenance and reproducibility probes
- Cost probe (its instrument is specific to Claude Code)
- Passive use; a remote endpoint; a Claude Code arm
