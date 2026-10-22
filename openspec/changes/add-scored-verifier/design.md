## Context

`score/verify.py:_command` runs `run` in the workdir and returns `VerifierResult(passed, detail,
exit_code, output)`, where output is stdout and stderr joined and cut to 2000 characters.
`VerifierError` becomes `infra_error` in `runner/run.py:366`. Reports build per-row summaries in
`report.py:_row`; rubric dimensions sit beside the pass rate through `_rubric` and `_rubric_lines`.
`findings.py` writes `findings.csv` from `CSV_COLUMNS`, and `report` tables add a slim rubric table.

## Goals / Non-Goals

**Goals:**
- Apply a grader's own pass rule without a wrapper script.
- Keep the grader's whole result per unit, so later analysis needs no rerun.
- Report a graded score with an interval, in the same places rubric scores appear.

**Non-Goals:**
- Expressions or numeric comparisons in `pass_when`; field equality only.
- Nested field paths. A grader with nested output needs a top-level field for its verdict.
- Scores in the pooled leaderboard or the version board. They stay in run reports and study CSVs
  until a study needs them there.

## Decisions

- **Exit code AND fields.** The grader's exit code keeps its meaning (validity for skills-comm), and
  `expect_exit` still applies. An invalid submission that exits non-zero fails without relying on its
  verdict. Alternative: fields alone; rejected because it would ignore a scorer's own failure signal.
- **stdout only, whole then last line.** stderr is kept for the output tail but never parsed. Many
  scorers log before printing their result; the last-line fallback handles that without a marker.
- **Unparseable output is `infra_error`.** A grader that cannot report is broken infrastructure; the
  model's mistakes reach it as an `invalid` verdict, which the grader prints. This matches how a
  verifier that cannot start is treated today.
- **Percentile bootstrap, fixed seed.** Scores are bounded and lumpy, often piled at 0 or 100, so a
  t-interval misbehaves at small n. 2000 resamples with `random.Random(0)`, stdlib only, give the
  same interval on every rebuild. With n = 1 the interval is the single value, marked as such.
- **Result stored under the verifier record.** `verifiers[i].result` keeps one record per verifier,
  so a task with two scored verifiers stays unambiguous. The 64 KiB cap bounds `results.jsonl`, which
  bundles commit to git.

## Risks / Trade-offs

- [Risk] A grader's JSON contains large arrays (per-voxel metrics) and hits the cap → Mitigation: the
  error names the size; the suite author points `run` at a summary mode or filters with `jq`.
- [Risk] A mean score reads as more decisive than the pass rate → Mitigation: it is printed with its
  n and interval, beside the rate, never ranked on.
- [Risk] The scorer's result changes shape between versions → Mitigation: `pass_when` failures name
  the missing field, so a shape change shows as an explicit failure, not a silent pass.

## Open Questions

None.
