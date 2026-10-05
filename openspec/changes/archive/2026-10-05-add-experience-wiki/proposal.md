## Why

Raw logs are too long and noisy for a model to reason over directly, and weak local models least of
all. WikiSkill's central finding is that a persistent wiki of distilled patterns, maintained
separately from the skills, drives most of the improvement; in its ablation, running the loop with no
wiki access for either agent loses most of the gain.

`add-minimal-loop` built that wiki once, for one component, from everything it had ever done:
- a validated create/update/index/log contract
- a git-versioned wiki
- scope computed from evidence
- `wikiskill review`, run headless against the maintainer role

That is enough for one pilot unit. It is not enough once real use accumulates. Every review starts
again from all the evidence, so the same sessions are shown repeatedly and new ones are crowded out.
Corrections, which `add-correction-capture` now records, carry no more weight than a clean session.
The budget is fixed whatever the maintainer's context. This change makes review incremental and
signal-led, and adds the in-harness path.

## What Changes

- **Signal-led sampling.** Evidence is ranked: explicit note, then output edit, then repeat
  activation, then failure (an eval verifier failure, a tool error or step exhaustion), then follow-up
  turn, and clean sessions last. It is capped at a configurable count of signal and clean items. A
  live session's digest shows its signals: the note, the follow-up text, the edit's diff.
- **A watermark.** `.watermark.json` in the wiki records which evidence each component has been
  reviewed on. Review samples only what is new, unless `--resample` is given. A second review with
  nothing new reports so and commits nothing.
- **A budget from the maintainer's context.** An optional `context_tokens` on a role scales the
  digest budget down below 64k tokens.
- **Persisted samples.** `wikiskill sample <component>` writes the prompt and its evidence map to a
  sample directory. `wikiskill review --sample <id> --reply-file` applies a reply written elsewhere
  against exactly that sample.
- **`/wikiskill-review` in the harness.** The command samples, delegates to the `wikiskill-maintainer`
  subagent, and hands its reply to `wikiskill review --sample`. Both paths are validated and applied
  by the same Python.
- **Component pages.** `components/<name>.md` lists a component's patterns, the versions they were
  observed on, and its review history.
- **Contract additions.**
  - An optional `universal` claim, rejected unless the evidence spans two models or two harnesses.
  - `status: superseded` on an update.
  - Two more causes: `routing_miss` and `user_preference`.
- **A failed review leaves a trace.** When retries are exhausted, the failure is appended to
  `log.md` and committed. Patterns, index and watermark are left unchanged.

## Capabilities

### Modified Capabilities

- `experience-wiki`: incremental, signal-led sampling within a context-derived budget; the
  watermark; persisted samples and the in-harness command; component pages; universality and
  superseding; failures recorded in the log.
- `collection-config`: a role may state its model's context, in tokens.

## Impact

- Depends on `add-trace-logging`, `add-minimal-loop` and `add-correction-capture`, all archived.
- `add-skill-refinement` reads the wiki and its component pages.
- Extends `src/wikiskill/{review,wiki,collection,cli}.py`, `schemas/maintainer-output.schema.json`
  and `harness/source/agents/wikiskill-maintainer.md`.
- Adds `harness/source/commands/wikiskill-review.md`.
- No new module for the contract: `add-minimal-loop` put it in `wiki.py`.
