"""Derived measures: what the three conditions mean once they have all been scored.

Built from result dicts rather than recorded sessions, because these are arithmetic over pass rates
and the arithmetic is the thing under test. The pass rates themselves are recorded elsewhere.
"""

from __future__ import annotations

import pytest

from wikiskill import report as report_mod
from wikiskill.score import derive


def result(task, model, condition, *, passed=None, repeat=0, outcome="completed", route=None):
    payload = {
        "task_id": task,
        "model": model,
        "condition": condition,
        "repeat": repeat,
        "outcome": outcome,
        "activations": [{"kind": "skill", "name": route}] if route else [],
        "expected": {"primary": "target", "agents": []},
    }
    if passed is not None:
        payload["verifiers"] = [{"kind": "command", "passed": passed, "detail": "ran"}]
        payload["passed"] = passed
    return payload


def triple(task, model, *, off, routed, injected):
    return [
        result(task, model, "off", passed=off),
        result(task, model, "routed", passed=routed),
        result(task, model, "injected", passed=injected),
    ]


# --------------------------------------------------------------------------- verdicts


def test_a_verdict_is_the_pass_rate_over_scored_repeats():
    results = [
        result("t", "m", "routed", passed=True, repeat=0),
        result("t", "m", "routed", passed=False, repeat=1),
        result("t", "m", "routed", repeat=2, outcome="infra_error"),
    ]

    (verdict,) = derive.verdicts(results)

    assert verdict.rate == 0.5
    assert verdict.repeats == 2, "the infra_error is excluded, not counted as a fail"
    assert verdict.passed is False, "a tie is not a pass"


def test_a_task_nothing_measures_has_no_verdict():
    bare = {
        "task_id": "t",
        "model": "m",
        "condition": "off",
        "repeat": 0,
        "outcome": "completed",
        "activations": [],
        "expected": {"primary": None, "agents": []},
    }

    (verdict,) = derive.verdicts([bare])

    assert verdict.rate is None
    assert verdict.basis == derive.UNMEASURED
    assert verdict.passed is None


# --------------------------------------------------------------------------- differences


def test_routing_loss_is_what_the_model_failed_to_reach():
    found = derive.verdicts(triple("t", "m", off=False, routed=False, injected=True))

    loss = derive.difference(found, "m", "injected", "routed")
    value = derive.difference(found, "m", "injected", "off")

    assert loss["value"] == 1.0, "the text works; the model never got to it"
    assert value["value"] == 1.0
    assert loss["tasks"] == 1


def test_a_skill_that_is_reached_and_does_not_help_shows_no_routing_loss():
    found = derive.verdicts(triple("t", "m", off=False, routed=False, injected=False))

    assert derive.difference(found, "m", "injected", "routed")["value"] == 0.0
    assert derive.difference(found, "m", "injected", "off")["value"] == 0.0


def test_a_missing_condition_is_said_rather_than_guessed():
    found = derive.verdicts(
        [result("t", "m", "off", passed=False), result("t", "m", "routed", passed=True)]
    )

    loss = derive.difference(found, "m", "injected", "routed")

    assert loss["value"] is None
    assert loss["tasks"] == 0
    assert "injected" in loss["reason"]


def test_a_verifier_rate_is_never_subtracted_from_a_routing_one():
    """Two numbers that mean different things must not be differenced."""
    results = [
        result("t", "m", "off", passed=False),
        result("t", "m", "routed", route="target"),
    ]
    found = derive.verdicts(results)

    assert {v.basis for v in found} == {derive.VERIFIER, derive.ROUTE}
    assert derive.difference(found, "m", "routed", "off")["tasks"] == 0


# --------------------------------------------------------------------------- drift


def test_transfer_and_regression_count_tasks_that_changed_verdict():
    results = [
        entry
        for task, off, routed in (
            ("gained", False, True),
            ("lost", True, False),
            ("same", True, True),
            ("none", False, False),
        )
        for entry in (
            result(task, "m", "off", passed=off),
            result(task, "m", "routed", passed=routed),
        )
    ]
    found = derive.verdicts(results)

    measured = derive.drift(found, "m", "off", "routed")

    assert measured["transfer_rate"] == 0.25
    assert measured["regression_rate"] == 0.25
    assert measured["tasks"] == 4


# --------------------------------------------------------------------------- mcnemar


def test_mcnemar_with_no_disagreement_cannot_tell_the_models_apart():
    assert derive.mcnemar([True, False], [True, False]) == {
        "b": 0,
        "c": 0,
        "p_value": 1.0,
        "tasks": 2,
    }


def test_mcnemar_counts_only_the_tasks_the_models_disagreed_on():
    left = [True, True, True, True, True, True, False]
    right = [False, False, False, False, False, False, False]

    out = derive.mcnemar(left, right)

    assert (out["b"], out["c"]) == (6, 0)
    assert out["p_value"] == pytest.approx(2 / 2**6), "six coin flips the same way"


def test_mcnemar_refuses_unpaired_input():
    with pytest.raises(ValueError):
        derive.mcnemar([True], [True, False])


# --------------------------------------------------------------------------- report


def manifest(**extra):
    payload = {
        "run_id": "01JRUN",
        "suite": "toy",
        "models": ["a/one", "b/two"],
        "conditions": ["off", "routed", "injected"],
        "preflight": {},
    }
    payload.update(extra)
    return payload


def test_the_report_carries_every_measure_and_the_comparison():
    results = [
        entry
        for task, model, routed, injected in (
            ("t1", "a/one", True, True),
            ("t2", "a/one", False, True),
            ("t1", "b/two", False, False),
            ("t2", "b/two", False, False),
        )
        for entry in triple(task, model, off=False, routed=routed, injected=injected)
    ]

    built = report_mod.build_report(results, manifest())
    derived = built["derived"]

    assert derived["per_model"]["a/one"]["routing_loss"]["value"] == 0.5
    assert derived["per_model"]["a/one"]["transfer_rate"] == 0.5
    assert derived["per_model"]["b/two"]["routing_loss"]["value"] == 0.0
    (pair,) = derived["comparisons"]
    assert (pair["left"], pair["right"]) == ("a/one", "b/two")
    assert (pair["b"], pair["c"]) == (1, 0)

    text = report_mod.render_markdown(built)
    assert "## Derived measures" in text
    assert "exact McNemar" in text
    assert "every condition ran" in text
