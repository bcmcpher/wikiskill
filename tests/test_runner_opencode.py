"""The OpenCode backend: isolation, the normaliser over recorded sessions, and run layout.

No test here runs `opencode`. The sessions are recorded fixtures — one of them captured from a real
1.18.31 run against a local Ollama model — so the normaliser's contract is checked without a model,
a GPU, or fifteen minutes of CPU inference.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from conftest import FIXTURES, write_manifest
from wikiskill import collection as collection_mod
from wikiskill import rawlog
from wikiskill.frontmatter import read as read_frontmatter
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


def test_a_tasks_env_reaches_the_harness_process_below_the_isolation(backend, tmp_path):
    import dataclasses

    base = unit()
    task = dataclasses.replace(
        base.task, env=(("DATALAD_AUTOSAVE", "0"), ("XDG_CONFIG_HOME", "/home/me/.config"))
    )
    environment = backend.env_for(dataclasses.replace(base, task=task), tmp_path / "root")

    assert environment["DATALAD_AUTOSAVE"] == "0"
    assert environment["XDG_CONFIG_HOME"].startswith(str(tmp_path)), (
        "even a task built past the suite check cannot undo the run's isolation"
    )


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


def test_routed_installs_agents_on_the_model_under_test(tmp_path, xdg, plugin_source):
    """A pinned doer would put two models in one row; the run strips every pin."""
    doer = plugin_source / "datalad" / "agents" / "datalad-doer.md"
    doer.write_text(
        "---\nname: datalad-doer\ndescription: d\ntools: Read, Bash\nmodel: haiku\n---\n\nb\n",
        encoding="utf-8",
    )
    write_manifest(
        xdg,
        "dsh",
        f'name = "dsh"\nsources = [{{ path = "{plugin_source}", layout = "claude-plugin", '
        'plugins = ["datalad"] }]\n[watch]\nagents = ["datalad/datalad-doer"]\n'
        '[aliases.opencode]\nhaiku = "ollama/qwen3:1.7b"\n',
    )
    backend = backend_mod.OpenCodeBackend(
        collection=collection_mod.load("dsh"),
        endpoint=Endpoint("http://localhost:11434/v1"),
        layout=runner_base.RunLayout.create("dsh", RUN_ID, base=tmp_path),
        suite_root=tmp_path,
        executable="/nonexistent/opencode",
    )
    config = backend.prepare(unit(condition="routed")).parent / "config" / "opencode"

    meta = read_frontmatter(config / "agents" / "datalad-doer.md").meta
    assert "model" not in meta
    assert meta["permission"]["bash"] == "allow"
    assert not (config / "skills").exists(), "only the selected plugin is installed"


def with_setup(*commands, env=()):
    import dataclasses

    base = unit(condition="off")
    return dataclasses.replace(
        base, task=dataclasses.replace(base.task, setup=tuple(commands), env=tuple(env))
    )


def test_setup_builds_the_starting_state_with_the_tasks_env(backend):
    workdir = backend.prepare(with_setup('printf "$MARK" > state.txt', env=(("MARK", "ready"),)))

    assert (workdir / "state.txt").read_text() == "ready"
    assert (workdir / ".git").is_dir(), "the workdir is still a repository after setup"
    assert "$ printf" in (workdir.parent / "setup.log").read_text()


def test_a_failing_setup_is_an_infrastructure_error(backend):
    trajectory = backend.execute(with_setup("true", "echo nope >&2; exit 3", "touch never"))

    assert trajectory.outcome == "infra_error"
    assert "exited 3" in trajectory.reason and "nope" in trajectory.reason
    assert not (backend.layout.unit_dir(trajectory.unit) / "work" / "never").exists()


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


# --------------------------------------------------------------------------- harness preflight


@pytest.fixture
def harness_backend(tmp_path, toy_collection):
    """A backend for a model the harness resolves itself, so there is no endpoint to address."""
    layout = runner_base.RunLayout.create("toy", RUN_ID, base=tmp_path)
    return backend_mod.OpenCodeBackend(
        collection=toy_collection,
        endpoint=None,
        layout=layout,
        suite_root=tmp_path,
        executable="/nonexistent/opencode",
    )


def test_a_harness_served_model_gets_no_synthetic_provider_block(harness_backend):
    """Declaring one would replace the credential and routing the harness supplies for its own."""
    config = harness_backend.config_for(unit())

    assert "provider" not in config
    assert config["mcp"] == {}, "isolation is unchanged by leaving the provider alone"
    assert config["share"] == "disabled"


def test_the_probe_passes_on_a_real_tool_call():
    stream = backend_mod._parse_stream(
        (OPENCODE / "probe-tool-call.ndjson").read_text(encoding="utf-8")
    )

    assert backend_mod._stream_tool_calls(stream) == ["write"]
    assert (
        backend_mod.probe_verdict(stream, produced_file=True, model="opencode/big-pickle") is None
    )


def test_the_file_alone_proves_the_call():
    """A stream shape this parser has not seen must not fail a model that did the work."""
    assert backend_mod.probe_verdict([], produced_file=True, model="m") is None


def test_a_printed_tool_call_fails_the_probe():
    stream = [{"part": {"type": "text", "text": '{"tool_call": {"name": "write"}}'}}]
    verdict = backend_mod.probe_verdict(stream, produced_file=False, model="m")

    assert verdict is not None
    assert "printed a tool call instead of making one" in verdict


def test_a_probe_error_is_reported_in_the_harness_own_words():
    stream = [{"type": "error", "error": {"data": {"message": "model does not support tools"}}}]
    verdict = backend_mod.probe_verdict(stream, produced_file=False, model="m")

    assert "does not support tools" in verdict


def test_a_silent_probe_names_the_file_it_did_not_write():
    stream = [{"part": {"type": "text", "text": "Sure, I would create that file."}}]
    verdict = backend_mod.probe_verdict(stream, produced_file=False, model="m")

    assert "probe.txt" in verdict


CATALOG = {
    "opencode": {"models": {"big-pickle": {"limit": {"context": 200000, "output": 32000}}}},
    "tiny": {"models": {"small": {"limit": {"output": 512}}}},
}


def test_context_comes_from_the_catalog_the_run_itself_fetched():
    context, source = backend_mod.catalog_context(CATALOG, "opencode/big-pickle")

    assert context == 200000
    assert "models.dev" in source


def test_a_model_the_catalog_does_not_describe_reports_no_context():
    assert backend_mod.catalog_context(CATALOG, "tiny/small") == (None, "unknown")
    assert backend_mod.catalog_context(CATALOG, "who/knows") == (None, "unknown")


def test_an_unlisted_model_is_refused_before_a_single_token_is_spent(harness_backend, monkeypatch):
    probed = []
    monkeypatch.setattr(type(harness_backend), "version", lambda self: "1.18.31")
    monkeypatch.setattr(
        type(harness_backend), "_harness_models", lambda self, env: ["opencode/big-pickle"]
    )
    monkeypatch.setattr(
        type(harness_backend), "_probe", lambda self, *a: probed.append(a) or ([], False)
    )

    result = harness_backend.preflight("opencode/no-such-model")

    assert result.ok is False
    assert probed == [], "a name the harness does not offer is not worth paying to probe"
    assert "does not offer" in result.reason
    assert "big-pickle" in result.reason, "and the reason names what it does offer"


def test_a_tool_calling_model_with_a_large_context_passes(harness_backend, monkeypatch):
    stream = backend_mod._parse_stream(
        (OPENCODE / "probe-tool-call.ndjson").read_text(encoding="utf-8")
    )
    monkeypatch.setattr(type(harness_backend), "version", lambda self: "1.18.31")
    monkeypatch.setattr(
        type(harness_backend), "_harness_models", lambda self, env: ["opencode/big-pickle"]
    )
    monkeypatch.setattr(type(harness_backend), "_probe", lambda self, *a: (stream, True))
    monkeypatch.setattr(backend_mod, "_read_catalog", lambda cache_root: CATALOG)

    result = harness_backend.preflight("opencode/big-pickle")

    assert result.ok, result.problems
    assert result.details["via"] == "harness"
    assert result.details["context_tokens"] == 200000
    assert result.details["probe_tools"] == ["write"]


def test_a_small_context_is_refused_with_the_number_and_its_source(harness_backend, monkeypatch):
    monkeypatch.setattr(type(harness_backend), "version", lambda self: "1.18.31")
    monkeypatch.setattr(type(harness_backend), "_harness_models", lambda self, env: [])
    monkeypatch.setattr(type(harness_backend), "_probe", lambda self, *a: ([], True))
    monkeypatch.setattr(
        backend_mod,
        "_read_catalog",
        lambda cache_root: {"opencode": {"models": {"cramped": {"limit": {"context": 8192}}}}},
    )

    result = harness_backend.preflight("opencode/cramped")

    assert result.ok is False
    assert "8192-token context" in result.reason
    assert "models.dev" in result.reason


# --------------------------------------------------------------------------- INJECTED


def injected_unit(**route):
    from wikiskill.suite import Route, Task

    return unit(
        condition="injected",
        task=Task(
            id="release",
            prompt="Cut version 1.0.",
            split="val",
            expect=Route(**route),
            repeats=1,
        ),
    )


def prepared(backend, target):
    """Run `prepare` and hand back the run root, which is where the built skill lands."""
    backend.prepare(target)
    return backend.layout.unit_dir(target)


def test_injected_supplies_the_skill_text_and_forbids_loading_it(backend):
    target = injected_unit(skill="smoke")
    root = prepared(backend, target)

    config = backend.config_for(target, root)

    (instruction,) = config["instructions"]
    assert instruction.endswith("skills/smoke/SKILL.md")
    assert Path(instruction).is_file(), "the file has to exist, or OpenCode injects nothing"
    assert config["permission"]["skill"] == {"smoke": "deny"}


def test_injected_takes_the_component_half_of_a_plugin_qualified_name(backend):
    target = injected_unit(skill="govern/smoke")
    root = prepared(backend, target)

    config = backend.config_for(target, root)

    assert config["permission"]["skill"] == {"smoke": "deny"}


def test_injected_says_so_when_the_collection_built_no_such_skill(backend):
    target = injected_unit(skill="absent")
    root = prepared(backend, target)

    with pytest.raises(backend_mod.RunnerError) as caught:
        backend.config_for(target, root)

    assert "built no skill" in str(caught.value)


def add_doer(opencode_source):
    (opencode_source / "agents").mkdir(exist_ok=True)
    (opencode_source / "agents" / "datalad-doer.md").write_text(
        "---\nname: datalad-doer\ndescription: d\ntools: Read, Bash\n---\n\nbody\n",
        encoding="utf-8",
    )


def test_an_injected_agent_is_run_directly_instead(backend, opencode_source):
    add_doer(opencode_source)
    target = injected_unit(agent="datalad/datalad-doer")
    root = prepared(backend, target)

    config = backend.config_for(target, root)

    assert "instructions" not in config, "an agent needs no text forced in; it is invoked directly"
    assert "skill" not in config.get("permission", {})
    assert backend_mod._injected_agent(target) == "datalad-doer"


def test_an_injected_agent_can_be_run_as_the_primary_agent(backend, opencode_source):
    """`opencode run --agent` refuses a subagent and silently falls back to its default agent."""
    add_doer(opencode_source)
    root = prepared(backend, injected_unit(agent="datalad/datalad-doer"))
    meta = read_frontmatter(root / "config" / "opencode" / "agents" / "datalad-doer.md").meta
    assert meta["mode"] == "all"
    assert meta["permission"]["bash"] == "allow", "promotion changes the mode and nothing else"


def test_routed_keeps_agents_as_subagents(backend, opencode_source):
    add_doer(opencode_source)
    config = backend.prepare(unit(condition="routed")).parent / "config" / "opencode"
    assert read_frontmatter(config / "agents" / "datalad-doer.md").meta["mode"] == "subagent"


def test_an_injected_agent_missing_from_the_collection_is_refused(backend):
    with pytest.raises(runner_base.RunnerError, match="built none"):
        backend.prepare(injected_unit(agent="datalad/datalad-doer"))


def test_a_session_that_ran_another_agent_is_flagged(opencode_source):
    target = injected_unit(agent="datalad/datalad-doer")
    fell_back = [{"info": {"agent": "build"}, "messages": []}]
    ran_it = [{"info": {"agent": "datalad-doer"}, "messages": []}]
    assert "the session ran 'build'" in backend_mod.agent_mismatch(target, fell_back)
    assert backend_mod.agent_mismatch(target, ran_it) is None
    assert backend_mod.agent_mismatch(unit(condition="off"), fell_back) is None


def test_routed_and_off_are_untouched_by_any_of_this(backend):
    for condition in ("off", "routed"):
        config = backend.config_for(unit(condition=condition), backend.layout.root)
        assert "instructions" not in config
        assert "skill" not in config["permission"]


# --------------------------------------------------------------------------- export


def stub_opencode(tmp_path, body: str):
    """A stand-in for `opencode export`, so the failure modes can be produced on demand."""
    script = tmp_path / "stub-opencode"
    script.write_text("#!/bin/sh\n" + body + "\n", encoding="utf-8")
    script.chmod(0o755)
    return str(script)


def exporting(backend, tmp_path, body: str):
    backend.executable = stub_opencode(tmp_path, body)
    return backend


def test_a_session_is_exported_to_a_file_not_a_pipe(backend, tmp_path):
    """`opencode export` exits without draining a pipe, so anything past 64 KiB is truncated."""
    big = json.dumps({"info": {"id": "ses_big"}, "messages": [], "pad": "x" * 200_000})
    payload = tmp_path / "payload.json"
    payload.write_text(big, encoding="utf-8")
    exporting(backend, tmp_path, f'cat "{payload}"')

    (session,) = backend.export_sessions("ses_big", tmp_path / "root")

    assert len(session["pad"]) == 200_000
    written = (tmp_path / "root" / "exports" / "ses_big.json").read_text(encoding="utf-8")
    assert len(written) > 65536, "the whole export is kept on disk beside the run"


def test_a_truncated_export_is_an_error_not_an_empty_session_list(backend, tmp_path):
    exporting(backend, tmp_path, 'printf \'{"info": {"id": "ses_x"}, "messages": [\'')

    with pytest.raises(backend_mod.RunnerError) as caught:
        backend.export_sessions("ses_x", tmp_path / "root")

    assert "not readable JSON" in str(caught.value)


def test_a_failed_export_reports_the_harness_own_words(backend, tmp_path):
    exporting(backend, tmp_path, 'echo "no such session" >&2; exit 3')

    with pytest.raises(backend_mod.RunnerError) as caught:
        backend.export_sessions("ses_gone", tmp_path / "root")

    assert "exited 3" in str(caught.value)
    assert "no such session" in str(caught.value)
