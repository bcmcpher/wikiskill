"""The rubric judge: blind, never a model under test, and never able to change a pass rate.

No test here calls a model. `request_json` is the only seam to a network and it is the only thing
replaced; everything else — the prompt, the parsing, the panel arithmetic — runs for real.
"""

from __future__ import annotations

import json

import pytest

from wikiskill import report as report_mod
from wikiskill import rubric as rubric_mod
from wikiskill.runner.preflight import Endpoint
from wikiskill.score import judge as judge_mod

RUBRIC = """
id: provenance
dimensions:
  - id: reachability
    evidence: Walk the history back to raw inputs.
    anchors:
      none: Nothing traces.
      partial: Some traces.
      complete: Everything traces.
  - id: ledger_validity
    type: binary
    anchors:
      fail: Does not validate.
      pass: Validates.
"""


@pytest.fixture
def rubric(tmp_path):
    path = tmp_path / "provenance.yaml"
    path.write_text(RUBRIC, encoding="utf-8")
    return rubric_mod.load(path)


@pytest.fixture
def workdir(tmp_path):
    root = tmp_path / "work"
    (root / ".git").mkdir(parents=True)
    (root / ".git" / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")
    (root / "project.yaml").write_text("name: study\n", encoding="utf-8")
    return root


def replying(monkeypatch, *bodies, status=200):
    """Answer each call with the next body, so a three-judge panel can disagree."""
    sent = []
    queue = list(bodies)

    def fake(url, *, payload=None, api_key=None, timeout=0):
        sent.append(payload)
        content = queue.pop(0) if len(queue) > 1 else queue[0]
        return status, {"choices": [{"message": {"content": content}}]}

    monkeypatch.setattr(judge_mod, "request_json", fake)
    return sent


def verdict(**levels):
    return json.dumps(
        {"scores": [{"dimension": k, "level": v, "reason": "because"} for k, v in levels.items()]}
    )


# --------------------------------------------------------------------------- loading


def test_a_rubric_needs_dimensions_with_at_least_two_anchors(tmp_path):
    path = tmp_path / "bad.yaml"
    path.write_text("id: x\ndimensions:\n  - id: d\n    anchors: { only: one }\n", encoding="utf-8")

    with pytest.raises(rubric_mod.RubricError) as caught:
        rubric_mod.load(path)

    assert any("at least two `anchors`" in problem for problem in caught.value.problems)


def test_a_panel_size_the_rubric_invented_is_refused(tmp_path):
    path = tmp_path / "bad.yaml"
    path.write_text(RUBRIC + "judges: 2\n", encoding="utf-8")

    with pytest.raises(rubric_mod.RubricError) as caught:
        rubric_mod.load(path)

    assert any("`judges` is 2" in problem for problem in caught.value.problems)


def test_anchor_order_is_the_scale(rubric):
    assert rubric.dimension("reachability").levels == ("none", "partial", "complete")
    assert rubric.dimension("reachability").rank("partial") == 1


# --------------------------------------------------------------------------- blindness


def test_the_judge_is_never_told_what_the_task_expected(rubric, workdir, monkeypatch):
    sent = replying(monkeypatch, verdict(reachability="partial", ledger_validity="pass"))

    judge_mod.judge_task(
        rubric,
        endpoint=Endpoint("http://judge.invalid/v1"),
        model="ollama/gemma2:2b",
        final_text="I recorded the provenance.",
        workdir=workdir,
    )

    whole = json.dumps(sent)
    assert "expected" not in whole.lower() or "expected route" not in whole.lower()
    assert "dataset-release" not in whole
    assert "I recorded the provenance." in whole, "it does see the answer"
    assert "project.yaml" in whole, "and the artifacts"


def test_the_judge_is_not_shown_the_git_directory(rubric, workdir):
    text = judge_mod.artifacts(workdir)

    assert "project.yaml" in text
    assert "refs/heads/main" not in text


def test_a_judge_that_is_also_under_test_is_refused_before_anything_runs():
    with pytest.raises(judge_mod.JudgeError) as caught:
        judge_mod.refuse_self_judging("ollama/gemma2:2b", ["vllm/gemma2:2b"])

    assert "grading its own output" in str(caught.value)


# --------------------------------------------------------------------------- replies


def test_a_fenced_reply_with_a_preamble_still_parses(rubric):
    reply = "Sure, here you go:\n```json\n" + verdict(reachability="complete") + "\n```"

    (score,) = judge_mod.parse_reply(reply, rubric)

    assert (score.dimension, score.level) == ("reachability", "complete")


def test_a_level_the_rubric_does_not_declare_is_dropped(rubric):
    reply = verdict(reachability="excellent", ledger_validity="pass")

    scores = judge_mod.parse_reply(reply, rubric)

    assert [s.dimension for s in scores] == ["ledger_validity"], "a missing score stays missing"


def test_a_reply_that_is_not_json_is_an_error_not_a_zero(rubric):
    with pytest.raises(judge_mod.JudgeError):
        judge_mod.parse_reply("I would rather not.", rubric)


def test_an_endpoint_that_answers_with_an_error_is_recorded_not_raised(
    rubric, workdir, monkeypatch
):
    replying(monkeypatch, "irrelevant", status=503)

    opinion = judge_mod.ask_once(
        rubric,
        endpoint=Endpoint("http://judge.invalid/v1"),
        model="m",
        final_text="",
        workdir=workdir,
    )

    assert opinion.scores == ()
    assert "answered 503" in opinion.error


# --------------------------------------------------------------------------- the panel


def test_one_judge_by_default(rubric, workdir, monkeypatch):
    sent = replying(monkeypatch, verdict(reachability="partial", ledger_validity="pass"))

    judgement = judge_mod.judge_task(
        rubric,
        endpoint=Endpoint("http://judge.invalid/v1"),
        model="m",
        final_text="",
        workdir=workdir,
    )

    assert len(sent) == 1
    assert {s.dimension: s.level for s in judgement.consensus} == {
        "reachability": "partial",
        "ledger_validity": "pass",
    }


def test_three_judges_settle_on_a_majority(tmp_path, workdir, monkeypatch):
    path = tmp_path / "panel.yaml"
    path.write_text(RUBRIC + "judges: 3\n", encoding="utf-8")
    panel = rubric_mod.load(path)
    replying(
        monkeypatch,
        verdict(reachability="complete"),
        verdict(reachability="partial"),
        verdict(reachability="complete"),
    )

    judgement = judge_mod.judge_task(
        panel,
        endpoint=Endpoint("http://judge.invalid/v1"),
        model="m",
        final_text="",
        workdir=workdir,
    )

    assert len(judgement.opinions) == 3
    assert judgement.consensus[0].level == "complete"


def test_a_panel_with_no_majority_says_so(rubric):
    dimension = rubric.dimension("reachability")

    settled = judge_mod.settle(dimension, ["none", "partial", "complete"])

    assert settled.level == judge_mod.SPLIT
    assert "none, partial" in settled.reason


def test_a_tie_resolves_to_the_worse_level(rubric):
    dimension = rubric.dimension("reachability")

    settled = judge_mod.settle(dimension, ["partial", "complete"])

    assert settled.level == "partial", "the benefit of the doubt is not the judge's to give"


# --------------------------------------------------------------------------- report


def result(**extra):
    payload = {
        "task_id": "release",
        "model": "m",
        "condition": "routed",
        "repeat": 0,
        "outcome": "completed",
        "activations": [],
        "expected": {"primary": None, "agents": []},
        "passed": True,
        "verifiers": [{"kind": "command", "passed": True, "detail": "ran"}],
    }
    payload.update(extra)
    return payload


def graded(level):
    return {
        "rubric": "provenance",
        "judge_model": "m",
        "judges": 1,
        "consensus": [{"dimension": "reachability", "level": level, "reason": ""}],
        "opinions": [],
    }


def test_the_rubric_is_reported_beside_the_pass_rate_and_never_inside_it():
    results = [
        result(repeat=0, rubric=graded("complete")),
        result(repeat=1, rubric=graded("partial")),
    ]
    manifest = {"run_id": "01JRUN", "models": ["m"], "conditions": ["routed"], "preflight": {}}

    row = report_mod.build_report(results, manifest)["rows"][0]

    assert row["pass_rate"] == 1.0, "the judge cannot move a verifier's verdict"
    assert row["rubric"]["dimensions"] == {"reachability": {"complete": 1, "partial": 1}}
    text = report_mod.render_markdown(report_mod.build_report(results, manifest))
    assert "## Rubric dimensions" in text
    assert "complete x1, partial x1" in text


def test_a_judge_that_could_not_be_reached_is_stated_in_the_report():
    results = [
        result(rubric={"rubric": "provenance", "error": "the judge endpoint is unreachable"})
    ]
    manifest = {"run_id": "01JRUN", "models": ["m"], "conditions": ["routed"], "preflight": {}}

    built = report_mod.build_report(results, manifest)

    assert built["rows"][0]["rubric"]["error"] == "the judge endpoint is unreachable"
    assert "not graded" in report_mod.render_markdown(built)


def test_the_settled_level_keeps_the_judge_own_words(rubric):
    dimension = rubric.dimension("reachability")

    settled = judge_mod.settle(
        dimension,
        ["complete", "partial", "complete"],
        ["everything traces", "some gaps", "all of it"],
    )

    assert settled.level == "complete"
    assert settled.reason == "everything traces", "a summary of three would be nobody's reasoning"
