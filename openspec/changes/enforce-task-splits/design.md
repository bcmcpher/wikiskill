## Context

See proposal.md for why. Today a task's split is read by the suite loader and then dropped: the
runner writes only task ids to `run.json` (`runner/run.py`), and `results.jsonl` carries no split.
Review picks eval candidates from every run of the component (`review._eval_candidates`), filtered
only by route and outcome. Replay takes motivating cases from the cited patterns' evidence and puts
every other task in the regression bank (`gate._cases`). The DSH adapter places every task in one
split, `val` by default, and its module comment argues that per-task splits would be wikiskill
deciding something about someone else's fixture.

## Goals / Non-Goals

**Goals:**
- Make the train / val / test separation hold from review through replay.
- Keep it checkable afterwards: a run says which split each task was in.

**Non-Goals:**
- Retiring or rewriting patterns that already cite `val` or `test` evidence.
- A "tuning" step that reads `val`. Nothing reads `val` specially yet; this change only keeps it out
  of review.
- Changing how a suite's own `split` fields are written or validated.

## Decisions

**Record splits in `run.json`, not per result line.** A split belongs to a task, not a unit, and
`run.json` already lists tasks. A `splits` mapping beside `tasks` keeps `results.jsonl` unchanged,
so pooling and the leaderboard need no change. Alternative: a `split` field per result. Rejected:
it repeats the value on every unit and changes a shared format for no reader's benefit.

**Filter at candidate selection in review.** `_eval_candidates` skips units whose task is not
`train`. Filtering there means the digest, the saved sample, the watermark and the refine prompt
all inherit it: refine only ever sees evidence that a review cited. Alternative: filter in refine.
Rejected: val/test evidence would still shape patterns.

**Recover older runs from the suite file by hash.** A `LoadedRun` without `splits` reloads
`suite_path` and compares its hash with `suite_hash`, using the same hash the runner records. A
match gives the splits as they were. A mismatch or a missing file leaves the run's units out, and
review reports it. For a DSH fixture the recovered split is the adapter's current assignment, not
the `val` the run used; that is acceptable because the split never affected how a unit ran, only
who may read it. Alternative: treat old runs as `train`. Rejected by the user: it keeps the leak
for every existing run.

**Deterministic DSH split from the task id.** `int(sha256(task_id)[:8], 16) % 5`: 0–2 → `train`,
3 → `val`, 4 → `test`. It depends on nothing but the id, so it is stable across machines, runs and
fixture order. A task added later does not move any other task. This reverses the adapter's stated
stance; the comment is rewritten to say wikiskill supplies a stable split because DSH declares
none, and that `--split` remains the way to choose one split for every task. The `--split` option
default changes from `val` to "none", meaning the per-task assignment.

**Replay breaks down by split, gate rule unchanged.** Each task in the motivating list, the
regression bank and the fallen list carries its split; the bank's per-model rates are also given
per split. The rule that no task may fall past the tolerance already covers every split, so it
stays. A run whose splits cannot be recovered shows `unknown`.

## Risks / Trade-offs

- [Small DSH suites may have no `train` task after hashing] → review reports "no train evidence for
  this component" with the split counts, and suggests `--split train` for that suite.
- [A wiki built before this change keeps patterns drawn from val/test] → documented in the guide;
  `review --resample` after the change rebuilds from train evidence only.
- [Recovery reloads a suite file per old run] → cached per `suite_path` in one review.
- [Existing DSH runs are re-labelled by recovery] → their recorded results are untouched; only
  which units review may read changes.

## Migration Plan

No data migration. New runs write `splits`. Old runs are recovered or left out at read time. To
roll back, revert the change: old readers ignore the extra `splits` key.
