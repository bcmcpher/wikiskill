"""Graded scores: the seeded bootstrap, and a report that gives a mean beside the pass rate."""

from __future__ import annotations

import json

import pytest

from test_score import manifest, result
from wikiskill import bootstrap, compare
from wikiskill import report as report_mod

# --------------------------------------------------------------------------- bootstrap


def test_one_value_is_its_own_interval():
    assert bootstrap.mean_interval([71.5]) == (71.5, 71.5, 71.5)


def test_constant_scores_have_an_interval_of_no_width():
    assert bootstrap.mean_interval([100, 100, 100]) == (100.0, 100.0, 100.0)


def test_no_values_give_no_interval():
    assert bootstrap.mean_interval([]) is None


def test_repeat_calls_give_the_same_interval():
    values = [0, 12, 40, 41, 100]
    assert bootstrap.mean_interval(values) == bootstrap.mean_interval(values)


def test_the_interval_holds_the_mean_and_stays_in_the_data():
    mean, low, high = bootstrap.mean_interval([0, 0, 100, 100, 50]) or (0, 0, 0)

    assert mean == 50
    assert 0 <= low < mean < high <= 100


def test_a_different_seed_can_move_the_interval():
    values = [3, 17, 29, 55, 61, 88]
    assert bootstrap.mean_interval(values, seed=1) != bootstrap.mean_interval(values)


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
    assert 60 <= entry["low"] <= entry["high"] <= 80
    text = report_mod.render_markdown(built)
    assert "## Scores" in text
    assert "| release | ollama/qwen2.5-coder:1.5b | routed | `score` | 70.0 (" in text


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


def test_one_unit_is_marked_rather_than_given_a_range():
    built = report_mod.build_report([graded(0, 71.5)], manifest())
    assert "71.5 (one unit)" in report_mod.render_markdown(built)


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
