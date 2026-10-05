## 0. Rebase onto add-minimal-loop

- [x] 0a.1 `add-minimal-loop` introduced the `experience-wiki` capability:
  - `src/wikiskill/wiki.py` and `review.py`
  - the maintainer contract and `schemas/maintainer-output.schema.json`
  - `wikiskill review`
  - `harness/source/agents/wikiskill-maintainer.md`
  - `tests/test_wiki.py`

  Rebased 2026-10-05, after `add-minimal-loop` and `add-correction-capture` were archived.
  - The spec delta now modifies the two live requirements and adds four.
  - The contract stays `add-minimal-loop`'s. The anchor-based patch operations are dropped; `design.md`
    says what replaces them.
  - The modules are extended; no `maintain.py`.
  - `collection-config` gains a role's `context_tokens`.

## 1. Sampling and the watermark

- [x] 1.1 Rank evidence by signal (note, output edit, repeat, failure, follow-up, unscored, clean),
  newest first within a rank, capped by `--signals` and `--clean`. Live digests show their signals.
- [x] 1.2 Budget: 15,000 characters by default, scaled down by the maintainer role's `context_tokens`
  under 65,536, floor 4,000; `--budget` overrides. `collection-config`: parse and validate
  `context_tokens`.
- [x] 1.3 `.watermark.json`: per component, eval unit keys and live session id → last shown event id.
  Exclude processed evidence; `--resample` ignores it; advanced only in a successful review's
  commit. Nothing new: report it, ask nothing, commit nothing.
- [x] 1.4 `wikiskill sample <component> --collection <c>` persists `prompt.md`, `evidence.json` and
  `sample.json` and prints the id; `wikiskill review --sample <id> --reply-file <f>` applies against
  it, refusing a stale sample.

## 2. Contract

- [x] 2.1 Schema: optional `universal` on create and update; `status: superseded` on update; causes
  `routing_miss` and `user_preference`. Maintainer prompt updated to match.
- [x] 2.2 Validator: reject `universal: true` whose evidence, with an update's existing evidence,
  spans one model and one harness. The index covers active patterns only; superseded ones leave it.

## 3. Wiki

- [x] 3.1 `components/<flat-name>.md` created on a component's first pattern; its pattern table is
  regenerated and a history line appended on every review.
- [x] 3.2 Exhausted retries append a failure entry to `log.md` and commit it; patterns, index and
  watermark unchanged.

## 4. In-harness review

- [x] 4.1 `harness/source/commands/wikiskill-review.md`: sample, delegate to `wikiskill-maintainer`,
  write the reply into the sample, apply with `wikiskill review --sample`, return problems at most
  twice. Builds for OpenCode and Claude Code.

## 5. Verify

- [x] 5.1 `uv run pytest tests/test_wiki.py`, covering:
  - signal ordering, with a noted session ahead of clean ones;
  - the budget scaling;
  - the watermark, including a second review with nothing new and a session that gains a note;
  - `universal`, `superseded`, and component pages;
  - a failed review's log entry;
  - a persisted sample applied, and refused when stale.
- [x] 5.2 The command builds for both harnesses (`tests/test_build*.py`).
- [x] 5.3 Live: `wikiskill review` against a real maintainer endpoint on logged sessions with a
  correction signal; then a second run reports nothing to review. If no endpoint is reachable,
  record it as unrun with the reason.

  Done 2026-10-05: `wikiskill review wikiskill-trace --collection wikiskill-self`, maintainer
  `qwen3:30b-a3b` on Ollama 0.34.2 with `context_tokens = 40960` (budget 9,375 characters).
  - The sample led with the two live OpenCode sessions from `add-correction-capture` 4.3, which
    carry the note and the follow-up turn.
  - The reply validated on the first attempt, in 1m14s, and created
    `ignored-instruction-to-ask-when-collection-not-found` (`instruction_ignored`) from both
    sessions. The wiki commit was `a21b3dd`.
  - The watermark recorded both sessions and 6 eval units. The next sample skipped them and held
    the remaining eval units.

  "Nothing to review" was not reached live: the collection has 73 more unreviewed eval units, so
  that path is covered by tests only.

  Two fixes came out of the run:
  - `infra_error` and `api_error` units were ranked as failures and crowded the sample, so they
    are no longer evidence.
  - A live session's `source_hash` was read from its first event, which carries no component. It
    now comes from the activation. The pattern written before this fix records no hash.
- [x] 5.4 `openspec validate add-experience-wiki --strict --no-interactive`.
