## Context

In WikiSkill the Wiki Maintainer runs once per iteration. It reads up to eight sampled traces (at most
five failing, three passing, each capped at 15,000 characters) and returns a JSON edit to the wiki.
The Skill Proposer then reads the wiki index, not raw traces first. The two unofficial implementations
diverged here: one runs a multi-turn agent that edits files freely; the other, in its paper-aligned
path, enforces the exact JSON contract. We take the contract, because it is validatable — which matters
far more with local models.

Our inputs differ from the paper's: live sessions have no ground-truth score, and they carry
correction signals the paper never had. Sessions span several models and two harnesses, so a lesson
learned on one small model must not be presented as universal.

## Goals / Non-Goals

**Goals:**
- A wiki that accumulates across reviews and survives every rejected refinement.
- Maintainer output that is machine-checked before anything is written.
- Patterns that say which component, models, and harnesses they apply to, with evidence ids.

**Non-Goals:**
- **Editing skills** — `add-skill-refinement`.
- **Pruning or merging old patterns** automatically (a stated limitation of the paper); patterns can be
  marked `superseded` by the maintainer.
- **Choosing a maintainer model** — configured per collection.

## Decisions

**Wiki layout.**

```
<collection>/wiki/            (its own git repo)
  index.md                    one line per pattern: component · problem · root cause · fix · scope
  patterns/<slug>.md          frontmatter + Problem / Root cause / Fix / Evidence
  components/<name>.md        purpose, provenance, patterns addressed, change history
  log.md                      maintainer-appended evolution log
  skill-impact.md             gate-appended only (`add-skill-refinement`)
  .watermark.json             last processed event per raw file
```

`components/<name>.md` takes the role of the paper's `PURPOSE.md`, but stays in the wiki so collection
source repos gain no extra files. The log is `log.md`, following the paper's appendix prompt; its
section 3.1 says `logs.md`.

**Pattern frontmatter.** `id`, `components`, `cause` (`routing-miss` | `inter-skill` |
`skill-environment` | `skill-task` | `user-preference`), `trigger`, `scope_hint`,
`scope: {models, harnesses, universal}`, `evidence: [{session, event_id, kind: failure|correction|success}]`,
`status` (`active` | `superseded`), `created`, `updated`. The cause taxonomy extends SkillAligner's
regression causes with routing misses and user preference. Trigger/evidence/scope hint follows
Evo-Harness.

**Sampling.** Default up to five signal sessions and three clean sessions since the watermark. Signal
priority: explicit note > output edit > repeat activation > error or step exhaustion > follow-up turn.
Eval-origin sessions use their scores. Each session renders into a digest: activations, delegations,
tool calls with status, errors, user follow-ups, diffs, and final assistant text. Per-digest budget
is 15,000 characters, scaled down linearly when the maintainer model's configured context is under
64k tokens.

**Contract.**
`{create_patterns: [{slug, frontmatter, body}], update_patterns: [{slug, ops: [{op: append|replace|insert_after, anchor?, text}]}], update_index: "<full index>", append_log: "<entry>"}`.
The validator checks:
- required keys, and that slugs are unique and exist for updates
- each `replace`/`insert_after` anchor occurs exactly once
- every evidence id is in the sample
- `universal: true` only when evidence spans at least two models or harnesses
- frontmatter enum values

**Retries.** On failure, re-prompt with the validator's error list, at most two times. If it still
fails: no wiki change, watermark unchanged, failure recorded in `log.md`.

**Where it runs.** `/wikiskill-review` delegates to the `wikiskill-maintainer` subagent, whose only
permissions are reading the digest directory. `wikiskill review --headless` runs the same agent through
`opencode run --agent wikiskill-maintainer` with the maintainer role's model. Either way, the Python
side validates and applies. Running in-session is acceptable here because the maintainer does not
evaluate anything.

**Versioning.** One wiki commit per successful review; the message lists the sampled session ids.
The wiki is never reset.

## Risks / Trade-offs

- [Invented evidence] → evidence ids are checked against the sample.
- [Overgeneralising from one model] → the `universal` rule; scope is required.
- [Weak local maintainer produces poor patterns] → the contract and retries bound the damage; docs
  recommend the strongest available endpoint for this role; patterns are reviewable plain markdown.
- [Wiki bloat] → `superseded` status; index stays one line per active pattern; pruning left open.
- [Sensitive user text copied into the wiki] → digests carry redacted text only; wiki is local.

## Open Questions

- Should patterns be pruned or merged after N reviews without new evidence?
- Should eval-origin and live-origin evidence be weighted differently?
