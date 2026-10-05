## 0. Minimal working core

The proposal contract, its checks, and patch delivery (1.x–2.x), plus the gate with human decision,
replay, and the impact record (3.1–3.4). `add-explicit-eval` comes earlier on the roadmap, so replay is
available from the start.

## 0a. Rebase onto add-minimal-loop

- [x] 0a.1 `add-minimal-loop` introduced:
  - the `refinement-proposal` capability: `src/wikiskill/refine.py`, `wikiskill refine`,
    `wiki/proposals/p-NNN/`, and `harness/source/agents/wikiskill-proposer.md`
  - `version-comparison`: `wikiskill compare` and its `--record` into `skill-impact.md`

  The deltas are now `MODIFIED`/`ADDED` against those specs, and `refinement-gate` is new. The
  decisions are recorded in `design.md` under "Rebase onto step 3":
  - the reply keeps step 3's `find`/`replace` edits
  - `create` is deferred
  - evidence is shown in the prompt rather than fetched and counted from a `_wikiskill` log, which
    replaces the old 1.3 and 1.4
  - the gate states extend `meta.json`'s `status`
  - replay is `compare` plus a per-task breakdown
  - acting on a proposal is a `wikiskill proposal` group

## 1. Proposer and contract

- [x] 1.1 Extend the reply contract in `refine.py`: `component` (single target), `evidence`, `models`.
- [x] 1.2 Proposer prompt: digests of the evidence the active patterns cite, labelled as in review and
  fitted to the proposer's budget, plus the component's earlier `skill-impact.md` entries. Update
  `harness/source/agents/wikiskill-proposer.md`.
- [x] 1.3 `refine --prepare` persists the prompt; `refine --prompt <id> --reply-file` checks a
  harness reply against it. Add `harness/source/commands/wikiskill-refine.md`; build for both
  harnesses.
- [x] 1.4 Evidence check: cited labels were shown, at least `min(4, shown)` of them.
- [x] 1.5 Leakage check against the component's suites (task ids, verifier literals, rubric anchors)
  and long notes, with the matched text named; `--allow-overlap` recorded.
- [x] 1.6 Pooled-first check: marked models need scoped patterns with at least three evidence items;
  unmarked model names are rejected.

## 2. Delivery

- [x] 2.1 Write `wiki/proposals/<id>/{proposal.json,patch.diff,rendered/,preview.md,meta.json}`, with
  `candidate_hash`.
- [x] 2.2 `wikiskill proposal list|show <id>`.
- [x] 2.3 `wikiskill proposal apply <id> [--branch]`; without `--branch` it writes nothing; with it,
  refuses a dirty worktree or a moved file.

## 3. Gate

- [x] 3.1 State machine in `src/wikiskill/gate.py` and `wikiskill proposal decide <id>
  accept|reject|withdraw --note`.
- [x] 3.2 `wikiskill eval --proposal <id>` from a copy of the source; `wikiskill proposal replay <id>
  <baseline> <candidate>` with motivating cases, regression bank and non-replayable evidence.
- [x] 3.3 Report per model: motivating delta, individually listed regressions, recommendation.
- [x] 3.4 Append every outcome to `skill-impact.md`, rejected and withdrawn content in full; `compare
  --record` goes through the gate.

## 4. Verify

- [x] 4.1 `uv run pytest tests/test_refine.py`: rejects a second component, unshown or too few
  evidence labels, task-id leakage, and unsupported model-specific guidance.
  - 24 tests. They also cover verifier-literal and rubric/note leaks, the `--allow-overlap`
    override, and the `--prepare`/`--prompt` harness path, including a stale prompt.
  - Found live: a command and a skill both named `wikiskill-trace`, and refine, review and the gate
    all took the first match, which was the command. `Collection.component()` now prefers the
    watched kind; `test_collection.py` covers it.
- [x] 4.2 `uv run pytest tests/test_gate.py`: accept is impossible without a decision call; a rejected
  proposal's full content is in `skill-impact.md` and in the next proposer prompt; the wiki's
  patterns are unchanged. 18 tests, including:
  - a net improvement whose regression is named
  - one lost repeat in three, listed but within tolerance
  - runs refused when they are not what they claim
  - live evidence marked non-replayable
  - `compare --record` going through the gate
- [x] 4.3 After `proposal apply` without `--branch`, and after `eval --proposal`, `git -C <source>
  status` is unchanged: `test_apply_without_a_branch_writes_nothing` and
  `test_a_candidate_runs_from_a_copy_and_the_source_is_untouched`. `--branch` commits on its own
  branch and returns the user to theirs.
- [x] 4.4 Live: one proposal through `eval --proposal`, `replay` and `decide` on a local model,
  on 2026-10-05, on `wikiskill-self`'s `wikiskill-trace` with `qwen3:30b-a3b` as the proposer.
  - p-001 was a real proposer patch, made in 1m47s, but against the `wikiskill-trace` command (the
    lookup bug in 4.1). It was withdrawn through `proposal decide`.
  - Re-run twice, the proposer answered `no_action`, citing p-001 in its history: the history
    reaches it and it uses it.
  - p-002 was therefore a hand-written reply through `--reply-file`, so it went through the same
    checks.
  - `toy-routing`, ROUTED, `gemma4:latest` and `qwen3:30b-a3b`:
    - baseline `01M46KSQFPM98P2DDQPEFYFM8P` at `ebbe81a0…`
    - candidate `01M46KWX6AKM47RQBRP6AX79JZ` at `8ac72789…`, from `candidate-source/`, with
      `proposal: p-002` in `run.json`
    - the source's `git status --porcelain` was identical before and after
  - `proposal replay` listed both cited live sessions as not replayable and recommended `none`,
    because no motivating case is a task of that suite.
  - p-002 was withdrawn, with its full content in `skill-impact.md`. The wiki has one commit per
    step: propose, replay, withdraw.
  - Not shown live: a motivating eval task. That needs a pattern drawn from eval evidence on a
    suite with verifiers, which step 4's pilot provides. Route-only tasks are unscored in `compare`,
    so they cannot regress in a replay either.
- [x] 4.5 `openspec validate add-skill-refinement --strict --no-interactive`.
