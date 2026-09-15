## 0. Minimal working core

The proposal contract, its checks, and patch delivery (1.x–2.x), plus the gate with human decision,
replay, and the impact record (3.1–3.4). `add-explicit-eval` comes earlier on the roadmap, so replay is
available from the start. Deferred: `--branch` delivery (2.3).

## 1. Proposer and contract

- [ ] 1.1 `schemas/proposal.schema.json` and validator in `src/wikiskill/propose.py` (single component,
  anchor uniqueness, file ownership).
- [ ] 1.2 `harness/source/agents/wikiskill-proposer.md` (read-only digest and wiki access) and
  `harness/source/commands/wikiskill-refine.md`; build for OpenCode.
- [ ] 1.3 Log wikiskill's own agents under the internal `_wikiskill` collection.
- [ ] 1.4 `wikiskill propose check`: verify distinct digest reads from the proposer session log.
- [ ] 1.5 Leakage check against task suites, rubrics, and note text, with a matched-span message.
- [ ] 1.6 Pooled-first check: model-specific guidance requires scoped patterns with at least three
  evidence items.

## 2. Delivery

- [ ] 2.1 Write `wiki/proposals/<id>/{proposal.json,patch.diff,rendered/,summary.md}`.
- [ ] 2.2 `wikiskill refine list|show <id>`.
- [ ] 2.3 `wikiskill refine apply <id> [--branch]`; refuses on a dirty source worktree.

## 3. Gate

- [ ] 3.1 State machine and `wikiskill refine decide <id> accept|reject|withdraw --note`.
- [ ] 3.2 Replay: build motivating and regression cases, run baseline vs candidate through the eval
  runner across the manifest's target models, and mark non-replayable cases with reasons.
- [ ] 3.3 Report per model: motivating delta, individually listed regressions, recommendation.
- [ ] 3.4 Append every outcome to `skill-impact.md`; keep rejected proposal content in full.

## 4. Verify

- [ ] 4.1 `uv run pytest tests/test_propose.py`: rejects two-component proposals, unread claimed
  digests, task-id leakage, and unsupported model-specific sections.
- [ ] 4.2 `uv run pytest tests/test_gate.py`: accept is impossible without a decision call; a rejected
  proposal's full content is in `skill-impact.md`; the wiki's patterns are unchanged.
- [ ] 4.3 After `refine apply` without `--branch`, `git -C <source> status` is unchanged apart from the
  user applying the diff.
- [ ] 4.4 `openspec validate add-skill-refinement --strict --no-interactive`.
