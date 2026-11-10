"""Graded scores: the t-interval of a mean, and a report that gives it beside the pass rate."""

from __future__ import annotations

import json

import pytest

from test_score import manifest, result
from wikiskill import compare, interval
from wikiskill import report as report_mod

# --------------------------------------------------------------------------- interval


def test_one_value_has_no_interval():
    assert interval.mean_interval([71.5]) == (71.5, None, None)


def test_constant_scores_have_an_interval_of_no_width():
    assert interval.mean_interval([100, 100, 100]) == (100.0, 100.0, 100.0)


def test_constant_scores_that_do_not_sum_exactly_still_have_no_width():
    # fsum([0.1] * 3) / 3 is not 0.1, so a computed interval would be a sliver, not a point.
    assert interval.mean_interval([0.1, 0.1, 0.1]) == (0.1, 0.1, 0.1)


def test_no_values_give_no_interval():
    assert interval.mean_interval([]) is None


def test_three_scores_give_the_t_interval():
    mean, low, high = interval.mean_interval([60, 70, 80]) or (0, 0, 0)

    assert mean == 70
    assert (round(low or 0, 1), round(high or 0, 1)) == (45.2, 94.8)


def test_repeat_calls_give_the_same_interval():
    values = [0, 12, 40, 41, 100]
    assert interval.mean_interval(values) == interval.mean_interval(values)


def test_the_interval_is_not_clipped_to_the_scale():
    _, low, high = interval.mean_interval([0, 0, 100]) or (0, 0, 0)
    assert (low or 0) < 0 and (high or 0) > 100


def test_past_thirty_degrees_of_freedom_the_normal_quantile_is_used():
    assert interval.t975(1) == 12.706
    assert interval.t975(30) == 2.042
    assert interval.t975(31) == 1.96


# --------------------------------------------------------------------------- report


def graded(repeat: int, score, *, verdict: str = "acceptable", outcome: str = "completed"):
    """A unit scored by a `result: json` verifier with `score: score`."""
    record = {
        "kind": "command",
        "passed": verdict == "acceptable",
        "detail": "`grade` exited 0, expected 0",
        "exit_code": 0,
        "result": {"verdict": verdict, "score": score},
        "score_field": "score",
    }
    return result(
        repeat=repeat,
        outcome=outcome,
        activations=[],
        expected=None,
        agents=(),
        verifiers=[record] if outcome == "completed" else None,
        passed=record["passed"] if outcome == "completed" else None,
    )


def test_three_repeats_give_a_mean_an_n_and_an_interval():
    built = report_mod.build_report([graded(0, 60), graded(1, 70), graded(2, 80)], manifest())
    (entry,) = built["rows"][0]["scores"]

    assert entry["field"] == "score"
    assert entry["mean"] == 70
    assert entry["n"] == 3
    assert entry["missing"] == 0
    assert (round(entry["low"], 1), round(entry["high"], 1)) == (45.2, 94.8)
    text = report_mod.render_markdown(built)
    assert "## Scores" in text
    assert (
        "| release | ollama/qwen2.5-coder:1.5b | routed | `score` | 70.0 (45.2 to 94.8) |" in text
    )


def test_a_non_numeric_score_is_left_out_and_counted():
    results = [
        graded(0, 60),
        graded(1, 70),
        graded(2, 80),
        graded(3, None, verdict="invalid"),
    ]
    (entry,) = report_mod.build_report(results, manifest())["rows"][0]["scores"]

    assert entry["n"] == 3
    assert entry["missing"] == 1
    assert entry["mean"] == 70


def test_a_boolean_is_not_a_score():
    (entry,) = report_mod.build_report([graded(0, True)], manifest())["rows"][0]["scores"]
    assert entry["n"] == 0
    assert entry["mean"] is None


def test_infrastructure_units_are_not_scored_and_the_score_leaves_the_rate_alone():
    results = [
        graded(0, 90),
        graded(1, 30, verdict="marginal"),
        graded(2, 0, outcome="infra_error"),
    ]
    row = report_mod.build_report(results, manifest())["rows"][0]
    (entry,) = row["scores"]

    assert entry["n"] == 2
    assert entry["missing"] == 0, "an infra_error is neither scored nor counted without a score"
    assert row["pass_rate"] == 0.5


def test_an_integer_past_a_floats_range_is_not_a_score():
    results = [graded(0, 10**400), graded(1, 50)]
    (entry,) = report_mod.build_report(results, manifest())["rows"][0]["scores"]

    assert (entry["n"], entry["missing"], entry["mean"]) == (1, 1, 50.0)


def test_one_unit_is_marked_rather_than_given_a_range():
    built = report_mod.build_report([graded(0, 71.5)], manifest())
    (entry,) = built["rows"][0]["scores"]

    assert (entry["low"], entry["high"]) == (None, None)
    assert "71.5 (one unit)" in report_mod.render_markdown(built)


def test_identical_scores_are_marked_rather_than_printed_as_a_range():
    built = report_mod.build_report([graded(0, 100), graded(1, 100)], manifest())
    assert "100.0 (all equal)" in report_mod.render_markdown(built)


def test_identical_inexact_scores_are_marked_too():
    built = report_mod.build_report([graded(i, 0.1) for i in range(3)], manifest())
    assert "0.1 (all equal)" in report_mod.render_markdown(built)


def test_two_scored_verifiers_stay_apart():
    unit = graded(0, 60)
    second = {**unit["verifiers"][0], "result": {"grade": 9}, "score_field": "grade"}
    unit["verifiers"].append(second)
    entries = report_mod.build_report([unit], manifest())["rows"][0]["scores"]

    assert [(entry["verifier"], entry["field"], entry["mean"]) for entry in entries] == [
        (0, "score", 60.0),
        (1, "grade", 9.0),
    ]


def test_a_run_from_before_scores_has_no_score_section():
    plain = {"kind": "file_exists", "passed": True, "detail": "CHANGELOG.md exists"}
    results = [
        result(repeat=0, activations=[], verifiers=[plain], passed=True),
        result(repeat=1, activations=[], verifiers=[{**plain, "passed": False}], passed=False),
    ]
    built = report_mod.build_report(results, manifest())

    assert built["rows"][0]["scores"] == []
    assert built["rows"][0]["pass_rate"] == 0.5
    assert "## Scores" not in report_mod.render_markdown(built)


def write_run(root, results):
    root.mkdir()
    (root / "run.json").write_text(json.dumps(manifest()), encoding="utf-8")
    (root / "results.jsonl").write_text(
        "".join(json.dumps(entry) + "\n" for entry in results), encoding="utf-8"
    )
    return compare.load_run("", root)


@pytest.mark.parametrize("scores", [[60, 70, 80], [0, 100, 100, 41, 12]])
def test_a_rebuilt_report_gives_the_same_means_and_intervals(tmp_path, scores):
    run = write_run(tmp_path / "run", [graded(index, value) for index, value in enumerate(scores)])

    first = report_mod.rebuild(run)
    first_md = (tmp_path / "run" / "report.md").read_text(encoding="utf-8")
    second = report_mod.rebuild(run)

    assert first["rows"][0]["scores"] == second["rows"][0]["scores"]
    assert (tmp_path / "run" / "report.md").read_text(encoding="utf-8") == first_md
