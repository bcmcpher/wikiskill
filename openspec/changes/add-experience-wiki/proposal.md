## Why

Raw logs are too long and noisy for a model to reason over directly, and weak local models least of
all. WikiSkill's central finding is that a persistent wiki of distilled patterns, maintained
separately from the skills, drives most of the improvement; in its ablation, running the loop with no
wiki access for either agent loses most of the gain. This change adds that layer: a maintainer agent that turns sampled raw
sessions — failures and corrections first — into pattern pages scoped to component, model and
harness, so later refinement works from lessons, not transcripts.

## What Changes

- `wikiskill sample` selects unprocessed sessions (corrections and failures ahead of successes) and
  renders compact trace digests sized to the maintainer model's context.
- A `wikiskill-maintainer` agent and `/wikiskill-review [component]` command, runnable in-harness or
  headless against the configured maintainer endpoint.
- A JSON output contract modelled on the paper's: create patterns, patch-update patterns, full index,
  required log entry. A validator re-prompts with errors a bounded number of times.
- Wiki layout under `<collection>/wiki/`: `index.md`, `patterns/*.md`, `components/*.md`, `log.md`,
  `skill-impact.md`, a watermark. Git-versioned, never rolled back.
- Pattern pages carry trigger, evidence, scope hint, cause tag, and model/harness scope.

## Capabilities

### New Capabilities

- `experience-wiki`: sampling, the maintainer contract and its validation, and the persistent wiki
  layout with scoped, evidence-backed patterns.

## Impact

- **Depends on `add-trace-logging`** (raw events) and **`add-correction-capture`** (signals to
  prioritise). It can start on `add-trace-logging` alone, sampling only errors and step exhaustion.
- `add-skill-refinement` reads the wiki; `add-explicit-eval` results feed it through the raw log.
- First meta-agent, so this change also exercises `wikiskill build` for agents (`add-trace-logging`, task 4.2).
- New: `src/wikiskill/{sample,digest,wiki,maintain}.py`, `schemas/maintainer-output.schema.json`,
  `harness/source/agents/wikiskill-maintainer.md`, `harness/source/commands/wikiskill-review.md`.
