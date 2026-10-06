"""What a pilot report reads: what did not run, what it cost, judge panels, and model catalogues."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from test_judge import RUBRIC, replying, verdict
from test_leaderboard import loaded, result, write_run
from test_version_board import COMPONENT, V1, critical_file, unit, units
from test_version_board import write_run as write_versioned
from wikiskill import catalogue as catalogue_mod
from wikiskill import collection as collection_mod
from wikiskill import leaderboard
from wikiskill import report as report_mod
from wikiskill import rubric as rubric_mod
from wikiskill import version_board as board_mod
from wikiskill.cli import main
from wikiskill.collection import Role
from wikiskill.compare import load_run
from wikiskill.runner import run as run_mod
from wikiskill.runner.preflight import Endpoint
from wikiskill.score import judge as judge_mod

CATALOGUE = """
[models."qwen3:1.7b"]
family = "qwen"
size_b = 2.0

[models."qwen3:30b-a3b"]
family = "qwen"
size_b = 30.5
shape = "moe"

[models."granite4.1:3b"]
family = "granite"
size_b = 3

[models."gpt-oss:20b"]
family = "gpt-oss"
size_b = 20

[models."gpt-oss:120b"]
family = "gpt-oss"
size_b = 117
"""


@pytest.fixture
def catalogue(tmp_path):
    path = tmp_path / "models.toml"
    path.write_text(CATALOGUE, encoding="utf-8")
    return catalogue_mod.load(path)


def with_preflight(directory, preflight):
    manifest = json.loads((directory / "run.json").read_text())
    manifest["preflight"] = preflight
    (directory / "run.json").write_text(json.dumps(manifest))
    return directory


# --------------------------------------------------------------------------- preflight and cost


def test_the_leaderboard_lists_models_that_did_not_run(tmp_path):
    run = write_run(tmp_path, "r1", [result("t", "ollama/a", "routed", first="trace")])
    with_preflight(
        run,
        {
            "ollama/a": {"ok": True, "problems": []},
            "ollama/coder": {"ok": False, "problems": ["no structured tool call"]},
            "ollama/idle": {"ok": True, "problems": []},
        },
    )

    board = leaderboard.pool(loaded(run))

    assert board.preflight["failed"] == [
        {"model": "ollama/coder", "run_id": "r1", "problems": ["no structured tool call"]}
    ]
    assert board.preflight["no_units"] == [{"model": "ollama/idle", "run_id": "r1"}]
    text = leaderboard.render(board)
    assert "ollama/coder failed preflight in `r1`: no structured tool call" in text
    assert "ollama/idle passed preflight in `r1` but ran no unit" in text


def test_the_leaderboard_counts_outcomes_and_takes_medians_of_units_that_ran(tmp_path):
    rows = []
    for duration, outcome in ((1000, "completed"), (3000, "completed"), (600000, "infra_error")):
        row = result("t", "m", "routed", first="trace", outcome=outcome)
        row["duration_ms"] = duration
        row["tokens"] = {"input": duration, "output": duration // 10}
        rows.append(row)
    blocked = result("t", "m", "routed", outcome="permission_blocked")
    blocked["duration_ms"] = 5000
    rows.append(blocked)
    board = leaderboard.pool(loaded(write_run(tmp_path, "r1", rows)))

    entry = board.as_dict()["ranking"]["routed"][0]
    assert entry["outcomes"] == {"completed": 2, "infra_error": 1, "permission_blocked": 1}
    assert entry["median_duration_ms"] == 3000, "the infra_error unit did not run"
    assert entry["median_tokens"] == {"input": 2000, "output": 200}
    text = leaderboard.render(board)
    assert "## Outcomes and cost" in text
    assert "| m | routed | 2 | 1 | 1 | 3.0 | 2000/200 |" in text


def test_the_board_lists_models_that_did_not_run(tmp_path):
    run = write_versioned(tmp_path, "r1", V1, units("t", "a", "injected", 1, 0))
    with_preflight(run, {"llama3.3": {"ok": False, "problems": ["context 4096 < 16384"]}})

    board = board_mod.pool(loaded(run), COMPONENT)

    assert "llama3.3 failed preflight in `r1`: context 4096 < 16384" in board_mod.render(board)
    assert board.as_dict()["preflight"]["failed"][0]["model"] == "llama3.3"


# --------------------------------------------------------------------------- critical under OFF


def test_critical_failures_under_off_are_listed_and_disqualify_nothing(tmp_path):
    invented = [
        {"kind": "regex", "passed": False, "detail": "negated: DOI found"},
        {"kind": "command", "passed": False, "detail": "the task's own check"},
    ]
    run = write_versioned(
        tmp_path,
        "r1",
        V1,
        [
            unit("t", "mistral", "off", False, verifiers=invented),
            *units("t", "mistral", "off", 0, 1),
            *units("t", "mistral", "injected", 2, 0),
        ],
    )
    critical = board_mod.load_critical(critical_file(tmp_path, "- { task: '*', verifier: 0 }\n"))

    board = board_mod.pool(loaded(run), COMPONENT, critical=critical)

    assert not board.disqualified(V1)
    assert [u["detail"] for u in board.off_failures["mistral"]] == ["negated: DOI found"]
    text = board_mod.render(board)
    assert "- mistral: 1 of 2 OFF units" in text
    assert "No version failed a critical check." in text
    assert board.as_dict()["critical_failures_off"]["mistral"][0]["verifier"] == 0


# --------------------------------------------------------------------------- judge panels


def roles_from(body):
    problems = []
    found = collection_mod._parse_roles(body, problems)
    return found, problems


def test_a_judge_role_can_name_a_panel():
    found, problems = roles_from({"judge": {"base_url": "http://x/v1", "models": ["a", "b", "c"]}})
    assert problems == []
    assert found["judge"].panel == ("a", "b", "c")
    assert found["judge"].model == "a"


@pytest.mark.parametrize(
    ("body", "message"),
    [
        ({"judge": {"model": "a", "models": ["b", "c"]}}, "names `model` and `models`"),
        ({"judge": {"models": ["a"]}}, "two or more models"),
        ({"judge": {"models": []}}, "two or more models"),
        ({"judge": {"models": ["a", "A"]}}, "names a model twice"),
        ({"maintainer": {"models": ["a", "b"]}}, "is for the judge only"),
    ],
)
def test_a_malformed_panel_is_refused(body, message):
    _, problems = roles_from(body)
    assert any(message in problem for problem in problems)


def test_every_panel_model_is_checked_against_the_targets():
    coll = collection_mod.Collection(
        name="c",
        sources=(),
        watch={},
        roles={"judge": Role(name="judge", model="a", models=("a", "llama3.3"))},
        targets={"opencode": ("ollama/llama3.3",)},
    )
    (conflict,) = collection_mod.judge_target_conflicts(coll)
    assert "'llama3.3'" in conflict


def test_panel_slots():
    assert judge_mod.panel_slots(3, ["m"]) == ["m", "m", "m"]
    assert judge_mod.panel_slots(3, ["a", "b", "c"]) == ["a", "b", "c"]
    with pytest.raises(judge_mod.JudgeError, match=r"asks for 3 judge.*has 2 models"):
        judge_mod.panel_slots(3, ["a", "b"])


@pytest.fixture
def three_judge_rubric(tmp_path):
    path = tmp_path / "panel.yaml"
    path.write_text(RUBRIC + "judges: 3\n", encoding="utf-8")
    return path


def test_a_panel_asks_each_model_once_and_records_it(three_judge_rubric, monkeypatch, tmp_path):
    sent = replying(
        monkeypatch,
        verdict(reachability="complete"),
        verdict(reachability="partial"),
        verdict(reachability="complete"),
    )
    judgement = judge_mod.judge_task(
        rubric_mod.load(three_judge_rubric),
        endpoint=Endpoint("http://judge.invalid/v1"),
        model=("a", "b", "c"),
        final_text="",
        workdir=tmp_path,
    )

    assert [payload["model"] for payload in sent] == ["a", "b", "c"]
    record = judgement.as_dict()
    assert [o["model"] for o in record["opinions"]] == ["a", "b", "c"]
    assert record["judge_model"] == "a, b, c"
    assert judgement.consensus[0].level == "complete"


def test_a_panel_member_under_test_is_refused(three_judge_rubric, tmp_path):
    with pytest.raises(judge_mod.JudgeError, match="also under test"):
        judge_mod.judge_task(
            rubric_mod.load(three_judge_rubric),
            endpoint=Endpoint("http://judge.invalid/v1"),
            model=("a", "b", "c"),
            final_text="",
            workdir=tmp_path,
            models_under_test=["ollama/b"],
        )


def test_a_rubric_the_panel_cannot_fill_is_refused_before_any_unit(three_judge_rubric):
    coll = SimpleNamespace(
        name="c",
        roles={"judge": Role(name="judge", model="a", base_url="http://x/v1", models=("a", "b"))},
    )
    suite = SimpleNamespace(
        tasks=[SimpleNamespace(rubric=three_judge_rubric.name)], root=three_judge_rubric.parent
    )
    with pytest.raises(judge_mod.JudgeError, match="asks for 3 judge"):
        run_mod.panel_for(coll, suite, ["ollama/m"])


# --------------------------------------------------------------------------- delegations


def test_delegations_come_from_the_tool_call_with_the_whole_prompt():
    events = [
        {"type": "tool_call", "payload": {"tool": "read", "input": {"path": "x"}}},
        {
            "type": "tool_call",
            "payload": {
                "tool": "task",
                "input": {
                    "subagent_type": "archive-doer",
                    "description": "mint a DOI",
                    "prompt": "Mint v1.0 with zenodo; the token is unset.",
                },
            },
        },
        {"type": "delegation", "payload": {"subagent_type": "archive-doer"}},
    ]
    (found,) = judge_mod.delegations(events)
    assert found == judge_mod.Delegation(
        agent="archive-doer",
        description="mint a DOI",
        prompt="Mint v1.0 with zenodo; the token is unset.",
    )


def test_a_delegation_event_alone_still_names_the_agent():
    events = [{"type": "delegation", "payload": {"subagent_type": "bids-doer", "description": "d"}}]
    assert judge_mod.delegations(events) == [
        judge_mod.Delegation(agent="bids-doer", description="d")
    ]


def test_the_judge_sees_delegations_only_when_the_rubric_asks(tmp_path):
    path = tmp_path / "handoff.yaml"
    path.write_text(RUBRIC + "shows: [delegations]\n", encoding="utf-8")
    shown = rubric_mod.load(path)
    plain = rubric_mod.load(_plain(tmp_path))
    handoffs = [judge_mod.Delegation(agent="archive-doer", prompt="x" * 5000)]

    with_view = judge_mod.prompt_for(shown, final_text="", workdir=None, handoffs=handoffs)
    without = judge_mod.prompt_for(plain, final_text="", workdir=None, handoffs=handoffs)

    text = with_view[1]["content"]
    assert "to `archive-doer`" in text
    assert "(cut at 4000 of 5000 characters)" in text
    assert "archive-doer" not in without[1]["content"]


def _plain(tmp_path):
    path = tmp_path / "plain.yaml"
    path.write_text(RUBRIC, encoding="utf-8")
    return path


def test_an_unknown_shows_value_is_refused(tmp_path):
    path = tmp_path / "bad.yaml"
    path.write_text(RUBRIC + "shows: [expected]\n", encoding="utf-8")
    with pytest.raises(rubric_mod.RubricError, match="`shows`"):
        rubric_mod.load(path)


# --------------------------------------------------------------------------- the catalogue


def test_a_catalogue_matches_with_or_without_the_provider(catalogue):
    assert catalogue.family("ollama/qwen3:30b-a3b") == "qwen"
    assert catalogue.family("QWEN3:1.7b") == "qwen"
    assert catalogue.get("ollama/qwen3:30b-a3b").shape == "moe"
    assert catalogue.family("ollama/mistral:latest") is None


def test_a_catalogue_orders_families_by_their_smallest_model_then_by_size(catalogue):
    models = ["gpt-oss:120b", "zeta", "qwen3:30b-a3b", "granite4.1:3b", "gpt-oss:20b", "qwen3:1.7b"]
    assert catalogue.order(models) == [
        "qwen3:1.7b",
        "qwen3:30b-a3b",
        "granite4.1:3b",
        "gpt-oss:20b",
        "gpt-oss:120b",
        "zeta",
    ]


@pytest.mark.parametrize(
    ("body", "message"),
    [
        ('[models."a"]\nsize_b = 3\n', "needs a `family`"),
        ('[models."a"]\nfamily = "x"\nsize_b = "big"\n', "`size_b` must be a number"),
        ('[models."a"]\nfamily = "x"\ncolour = "red"\n', "unknown keys: colour"),
        ('family = "x"\n', "table per model"),
        ("[models\n", "not valid TOML"),
    ],
)
def test_a_malformed_catalogue_is_refused(tmp_path, body, message):
    path = tmp_path / "bad.toml"
    path.write_text(body, encoding="utf-8")
    with pytest.raises(catalogue_mod.CatalogueError, match=message):
        catalogue_mod.load(path)


def test_the_leaderboard_groups_by_family_with_a_catalogue(tmp_path, catalogue):
    rows = [
        result("t", model, "routed", first="trace")
        for model in ("ollama/gpt-oss:20b", "ollama/qwen3:30b-a3b", "ollama/qwen3:1.7b", "ollama/x")
    ]
    board = leaderboard.pool(loaded(write_run(tmp_path, "r1", rows)), catalogue)

    assert board.models_in_order == [
        "ollama/qwen3:1.7b",
        "ollama/qwen3:30b-a3b",
        "ollama/gpt-oss:20b",
        "ollama/x",
    ]
    assert board.uncatalogued == ["ollama/x"]
    entry = next(
        e for e in board.as_dict()["ranking"]["routed"] if e["model"] == "ollama/qwen3:1.7b"
    )
    assert (entry["family"], entry["size_b"]) == ("qwen", 2.0)
    text = leaderboard.render(board)
    assert "| family | size (B) |" in text and "uncatalogued: ollama/x" in text
    (header,) = [line for line in text.splitlines() if line.startswith("| task | basis |")]
    assert header.index("qwen3:1.7b") < header.index("qwen3:30b-a3b") < header.index("gpt-oss:20b")


def test_the_board_groups_by_family_with_a_catalogue(tmp_path, catalogue):
    run = write_versioned(
        tmp_path,
        "r1",
        V1,
        units("t", "ollama/qwen3:30b-a3b", "injected", 1, 0)
        + units("t", "ollama/granite4.1:3b", "injected", 1, 0)
        + units("t", "ollama/qwen3:1.7b", "injected", 1, 0),
    )
    board = board_mod.pool(loaded(run), COMPONENT, catalogue=catalogue)

    assert board.models == ["ollama/qwen3:1.7b", "ollama/qwen3:30b-a3b", "ollama/granite4.1:3b"]
    assert board.as_dict()["per_model"]["ollama/granite4.1:3b"]["family"] == "granite"
    assert "| ollama/qwen3:1.7b | qwen | 2 |" in board_mod.render(board)


# --------------------------------------------------------------------------- per-judge report


def judged(model, opinions):
    row = result("handoff", model, "routed", first="planner", passed=True)
    row["rubric"] = {
        "rubric": "handoff",
        "judge_model": ", ".join(m for m, _ in opinions),
        "judges": len(opinions),
        "consensus": [{"dimension": "sufficient", "level": "yes", "reason": ""}],
        "opinions": [
            {"model": m, "scores": [{"dimension": "sufficient", "level": lv, "reason": ""}]}
            for m, lv in opinions
        ],
    }
    return row


def test_the_report_gives_each_judges_levels(tmp_path):
    rows = [judged("ollama/qwen3:1.7b", [("gpt-oss:120b", "yes"), ("llama3.3", "no")])]
    report = report_mod.build_report(rows, {"run_id": "r", "models": ["ollama/qwen3:1.7b"]})

    (row,) = [r for r in report["rows"] if r.get("rubric")]
    assert row["rubric"]["judges"]["gpt-oss:120b"] == {"sufficient": {"yes": 1}}
    assert "same_family" not in row["rubric"]
    text = report_mod.render_markdown(report)
    assert "    - llama3.3: no x1" in text


def test_a_judge_of_the_models_own_family_is_marked_with_the_others_majority(catalogue):
    opinions = [("gpt-oss:120b", "yes"), ("llama3.3", "no"), ("nemotron", "no")]
    rows = [judged("ollama/gpt-oss:20b", opinions)]
    report = report_mod.build_report(rows, {"run_id": "r"}, catalogue)

    (row,) = [r for r in report["rows"] if r.get("rubric")]
    assert row["rubric"]["same_family"] == ["gpt-oss:120b"]
    assert row["rubric"]["others_majority"] == {"sufficient": {"no": 1}}
    text = report_mod.render_markdown(report)
    assert "gpt-oss:120b (same family): yes x1" in text
    assert "majority without the same family: no x1" in text


def test_the_report_command_rebuilds_a_run_with_a_catalogue(tmp_path, catalogue, capsys):
    opinions = [("gpt-oss:120b", "yes"), ("llama3.3", "no"), ("nemotron", "no")]
    run = write_run(tmp_path, "r1", [judged("ollama/gpt-oss:20b", opinions)])
    before = (run / "results.jsonl").read_text()

    code = main(["report", str(run), "--models-file", catalogue.source])

    assert code == 0
    assert "(same family)" in (run / "report.md").read_text()
    assert json.loads((run / "report.json").read_text())["run_id"] == "r1"
    assert (run / "results.jsonl").read_text() == before, "nothing is re-run or re-judged"
    assert load_run("", run).results


def test_the_report_command_refuses_what_it_cannot_read(tmp_path, capsys):
    assert main(["report", "nope"]) == 2
    assert "pass a path, or --collection" in capsys.readouterr().err
    run = write_run(tmp_path, "r1", [result("t", "m", "routed", first="trace")])
    assert main(["report", str(run), "--models-file", str(tmp_path / "missing.toml")]) == 2


def test_a_run_gives_the_judge_the_units_delegations(tmp_path, monkeypatch):
    (tmp_path / "handoff.yaml").write_text(RUBRIC + "shows: [delegations]\n", encoding="utf-8")
    sent = replying(monkeypatch, verdict(reachability="complete", ledger_validity="pass"))
    panel = run_mod.Panel(
        endpoint=Endpoint("http://judge.invalid/v1"),
        models=("judge-model",),
        suite_root=tmp_path,
        models_under_test=("ollama/m",),
    )
    trajectory = SimpleNamespace(
        unit=SimpleNamespace(task=SimpleNamespace(rubric="handoff.yaml")),
        scored=True,
        final_text="done",
        workdir=None,
        sessions=[{"id": "s"}],
        rubric=None,
        events=None,
    )
    call = {"subagent_type": "archive-doer", "description": "d", "prompt": "deposit v1.0"}
    backend = SimpleNamespace(
        normalize=lambda _t: [{"type": "tool_call", "payload": {"tool": "task", "input": call}}]
    )

    run_mod._judge(trajectory, panel, None, lambda _line: None, backend)

    prompt = sent[0]["messages"][1]["content"]
    assert "to `archive-doer`" in prompt and "deposit v1.0" in prompt
    assert trajectory.rubric["opinions"][0]["model"] == "judge-model"


# --------------------------------------------------------------------------- review fixes


def test_a_failed_or_non_agent_call_is_no_delegation_and_names_are_qualified():
    events = [
        {
            "type": "tool_call",
            "payload": {"tool": "Task", "ok": False, "input": {"subagent_type": "x"}},
        },
        {
            "type": "tool_call",
            "payload": {"tool": "bash", "input": {"agent": "y", "command": "ls"}},
        },
        {"type": "tool_call", "payload": {"tool": "Agent", "input": {"subagent_type": "dsh:bids"}}},
        {"type": "delegation", "payload": {"subagent_type": "x"}},
    ]
    assert judge_mod.delegations(events) == [judge_mod.Delegation(agent="dsh/bids")]


def test_a_failed_call_alone_is_not_replaced_by_its_delegation_event():
    events = [
        {"type": "tool_call", "payload": {"tool": "task", "ok": False, "input": {"agent": "x"}}},
        {"type": "delegation", "payload": {"subagent_type": "x"}},
    ]
    assert judge_mod.delegations(events) == []


def _delegation_unit(tmp_path, sessions):
    (tmp_path / "handoff.yaml").write_text(RUBRIC + "shows: [delegations]\n", encoding="utf-8")
    panel = run_mod.Panel(
        endpoint=Endpoint("http://judge.invalid/v1"),
        models=("judge-model",),
        suite_root=tmp_path,
        models_under_test=("ollama/m",),
    )
    trajectory = SimpleNamespace(
        unit=SimpleNamespace(task=SimpleNamespace(rubric="handoff.yaml")),
        scored=True,
        final_text="done",
        workdir=None,
        sessions=sessions,
        rubric=None,
        events=None,
    )
    return panel, trajectory


def test_missing_sessions_are_not_judged_as_no_delegation(tmp_path, monkeypatch):
    sent = replying(monkeypatch, verdict(reachability="complete", ledger_validity="pass"))
    panel, trajectory = _delegation_unit(tmp_path, [])
    backend = SimpleNamespace(normalize=lambda _t: [])

    run_mod._judge(trajectory, panel, None, lambda _line: None, backend)

    assert sent == []
    assert "not captured" in trajectory.rubric["error"]
    assert "unknown" in judge_mod.describe_delegations(None)


def test_events_are_normalized_once_for_the_judge_and_the_raw_log(tmp_path, monkeypatch):
    replying(monkeypatch, verdict(reachability="complete", ledger_validity="pass"))
    panel, trajectory = _delegation_unit(tmp_path, [{"id": "s"}])
    calls = []

    def normalize(_t):
        calls.append(1)
        return []

    backend = SimpleNamespace(normalize=normalize)
    run_mod._judge(trajectory, panel, None, lambda _line: None, backend)
    run_mod._write_events(backend, trajectory, tmp_path)
    assert len(calls) == 1


def test_a_session_that_cannot_be_read_is_a_judge_error(tmp_path):
    panel, trajectory = _delegation_unit(tmp_path, [{"id": "s"}])

    def normalize(_t):
        raise ValueError("bad session")

    run_mod._judge(
        trajectory, panel, None, lambda _line: None, SimpleNamespace(normalize=normalize)
    )
    assert "could not be read: bad session" in trajectory.rubric["error"]


def test_only_the_selected_tasks_rubrics_must_fit_the_panel(three_judge_rubric):
    coll = SimpleNamespace(
        name="c",
        roles={"judge": Role(name="judge", model="a", base_url="http://x/v1", models=("a", "b"))},
    )
    other = SimpleNamespace(rubric=None)
    suite = SimpleNamespace(
        tasks=[SimpleNamespace(rubric=three_judge_rubric.name), other],
        root=three_judge_rubric.parent,
    )
    assert run_mod.panel_for(coll, suite, ["ollama/m"], [other]) == (None, None)


def test_a_preflight_without_ok_is_a_failure_in_every_output(tmp_path):
    run = write_run(tmp_path, "r1", [result("t", "ollama/a", "routed", first="trace")])
    with_preflight(run, {"ollama/a": {"ok": True}, "ollama/old": {}})
    (manifest_run,) = loaded(run)

    board = leaderboard.pool([manifest_run])
    report = report_mod.build_report(list(manifest_run.results), manifest_run.manifest)

    assert board.preflight["failed"] == [
        {"model": "ollama/old", "run_id": "r1", "problems": ["preflight failed"]}
    ]
    assert [e["model"] for e in report["not_run"] if e["kind"] == "preflight"] == ["ollama/old"]


def test_the_others_majority_counts_every_repeat_and_follows_settle(catalogue):
    first = judged("ollama/gpt-oss:20b", [("llama3.3", "partial"), ("nemotron", "complete")])
    first["rubric"]["scales"] = {"sufficient": ["none", "partial", "complete"]}
    second = judged(
        "ollama/gpt-oss:20b",
        [("gpt-oss:120b", "complete"), ("llama3.3", "complete"), ("nemotron", "complete")],
    )
    report = report_mod.build_report([first, second], {"run_id": "r"}, catalogue)

    (row,) = [r for r in report["rows"] if r.get("rubric")]
    assert row["rubric"]["others_majority"] == {"sufficient": {"partial": 1, "complete": 1}}


def test_a_tie_without_a_recorded_scale_stays_split():
    assert report_mod._majority("d", ["a", "b"], None) == judge_mod.SPLIT
    assert report_mod._majority("d", ["a", "a", "b", "c"], None) == "a"


def test_panel_models_are_stripped():
    found, problems = roles_from({"judge": {"base_url": "http://x/v1", "models": [" a", "b "]}})
    assert problems == []
    assert found["judge"].panel == ("a", "b")


def test_the_board_says_when_no_off_unit_ran(tmp_path):
    run = write_versioned(tmp_path, "r1", V1, units("t", "m", "injected", 1, 0))
    critical = board_mod.load_critical(critical_file(tmp_path, "- { task: '*', verifier: 0 }\n"))
    text = board_mod.render(board_mod.pool(loaded(run), COMPONENT, critical=critical))
    assert "No OFF unit ran, so the bare models were not checked." in text
    assert "No OFF unit failed" not in text
