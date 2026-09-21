"""Route metrics, outcome classification, and what a report says about work it did not do."""

from __future__ import annotations

import json

from conftest import FIXTURES
from wikiskill import report as report_mod
from wikiskill import score
from wikiskill.runner import opencode as backend_mod

OPENCODE = FIXTURES / "opencode"


def result(
    *,
    task_id: str = "release",
    model: str = "ollama/qwen2.5-coder:1.5b",
    condition: str = "routed",
    repeat: int = 0,
    outcome: str = "completed",
    activations=(),
    expected: str | None = "disseminate/dataset-release",
    agents: tuple[str, ...] = ("datalad-doer",),
    **extra,
):
    payload = {
        "run_id": "01JRUN",
        "suite": "toy",
        "task_id": task_id,
        "model": model,
        "condition": condition,
        "repeat": repeat,
        "outcome": outcome,
        "reason": None,
        "error": None,
        "duration_ms": 1000,
        "exit_code": 0,
        "tokens": {"input": 100, "output": 10},
        "session_id": f"ses_{task_id}{repeat}",
        "activations": [dict(entry) for entry in activations],
        "expected": {"primary": expected, "agents": list(agents)},
    }
    payload.update(extra)
    return payload


def skill(name):
    return {"kind": "skill", "name": name}


def agent(name):
    return {"kind": "agent", "name": name}


# --------------------------------------------------------------------------- routing


def test_route_at_1_counts_only_the_first_activation():
    results = [
        result(repeat=0, activations=[skill("dataset-release"), agent("datalad-doer")]),
        result(repeat=1, activations=[skill("qc-review"), skill("dataset-release")]),
    ]
    scored = score.score_group(results)

    assert scored.route_at_1 == 0.5, "only the first run started in the right place"
    assert scored.route_at_k == 1.0, "the expected skill was reached in at least one repeat"
    assert scored.capability_at_k == 1.0


def test_a_bare_name_matches_a_plugin_qualified_one():
    """OpenCode reports `dataset-release`; the manifest says `disseminate/dataset-release`."""
    scored = score.score_group([result(activations=[skill("dataset-release")])])
    assert scored.route_at_1 == 1.0


def test_a_run_that_activated_nothing_is_a_miss_not_an_error():
    scored = score.score_group([result(activations=[])])

    assert scored.route_at_1 == 0.0
    assert scored.chosen == {"none": 1}


def test_infrastructure_outcomes_are_excluded_from_the_denominator():
    results = [
        result(repeat=0, activations=[skill("dataset-release")]),
        result(repeat=1, outcome="infra_error", activations=[]),
        result(repeat=2, outcome="skipped", activations=[]),
    ]
    scored = score.score_group(results)

    assert scored.repeats == 1, "only the run that actually happened counts"
    assert scored.unscored == 2
    assert scored.route_at_1 == 1.0


def test_capability_counts_only_the_agents_the_task_expected():
    scored = score.score_group(
        [result(activations=[skill("dataset-release"), agent("archive-doer")])]
    )
    assert scored.capability_at_k == 0.0


def test_confusion_names_what_was_activated_instead():
    results = [
        result(repeat=0, activations=[skill("qc-review")]),
        result(repeat=1, activations=[skill("qc-review")]),
    ]
    matrix = score.confusion(score.score_all(results))
    assert matrix == {"dataset-release": {"qc-review": 2}}


def test_tasks_without_an_expected_route_report_no_route_metric():
    scored = score.score_group([result(expected=None, agents=(), activations=[])])

    assert scored.route_at_1 is None
    assert scored.capability_at_k is None
    assert score.aggregate([scored])["tasks_measuring_route"] == 0


# --------------------------------------------------------------------------- classification


def load(name):
    return json.loads((OPENCODE / name).read_text(encoding="utf-8"))


def stream(name):
    return backend_mod._parse_stream((OPENCODE / name).read_text(encoding="utf-8"))


def test_a_model_that_cannot_be_given_tools_is_an_api_error():
    """The recorded stream of a real Ollama model that does not support tool calling."""
    outcome, error = backend_mod.classify(
        stream("run-no-tools.ndjson"), [load("session-no-tools.json")]
    )

    assert outcome == "api_error"
    assert "does not support tools" in error


def test_a_printed_tool_call_is_not_a_completed_run():
    outcome, error = backend_mod.classify(
        stream("run-tool-as-text.ndjson"), [load("session-tool-as-text.json")]
    )

    assert outcome == "tool_call_as_text"
    assert "instead of making one" in error


def test_a_guard_refusal_is_behaviour_not_failure():
    outcome, error = backend_mod.classify(
        stream("run-root.ndjson"), [load("session-root.json"), load("session-child.json")]
    )

    assert outcome == "permission_blocked"
    assert "guard" in error


def test_running_out_of_steps_is_the_models_doing_not_the_harness():
    """Recorded from a real run: a one-step budget against a task needing three writes."""
    outcome, error = backend_mod.classify(
        stream("run-step-exhausted.ndjson"), [load("session-step-exhausted.json")]
    )

    assert outcome == "step_exhausted", "not permission_blocked, though the guard is what threw"
    assert "step budget of 1 exhausted" in error


def test_a_session_that_used_tools_completed():
    outcome, error = backend_mod.classify(stream("run-root.ndjson"), [load("session-root.json")])

    assert outcome == "completed"
    assert error is None


# --------------------------------------------------------------------------- reports


def manifest(**extra):
    payload = {
        "run_id": "01JRUN",
        "suite": "toy",
        "collection": "toy-collection",
        "harness": "opencode",
        "harness_version": "1.18.31",
        "wikiskill_version": "0.1.0",
        "models": ["ollama/qwen2.5-coder:1.5b"],
        "conditions": ["off", "routed"],
        "duration_s": 12.5,
        "preflight": {},
    }
    payload.update(extra)
    return payload


def test_report_states_every_skipped_and_failed_combination():
    results = [
        result(repeat=0, activations=[skill("dataset-release")]),
        result(repeat=1, outcome="skipped", reason="environment lacks datalad", activations=[]),
    ]
    built = report_mod.build_report(
        results,
        manifest(
            preflight={
                "ollama/gemma3:1b": {"ok": False, "problems": ["gemma3:1b does not support tools"]}
            }
        ),
    )

    kinds = {entry["kind"] for entry in built["not_run"]}
    assert kinds == {"skipped", "preflight"}
    reasons = " ".join(entry["reason"] for entry in built["not_run"])
    assert "datalad" in reasons and "does not support tools" in reasons


def test_report_rows_carry_routing_tokens_and_time():
    built = report_mod.build_report(
        [result(activations=[skill("dataset-release"), agent("datalad-doer")])], manifest()
    )
    row = built["rows"][0]

    assert row["route@1"] == 1.0
    assert row["tokens"] == {"input": 100, "output": 10}
    assert row["wall_time_ms"] == 1000
    assert row["pass_basis"] == "route"


def test_derived_measures_say_which_condition_is_missing():
    built = report_mod.build_report([result(activations=[])], manifest())
    derived = built["derived"]
    model = derived["per_model"]["ollama/qwen2.5-coder:1.5b"]

    assert model["routing_loss"]["value"] is None, "a run without INJECTED cannot have one"
    assert "injected" in derived["note"]
    assert "injected" in report_mod.render_markdown(built).lower()


def test_markdown_lists_unrun_work_rather_than_hiding_it():
    results = [result(outcome="infra_error", reason="timed out after 900s", activations=[])]
    text = report_mod.render_markdown(report_mod.build_report(results, manifest()))

    assert "## Not run" in text
    assert "timed out after 900s" in text
    assert "| release |" in text, "the task still gets a row, marked as having no scored repeats"
    assert "| 0 |" in text


def test_markdown_reports_a_run_where_everything_ran():
    results = [result(activations=[skill("dataset-release"), agent("datalad-doer")])]
    text = report_mod.render_markdown(report_mod.build_report(results, manifest()))

    assert "Everything the suite declared was attempted" in text
    assert "| release |" in text


# --------------------------------------------------------------------------- verifier-first


def verifier(kind="file_exists", *, passed=True, detail="CHANGELOG.md exists"):
    return {"kind": kind, "passed": passed, "detail": detail}


def test_a_verifier_verdict_decides_the_pass_rate():
    results = [
        result(
            repeat=0, activations=[], expected=None, agents=(), verifiers=[verifier()], passed=True
        ),
        result(
            repeat=1,
            activations=[],
            expected=None,
            agents=(),
            verifiers=[verifier(passed=False, detail="CHANGELOG.md does not exist")],
            passed=False,
        ),
    ]
    row = report_mod.build_report(results, manifest())["rows"][0]

    assert row["pass_rate"] == 0.5
    assert row["pass_basis"] == "verifier"


def test_a_verifier_outranks_the_route_it_also_declares():
    """The route was reached and the work was still wrong. The verifier is the verdict."""
    results = [
        result(
            activations=[skill("dataset-release"), agent("datalad-doer")],
            verifiers=[verifier(passed=False)],
            passed=False,
        )
    ]
    row = report_mod.build_report(results, manifest())["rows"][0]

    assert row["route@1"] == 1.0, "routing is still reported as its own dimension"
    assert row["pass_rate"] == 0.0
    assert row["pass_basis"] == "verifier"


def test_a_task_with_neither_route_nor_verifier_is_not_measured():
    results = [result(activations=[], expected=None, agents=())]
    row = report_mod.build_report(results, manifest())["rows"][0]

    assert row["pass_rate"] is None
    assert row["pass_basis"] == "not measured"


def test_an_unscored_repeat_contributes_no_verdict():
    results = [
        result(repeat=0, activations=[], verifiers=[verifier()], passed=True),
        result(repeat=1, outcome="infra_error", reason="verifier could not run", activations=[]),
    ]
    row = report_mod.build_report(results, manifest())["rows"][0]

    assert row["pass_rate"] == 1.0, "an infra_error is excluded, not counted as a fail"
    assert row["attempted"] == 2


def test_failing_verifiers_are_named_once_however_many_repeats_fail():
    results = [
        result(repeat=index, activations=[], verifiers=[verifier(passed=False)], passed=False)
        for index in range(3)
    ]
    built = report_mod.build_report(results, manifest())

    assert built["rows"][0]["failed_verifiers"] == [
        {"kind": "file_exists", "detail": "CHANGELOG.md exists"}
    ]
    text = report_mod.render_markdown(built)
    assert "## Failing verifiers" in text
    assert text.count("CHANGELOG.md exists") == 1


def test_markdown_says_what_each_pass_rate_is_based_on():
    results = [
        result(task_id="release", activations=[skill("dataset-release")]),
        result(
            task_id="control",
            activations=[],
            expected=None,
            agents=(),
            verifiers=[verifier()],
            passed=True,
        ),
    ]
    text = report_mod.render_markdown(report_mod.build_report(results, manifest()))

    assert "pass basis" in text
    assert "| route |" in text
    assert "| verifier |" in text


# --------------------------------------------------------------------------- refused routes


def test_a_skill_the_harness_refused_is_recorded_but_not_a_route():
    """Recorded under INJECTED: OpenCode honoured `permission.skill.<name>: deny`."""
    session = load("session-skill-denied.json")

    found = backend_mod.activations([session])

    assert found == [{"kind": "skill", "name": "wikiskill-trace", "blocked": True}]
    assert score.activated_names({"activations": found}) == [], "it reached nothing"
    assert score.first_activation({"activations": found}) == score.NONE


def test_injected_does_not_score_a_perfect_route_for_a_route_it_forbids():
    denied = [{"kind": "skill", "name": "dataset-release", "blocked": True}]
    reached = [skill("dataset-release")]

    injected = report_mod.build_report(
        [result(condition="injected", activations=denied)], manifest()
    )["rows"][0]
    routed = report_mod.build_report([result(activations=reached)], manifest())["rows"][0]

    assert routed["route@1"] == 1.0
    assert injected["route@1"] == 0.0, "the route is impossible by construction, not reached"
