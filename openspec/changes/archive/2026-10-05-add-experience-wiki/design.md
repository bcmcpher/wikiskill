## Context

In WikiSkill the Wiki Maintainer runs once per iteration. It reads up to eight sampled traces (at most
five failing, three passing, each capped at 15,000 characters) and returns a JSON edit to the wiki.
The Skill Proposer then reads the wiki index, not raw traces first.

`add-minimal-loop` (archived 2026-10-05) built the core of this:
- `wiki.py`: the layout, validation against `schemas/maintainer-output.schema.json`, apply and commit,
  and scope computed from cited evidence.
- `review.py`: a character-budgeted digest of eval units and live sessions, failures first, and the
  retry loop.
- Asking the maintainer role through its endpoint or through `opencode run`.

This change builds on those modules rather than replacing them.

Our inputs differ from the paper's: live sessions have no ground-truth score, and they carry
correction signals the paper never had. Sessions span several models and two harnesses, so a lesson
learned on one small model must not be presented as universal.

## Goals / Non-Goals

**Goals:**
- Review that only looks at what is new, and looks at corrections first.
- A digest that fits the maintainer's context, whatever that model is.
- The same review from inside the harness and from the command line, applied by the same code.

**Non-Goals:**
- **Editing skills** — `add-skill-refinement`.
- **Pruning or merging old patterns** automatically, a stated limitation of the paper. The maintainer
  can mark a pattern `superseded`.
- **Choosing a maintainer model** — configured per collection.

## Decisions

**Keep `add-minimal-loop`'s contract.** The contract stays as it is:
`{create: [...], update: [{slug, evidence, observation}], index: {slug: summary}, log}`.

The original plan here was patch operations (`append | replace | insert_after` with anchors) on a
pattern's text. They are not adopted, for three reasons:
- Updates append an observation and merge evidence, so a pattern's history is never rewritten.
- A model has nothing to get wrong about an anchor.
- Scope is recomputed from the merged evidence.

What the patch operations were for is covered instead by:
- `status: "superseded"` on an update, which retires a pattern from the index while keeping its
  page;
- creating a new pattern.

The cause taxonomy keeps `add-minimal-loop`'s values and adds `routing_miss`, for a task where the
expected component was not what the model reached for, and `user_preference`, for a correction that
says what the user wanted rather than what was wrong.

**Universality.** `scope` is computed by wikiskill, never claimed. The one claim the maintainer may
make is `universal: true`, on a create or an update. It is rejected unless the pattern's evidence,
counting existing evidence for an update, spans at least two models or two harnesses. Without the
claim a pattern is `universal: false`.

**Sampling.** Each candidate is ranked by its strongest signal:

| rank | signal | where it comes from |
|---|---|---|
| 0 | explicit note | `note` event |
| 1 | output edit | `output_edit` event |
| 2 | repeat activation | `repeat_activation` event |
| 3 | failure | eval unit with `passed: false` or an outcome such as `step_exhausted`, a failed tool call |
| 4 | follow-up turn | `user_turn` event |
| 5 | unscored | eval unit with no verifier verdict |
| 6 | clean | passed eval unit, live session with no signal |

Eval units that ended `infra_error`, `api_error` or `skipped` are not evidence: the harness or the
endpoint failed, not the component. The sample takes up to `--signals` (default 5) candidates ranked 0–5, then up to `--clean`
(default 3) ranked 6. Ties go to the newest. One passing unit per task, as before. A live session's
digest gains its signal lines: the note text, the first follow-up turns, and the edit's diff, each
truncated. All of this is already redacted by the logger.

**Budget.** The default per-review budget is 15,000 characters. A role may set `context_tokens`. When
that is under 65,536 the budget scales linearly with it, with a floor of 4,000 characters. So a
32k-token maintainer gets 7,500. `--budget` overrides both.

**Watermark.** `<wiki>/.watermark.json` maps each component to the evidence it has been reviewed
on:
- `eval`: a list of unit keys `run/task/model/condition/repeat`;
- `sessions`: live root session id → the id of the last event that was shown.

A live session reappears when new events arrive after that id: a later note, say. Only evidence that
was shown is marked; evidence that did not fit stays unprocessed for the next review. The watermark
is written in the same commit as the review's patterns, so a failed review cannot advance it.
`--resample` ignores it.

With nothing unprocessed, review reports nothing to review, asks no model, and commits nothing.

**Persisted samples.** `wikiskill sample <component>` writes
`<collection data>/samples/<id>/{prompt.md, evidence.json, sample.json}` and prints the id and path.
`sample.json` holds the component, runs, budget and keys. `wikiskill review --sample <id>
--reply-file <file>` validates and applies a reply against that sample's evidence map and advances
the watermark from its keys. It refuses a sample whose component patterns have changed since it was
taken, because the existing-pattern list the maintainer saw is stale. Without `--sample`,
`wikiskill review` samples and asks the maintainer role itself, headless, as before.

**In-harness command.** `/wikiskill-review <component>` takes four steps:
1. Run `wikiskill sample`.
2. Delegate to the `wikiskill-maintainer` subagent with the prompt file's path. The subagent has
   read-only permissions and returns the JSON.
3. Write the reply to a file in the sample directory.
4. Run `wikiskill review --sample <id> --reply-file <file>`.

If that reports problems, the command sends them back to the subagent, at most twice. Running
in-session is acceptable because the maintainer does not evaluate anything.

**Component pages.** On a component's first pattern, `components/<flat-name>.md` is created. Each
review regenerates its pattern table from the pattern pages and appends one history line. The
regenerated table lists every pattern with its status, the hashes it was observed on, and its
models. The page takes the role of the paper's `PURPOSE.md`, but stays in the wiki so collection
source repositories gain no files.

**Failure.** After the last retry the review appends a `log.md` entry and commits it. The entry
names the component, the maintainer, the attempts and the last problems. Nothing else changes.

**Versioning.** One wiki commit per review, successful or failed. The wiki is never reset.

## Risks / Trade-offs

- [Invented evidence] → evidence ids are checked against the sample.
- [Overgeneralising from one model] → `universal` is checked against evidence; scope is computed.
- [A weak local maintainer writes poor patterns] → the contract and retries bound the damage; patterns
  are plain markdown.
- [Signals crowd out clean sessions] → a separate clean quota.
- [A stale persisted sample] → refused when the component's patterns changed since it was taken.
- [Wiki bloat] → `superseded` drops a pattern from the index; pruning is left open.
- [Sensitive user text copied into the wiki] → digests carry logger-redacted text only; the wiki is
  local.

## Open Questions

- Should patterns be pruned or merged after N reviews without new evidence?
- Should eval-origin and live-origin evidence be weighted differently?
