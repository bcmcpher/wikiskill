"""The OpenCode backend: isolation, the normaliser over recorded sessions, and run layout.

No test here runs `opencode`. The sessions are recorded fixtures — one of them captured from a real
1.18.31 run against a local Ollama model — so the normaliser's contract is checked without a model,
a GPU, or fifteen minutes of CPU inference.
"""

from __future__ import annotations

import json

import pytest

from conftest import FIXTURES, write_manifest
from wikiskill import collection as collection_mod
from wikiskill import rawlog
from wikiskill.runner import base as runner_base
from wikiskill.runner import opencode as backend_mod
from wikiskill.runner.preflight import Endpoint

OPENCODE = FIXTURES / "opencode"

#: A valid ULID, because a run id is one and every event carries it.
RUN_ID = "01ABCDEFGHJKMNPQRSTVWXYZ01"

MANIFEST = """
name = "toy"
sources = [{{ path = "{source}", layout = "opencode" }}]

[watch]
skills = ["*"]
agents = ["*"]
commands = []

[targets]
opencode = ["small"]

[aliases.opencode]
small = "ollama/qwen2.5-coder:1.5b"
"""


def load(name):
    return json.loads((OPENCODE / name).read_text(encoding="utf-8"))


@pytest.fixture
def toy_collection(xdg, opencode_source):
    write_manifest(xdg, "toy", MANIFEST.format(source=opencode_source))
    return collection_mod.load("toy")


@pytest.fixture
def backend(tmp_path, toy_collection):
    layout = runner_base.RunLayout.create("toy", RUN_ID, base=tmp_path)
    return backend_mod.OpenCodeBackend(
        collection=toy_collection,
        endpoint=Endpoint("http://localhost:11434/v1"),
        layout=layout,
        suite_root=tmp_path,
        executable="/nonexistent/opencode",
    )


def unit(condition="routed", task=None, repeat=0):
    from wikiskill.suite import Route, Task

    task = task or Task(
        id="release",
        prompt="Cut version 1.0 so the paper can cite a fixed version.",
        split="val",
        expect=Route(skill="dataset-release", agents=("datalad-doer",)),
        guard_deny=("datalad push*",),
        repeats=1,
    )
    return runner_base.Unit(
        run_id=RUN_ID,
        suite="toy",
        task=task,
        model="ollama/qwen2.5-coder:1.5b",
        condition=condition,
        repeat=repeat,
    )


def trajectory(sessions, condition="routed"):
    return runner_base.Trajectory(
        unit=unit(condition=condition),
        outcome="completed",
        sessions=sessions,
        session_id="ses_root0000000000000000001",
        duration_ms=30000,
    )


# --------------------------------------------------------------------------- isolation


def test_the_inline_config_carries_only_the_target_provider(backend):
    config = backend.config_for(unit())

    assert list(config["provider"]) == ["ollama"]
    assert list(config["provider"]["ollama"]["models"]) == ["qwen2.5-coder:1.5b"]
    assert config["mcp"] == {}, "no MCP server reaches an evaluation"
    assert config["autoupdate"] is False
    assert config["share"] == "disabled"
    assert config["permission"]["webfetch"] == "deny"
    assert config["permission"]["external_directory"] == "deny"


def test_the_environment_isolates_xdg_and_disables_discovery(backend, tmp_path):
    environment = backend.env_for(unit(), tmp_path / "root")

    for variable in ("XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_STATE_HOME", "XDG_CACHE_HOME"):
        assert environment[variable].startswith(str(tmp_path)), variable
    assert environment["OPENCODE_DISABLE_PROJECT_CONFIG"] == "true"
    assert environment["OPENCODE_DISABLE_CLAUDE_CODE"] == "1"
    assert "OPENCODE_CONFIG" not in environment
    assert json.loads(environment["OPENCODE_CONFIG_CONTENT"])["mcp"] == {}


def test_the_guard_denies_the_task_patterns_and_the_base_ones(backend, tmp_path):
    deny = json.loads(backend.env_for(unit(), tmp_path / "root")["WIKISKILL_GUARD_DENY"])

    assert "datalad push*" in deny, "the task's own deny list"
    assert "git push*" in deny, "and the patterns no evaluation may run"


def test_preparing_a_unit_creates_a_git_workdir(backend):
    workdir = backend.prepare(unit(condition="off"))

    assert workdir.is_dir()
    assert (workdir / ".git").is_dir()
    assert (workdir.parent / "config.json").is_file()


def test_routed_installs_the_collection_into_the_run_and_nowhere_else(backend, xdg):
    workdir = backend.prepare(unit(condition="routed"))
    config = workdir.parent / "config" / "opencode"

    assert (config / "skills" / "smoke" / "SKILL.md").is_file(), (
        "the component under test is installed into the run's own config"
    )
    assert (config / "commands" / "smoke-check.md").is_file(), (
        "and so is every other component the collection declares, watched or not"
    )
    assert not (config / "plugin").exists(), "no logger: the runner normalises the run itself"
    assert not (xdg["config"] / "wikiskill" / "runtime.json").exists(), (
        "an evaluation never writes into the user's own configuration"
    )


def test_off_installs_nothing_at_all(backend):
    workdir = backend.prepare(unit(condition="off"))
    assert not (workdir.parent / "config" / "opencode").exists()


def test_a_missing_fixture_directory_is_an_error_not_an_empty_run(backend):
    from wikiskill.suite import Route, Task

    task = Task(
        id="fixtured",
        prompt="Do the thing.",
        split="val",
        expect=Route(skill="dataset-release"),
        fixtures="not-there",
    )
    with pytest.raises(runner_base.RunnerError, match="fixture directory"):
        backend.prepare(unit(condition="off", task=task))


# --------------------------------------------------------------------------- normalising


def test_every_event_validates_and_carries_its_evaluation_provenance(backend):
    events = backend.normalize(trajectory([load("session-root.json")]))

    assert events, "a recorded session produces events"
    for event in events:
        assert rawlog.schema_errors(event) == [], event
        assert event["origin"] == "eval"
        assert event["eval"] == {
            "run_id": RUN_ID,
            "suite": "toy",
            "task_id": "release",
            "condition": "routed",
            "repeat": 0,
        }
        assert event["harness"] == "opencode"
        assert event["provider"] == "ollama"
        assert event["model"] == "qwen2.5-coder:1.5b"


def test_the_session_reads_as_one_trajectory_in_order(backend):
    events = backend.normalize(trajectory([load("session-root.json")]))
    types = [event["type"] for event in events]

    assert types[0] == "session_start"
    assert types[-1] == "session_end"
    assert types.index("component_activated") < types.index("delegation")
    assert "step_usage" in types and "assistant_turn" in types


def test_a_skill_call_is_an_activation_attributed_to_what_followed(backend):
    events = backend.normalize(trajectory([load("session-root.json")]))
    activation = next(event for event in events if event["type"] == "component_activated")

    assert activation["component"]["kind"] == "skill"
    assert activation["component"]["name"] == "dataset-release"
    assert activation["payload"]["trigger"] == "skill_tool"

    delegation = next(event for event in events if event["type"] == "delegation")
    assert delegation["component"]["name"] == "datalad-doer", (
        "events are attributed to the component most recently activated"
    )


def test_a_delegation_names_the_child_session(backend):
    events = backend.normalize(trajectory([load("session-root.json")]))
    delegation = next(event for event in events if event["type"] == "delegation")

    assert delegation["payload"]["subagent_type"] == "datalad-doer"
    assert delegation["payload"]["child_session_id"] == "ses_child000000000000000001"


def test_a_child_session_is_written_into_its_root(backend):
    events = backend.normalize(trajectory([load("session-root.json"), load("session-child.json")]))
    child = [event for event in events if event["session_id"] == "ses_child000000000000000001"]

    assert child, "the child session's events are present"
    for event in child:
        assert event["root_session_id"] == "ses_root0000000000000000001"
        assert event["parent_session_id"] == "ses_root0000000000000000001"


def test_a_blocked_tool_call_is_recorded_as_a_failed_call(backend):
    events = backend.normalize(trajectory([load("session-child.json")]))
    call = next(event for event in events if event["type"] == "tool_call")

    assert call["payload"]["ok"] is False
    assert "evaluation guard" in call["payload"]["error"]
    assert call["payload"]["duration_ms"] == 50


def test_token_usage_comes_from_step_parts():
    assert backend_mod._token_totals([load("session-root.json")]) == {
        "input": 1200,
        "output": 90,
        "reasoning": 0,
    }


def test_child_session_ids_are_found_for_export():
    assert backend_mod._child_session_ids(load("session-root.json")) == [
        "ses_child000000000000000001"
    ]


def test_activations_record_what_was_chosen_in_order():
    assert backend_mod.activations([load("session-root.json")]) == [
        {"kind": "skill", "name": "dataset-release"},
        {"kind": "agent", "name": "datalad-doer"},
    ]


def test_a_recorded_failed_run_still_normalises(backend):
    """The real capture: a model that cannot be given tools, exported as a session with an error."""
    events = backend.normalize(
        runner_base.Trajectory(
            unit=unit(condition="off"),
            outcome="api_error",
            sessions=[load("session-no-tools.json")],
            session_id="ses_f4a3ed652ffecYIWtPMgVDXDul",
        )
    )

    for event in events:
        assert rawlog.schema_errors(event) == [], event
    error = next(event for event in events if event["type"] == "error")
    assert "does not support tools" in error["payload"]["message"]


# --------------------------------------------------------------------------- run layout


def test_a_run_directory_holds_the_manifest_results_and_reports(tmp_path):
    layout = runner_base.RunLayout.create("toy", RUN_ID, base=tmp_path)
    layout.write_manifest({"run_id": layout.run_id})
    layout.append_result({"task_id": "release", "outcome": "completed"})
    layout.append_result({"task_id": "release", "outcome": "skipped"})

    assert layout.root == tmp_path / RUN_ID
    assert json.loads(layout.manifest.read_text())["run_id"] == layout.run_id
    assert [entry["outcome"] for entry in layout.read_results()] == ["completed", "skipped"]


def test_unit_slugs_are_unique_and_filesystem_safe():
    first = unit(repeat=0).slug
    second = unit(repeat=1).slug

    assert first != second
    assert "/" not in first and ":" not in first


def test_units_cover_every_model_condition_task_and_repeat():
    from wikiskill.suite import Route, Suite, Task

    suite = Suite(
        name="toy",
        tasks=(
            Task(id="a", prompt="p", split="val", expect=Route(skill="x"), repeats=2),
            Task(id="b", prompt="q", split="val", expect=Route(skill="y"), repeats=1),
        ),
    )
    units = runner_base.units_for(
        suite, run_id="01JRUN", models=["m1", "m2"], conditions=["off", "routed"]
    )

    assert len(units) == 2 * 2 * 3
    assert units[0].model == "m1", "a model is finished before the next one is pulled"
    assert units[-1].model == "m2"
