"""The Claude Code backend: isolation, the command it runs, and reading stream-json back.

The streams are real: captured from Claude Code 2.1.289 driving local Ollama models through a
throwaway plugin `capture` (skill `word-count`, agent `counter`). See the `add-claude-code-adapter`
tasks for how. The capture predates the isolation settings, so its sessions were offered Claude
Code's own skills too, and executing it as a unit is rightly an isolation failure.
"""

from __future__ import annotations

import json
import os
import stat

import pytest

from conftest import FIXTURES, write_manifest
from wikiskill import collection as collection_mod
from wikiskill import rawlog
from wikiskill.runner import base as runner_base
from wikiskill.runner import claude as backend_mod
from wikiskill.runner.preflight import Endpoint

CLAUDE = FIXTURES / "claude-code"
SUBAGENT = CLAUDE / "stream-subagent-2.1.289.jsonl"
SKILL_ONLY = CLAUDE / "stream-skill-2.1.289.jsonl"
RUN_ID = "01ABCDEFGHJKMNPQRSTVWXYZ01"

MANIFEST = """
name = "capture"
sources = [{{ path = "{source}", layout = "claude-plugin" }}]

[watch]
skills = ["*"]
agents = ["*"]
commands = []
"""


def stream(path=SUBAGENT):
    return backend_mod.parse_stream(path.read_text(encoding="utf-8"))


@pytest.fixture
def capture_source(tmp_path):
    root = tmp_path / "plugins"
    skill = root / "capture" / "skills" / "word-count"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text(
        "---\nname: word-count\ndescription: Count the words in a file.\n---\n\n"
        "Delegate to the `counter` agent.\n",
        encoding="utf-8",
    )
    (root / "capture" / "agents").mkdir()
    (root / "capture" / "agents" / "counter.md").write_text(
        "---\nname: counter\ndescription: Counts words.\nmodel: sonnet\n---\n\nRun wc -w.\n",
        encoding="utf-8",
    )
    return root


@pytest.fixture
def capture(xdg, capture_source):
    write_manifest(xdg, "capture", MANIFEST.format(source=capture_source))
    return collection_mod.load("capture")


def make_backend(tmp_path, collection, endpoint=None, executable="/nonexistent/claude", **kw):
    layout = runner_base.RunLayout.create("capture", RUN_ID, base=tmp_path / "runs")
    return backend_mod.ClaudeCodeBackend(
        collection=collection,
        endpoint=endpoint,
        layout=layout,
        suite_root=tmp_path,
        executable=executable,
        **kw,
    )


@pytest.fixture
def backend(tmp_path, capture):
    return make_backend(tmp_path, capture, Endpoint("http://localhost:11434/v1"))


def unit(condition="routed", expect=None, max_steps=None):
    from wikiskill.suite import Route, Task

    task = Task(
        id="count",
        prompt="How many words does notes.txt have?",
        split="val",
        expect=expect or Route(skill="capture/word-count", agents=("capture/counter",)),
        guard_deny=("git push*",),
        repeats=1,
        max_steps=max_steps,
    )
    return runner_base.Unit(
        run_id=RUN_ID,
        suite="toy",
        task=task,
        model="ollama/qwen3:30b-a3b",
        condition=condition,
        repeat=0,
    )


def trajectory(events, condition="routed"):
    return runner_base.Trajectory(
        unit=unit(condition=condition),
        outcome="completed",
        sessions=[{"stream": events}],
        session_id=backend_mod.session_of(events),
        duration_ms=93081,
    )


# --------------------------------------------------------------------------- reading the stream


def test_progress_ticks_are_dropped_when_the_stream_is_read():
    events = stream()
    assert events
    assert not [event for event in events if event.get("subtype") == "thinking_tokens"]


def test_a_misnamed_agent_call_is_not_an_activation():
    # Two Agent calls failed: one named `counter` bare, one missing `description`. Neither ran.
    assert backend_mod.activations(stream()) == [
        {"kind": "skill", "name": "capture/word-count"},
        {"kind": "agent", "name": "capture/counter"},
    ]


def test_a_refused_activation_is_kept_as_blocked():
    events = [
        {
            "type": "assistant",
            "message": {
                "id": "m1",
                "content": [
                    {"type": "tool_use", "id": "t1", "name": "Skill", "input": {"skill": "x:y"}}
                ],
            },
        },
        {
            "type": "user",
            "message": {
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "t1",
                        "is_error": True,
                        "content": 'Skill "x:y" is disabled via skillOverrides.',
                    }
                ]
            },
        },
    ]
    assert backend_mod.activations(events) == [{"kind": "skill", "name": "x/y", "blocked": True}]


def test_the_answer_is_in_the_last_result_when_a_subagent_ran_in_the_background():
    events = stream()
    assert len(backend_mod.results(events)) == 2
    assert backend_mod.final_text(events) == "The file `notes.txt` has **5 words**."


def test_the_subagent_is_named_by_its_agent_id():
    children = backend_mod.child_sessions(stream())
    assert children == {"call_7zx8v67c": "a46aa7f3a5f754bfe"}


def test_a_loaded_skill_is_traced_to_its_file():
    assert backend_mod.skill_sources(stream()) == {
        "call_7peqc2sw": "/tmp/cc-capture/plugin/skills/word-count/SKILL.md"
    }


def test_tokens_are_the_session_totals_subagents_included():
    # A message's own usage stops at its first block (output 0); `modelUsage` has the totals.
    tokens = backend_mod.token_totals(stream())
    assert tokens == {"input": 78906, "output": 3619, "reasoning": 0, "cache_read": 25394}


def test_transcript_includes_the_subagent():
    assert "5" in backend_mod.transcript(stream())


@pytest.mark.parametrize(
    ("result", "outcome"),
    [
        ({"type": "result", "subtype": "success", "is_error": False, "result": "ok"}, "completed"),
        ({"type": "result", "subtype": "error_max_turns", "num_turns": 9}, "step_exhausted"),
        (
            {"type": "result", "subtype": "success", "is_error": True, "api_error_status": 500},
            "api_error",
        ),
    ],
)
def test_how_a_session_ended(result, outcome):
    assert backend_mod.classify([result])[0] == outcome


def test_no_result_is_infrastructure():
    assert backend_mod.classify([])[0] == "infra_error"


@pytest.mark.parametrize(
    ("text", "outcome"),
    [
        (
            "blocked by the wikiskill evaluation guard: git push matches deny pattern git push*",
            "permission_blocked",
        ),
        ("blocked by the wikiskill evaluation guard: step budget of 3 exhausted", "step_exhausted"),
    ],
)
def test_a_guard_refusal_decides_the_outcome(text, outcome):
    events = [
        {
            "type": "assistant",
            "message": {
                "id": "m",
                "content": [{"type": "tool_use", "id": "t", "name": "Bash", "input": {}}],
            },
        },
        {
            "type": "user",
            "message": {
                "content": [
                    {"type": "tool_result", "tool_use_id": "t", "is_error": True, "content": text}
                ]
            },
        },
        {"type": "result", "subtype": "success", "is_error": False},
    ]
    assert backend_mod.classify(events)[0] == outcome


def test_the_recorded_capture_was_not_isolated(capture):
    offered = backend_mod.offered_in(stream())
    leak = backend_mod.isolation_leak(unit(), offered, capture)
    assert leak and "deep-research" in leak and "cc-plugin-telemetry" in leak


def test_only_the_collection_may_be_offered(capture):
    offered = {"skills": ["capture:word-count"], "plugins": ["capture"], "mcp_servers": []}
    assert backend_mod.isolation_leak(unit(), offered, capture) is None
    assert backend_mod.isolation_leak(unit(condition="off"), offered, capture)


# --------------------------------------------------------------------------- normalising


def test_every_event_validates_and_carries_its_evaluation_provenance(backend):
    events = backend.normalize(trajectory(stream()))
    assert events
    for event in events:
        assert rawlog.schema_errors(event) == [], event
        assert event["origin"] == "eval"
        assert event["harness"] == "claude-code"
        assert event["harness_version"] == "2.1.289"
        assert event["provider"] == "ollama"
        assert event["model"] == "qwen3:30b-a3b"
        assert event["eval"]["condition"] == "routed"


def test_the_subagent_is_a_child_session_of_the_root(backend):
    events = backend.normalize(trajectory(stream()))
    root = "029c8d22-7314-4fc7-be89-ab8fa774c8e9"
    starts = [e for e in events if e["type"] == "session_start"]
    assert [(e["session_id"], e["parent_session_id"]) for e in starts] == [
        (root, None),
        ("a46aa7f3a5f754bfe", root),
    ]
    delegation = next(e for e in events if e["type"] == "delegation")
    assert delegation["payload"]["subagent_type"] == "capture/counter"
    assert delegation["payload"]["child_session_id"] == "a46aa7f3a5f754bfe"
    child_calls = [
        e for e in events if e["type"] == "tool_call" and e["session_id"] == "a46aa7f3a5f754bfe"
    ]
    assert [e["payload"]["tool"] for e in child_calls] == ["Bash"]
    assert all(e["root_session_id"] == root for e in events)


def test_activations_are_attributed_until_the_next(backend):
    events = backend.normalize(trajectory(stream()))
    activated = [e for e in events if e["type"] == "component_activated"]
    assert [(e["component"]["kind"], e["component"]["name"]) for e in activated] == [
        ("skill", "capture/word-count"),
        ("agent", "capture/counter"),
    ]
    assert activated[0]["payload"]["source_path"].endswith("word-count/SKILL.md")
    failed = [e for e in events if e["type"] == "tool_call" and not e["payload"]["ok"]]
    assert len(failed) == 2
    assert all(e["component"]["name"] == "capture/word-count" for e in failed)


def test_usage_is_recorded_per_turn_and_never_priced(backend):
    events = backend.normalize(trajectory(stream()))
    usage = [e for e in events if e["type"] == "step_usage"]
    assert [e["payload"]["tokens"]["output"] for e in usage] == [2561, 265]
    assert all(e["payload"]["cost"] is None for e in usage)


def test_a_skill_only_session_normalises(backend):
    events = backend.normalize(trajectory(stream(SKILL_ONLY)))
    assert [e["type"] for e in events].count("session_start") == 1
    assert any(e["type"] == "component_activated" for e in events)
    assert not any(e["type"] == "delegation" for e in events)


# --------------------------------------------------------------------------- isolation


def test_the_settings_switch_off_what_claude_code_ships(backend):
    settings = backend.settings_for(unit())
    assert settings["disableBundledSkills"] is True
    assert all(value is False for value in settings["enabledPlugins"].values())
    assert set(settings["enabledPlugins"]) == set(backend_mod.BUILTIN_PLUGINS)
    assert settings["skillOverrides"] == {"design": "off", "doctor": "off"}
    assert "WebFetch" in settings["permissions"]["deny"]
    guard = settings["hooks"]["PreToolUse"][0]["hooks"][0]["command"]
    assert guard.endswith(" guard")


def test_injected_switches_the_skill_off_and_puts_its_text_in_the_prompt(backend):
    injected = unit(condition="injected")
    root = backend.layout.unit_dir(injected)
    backend.prepare(injected)
    settings = json.loads((root / "claude" / "settings.json").read_text(encoding="utf-8"))
    assert "Skill(capture:word-count)" in settings["permissions"]["deny"]
    command = backend.command_for(injected, root)
    prompt = command[command.index("--append-system-prompt") + 1]
    assert "Delegate to the `counter` agent." in prompt


def test_an_injected_agent_runs_as_the_session_agent(backend):
    from wikiskill.suite import Route

    injected = unit(condition="injected", expect=Route(agent="capture/counter"))
    root = backend.layout.unit_dir(injected)
    backend.prepare(injected)
    command = backend.command_for(injected, root)
    assert command[command.index("--agent") + 1] == "capture:counter"


def test_routed_loads_the_built_collection_and_off_loads_nothing(backend):
    routed = unit()
    root = backend.layout.unit_dir(routed)
    backend.prepare(routed)
    command = backend.command_for(routed, root)
    plugin = command[command.index("--plugin-dir") + 1]
    assert (root / "plugin" / "skills" / "word-count" / "SKILL.md").is_file()
    assert plugin == str(root / "plugin")
    agent = (root / "plugin" / "agents" / "counter.md").read_text(encoding="utf-8")
    assert "model:" not in agent, "a pinned subagent would mix two models in one row"

    off = unit(condition="off")
    off_root = backend.layout.unit_dir(off)
    backend.prepare(off)
    assert "--plugin-dir" not in backend.command_for(off, off_root)
    assert not (off_root / "plugin").exists()


def test_the_environment_points_only_at_the_endpoint(backend, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-real")
    monkeypatch.setenv("CLAUDE_CODE_ENTRYPOINT", "cli")
    monkeypatch.setenv("CLAUDECODE", "1")
    root = backend.layout.root
    env = backend.env_for(unit(max_steps=7), root)
    assert env["CLAUDE_CONFIG_DIR"] == str(root / "claude")
    assert env["ANTHROPIC_BASE_URL"] == "http://localhost:11434"
    assert "ANTHROPIC_API_KEY" not in env, "an open-model run never carries a real key"
    assert "CLAUDECODE" not in env
    assert "CLAUDE_CODE_ENTRYPOINT" not in env
    assert env["CLAUDE_CODE_SUBAGENT_MODEL"] == "qwen3:30b-a3b"
    assert env["ANTHROPIC_DEFAULT_HAIKU_MODEL"] == "qwen3:30b-a3b"
    assert env["WIKISKILL_MAX_STEPS"] == "7"
    assert "git push*" in json.loads(env["WIKISKILL_GUARD_DENY"])
    assert "CLAUDE_CODE_DISABLE_BACKGROUND_TASKS" not in env


def test_foreground_agents_is_a_recorded_choice(tmp_path, capture):
    chosen = make_backend(tmp_path, capture, Endpoint("http://x:11434"), foreground_agents=True)
    env = chosen.env_for(unit(), tmp_path)
    assert env["CLAUDE_CODE_DISABLE_BACKGROUND_TASKS"] == "1"
    assert chosen.run_options() == {"foreground_agents": True}


def test_a_hosted_model_needs_a_key(tmp_path, capture, monkeypatch):
    hosted = make_backend(tmp_path, capture)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert not hosted.preflight("anthropic/claude-haiku-4-5").ok
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    assert hosted.preflight("anthropic/claude-haiku-4-5").ok
    assert hosted.env_for(unit(), tmp_path)["ANTHROPIC_API_KEY"] == "sk-test"


# --------------------------------------------------------------------------- the entry point


def fake_claude(tmp_path, recorded):
    """A `claude` that records how it was called and replays a captured stream."""
    script = tmp_path / "claude"
    script.write_text(
        "#!/bin/sh\n"
        'if [ "$1" = "--version" ]; then echo "2.1.289 (Claude Code)"; exit 0; fi\n'
        f'printf "%s\\n" "$@" > {tmp_path}/args.txt\n'
        f"env > {tmp_path}/env.txt\n"
        f"pwd > {tmp_path}/cwd.txt\n"
        f"cat {recorded}\n",
        encoding="utf-8",
    )
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    return script


def isolated_capture(tmp_path):
    """The subagent capture as an isolated session would have reported it."""
    lines = []
    for line in SUBAGENT.read_text(encoding="utf-8").splitlines():
        event = json.loads(line)
        if event.get("subtype") == "init":
            event["skills"] = ["capture:word-count"]
            event["plugins"] = [{"name": "capture", "path": "x", "source": "capture@inline"}]
        lines.append(json.dumps(event))
    path = tmp_path / "isolated.jsonl"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def test_execute_runs_claude_in_the_unit_and_reads_the_stream(tmp_path, capture):
    executable = fake_claude(tmp_path, isolated_capture(tmp_path))
    backend = make_backend(tmp_path, capture, Endpoint("http://localhost:11434"), str(executable))
    routed = unit()
    proof = backend.isolation_proof(routed)
    trajectory = backend.execute(routed)

    assert trajectory.outcome == "completed", trajectory.error
    assert trajectory.final_text.endswith("**5 words**.")
    assert [a["name"] for a in trajectory.activations] == ["capture/word-count", "capture/counter"]
    assert trajectory.session_id == "029c8d22-7314-4fc7-be89-ab8fa774c8e9"
    assert proof["offered"]["skills"] == ["capture:word-count"]

    args = (tmp_path / "args.txt").read_text(encoding="utf-8").splitlines()
    assert args[:4] == ["-p", "--output-format", "stream-json", "--verbose"]
    assert args[args.index("--setting-sources") + 1] == "user"
    assert args[-2:] == ["--", routed.task.prompt], "a variadic --add-dir must not eat the prompt"
    assert "--strict-mcp-config" in args
    env = dict(
        line.split("=", 1)
        for line in (tmp_path / "env.txt").read_text(encoding="utf-8").splitlines()
        if "=" in line
    )
    root = backend.layout.unit_dir(routed)
    assert env["CLAUDE_CONFIG_DIR"] == str(root / "claude")
    assert (tmp_path / "cwd.txt").read_text(encoding="utf-8").strip() == str(root / "work")
    assert (root / "stream.jsonl").is_file()


def test_an_unisolated_session_is_infrastructure_not_a_result(tmp_path, capture):
    executable = fake_claude(tmp_path, SUBAGENT)
    backend = make_backend(tmp_path, capture, Endpoint("http://localhost:11434"), str(executable))
    trajectory = backend.execute(unit())
    assert trajectory.outcome == "infra_error"
    assert "outside the collection" in trajectory.reason
    assert not trajectory.transient, "a leak is configuration, and would leak again"


def test_a_harness_that_produces_nothing_is_infrastructure(tmp_path, capture):
    empty = tmp_path / "empty.jsonl"
    empty.write_text("", encoding="utf-8")
    executable = fake_claude(tmp_path, empty)
    backend = make_backend(tmp_path, capture, Endpoint("http://localhost:11434"), str(executable))
    trajectory = backend.execute(unit())
    assert trajectory.outcome == "infra_error"
    assert "no session" in trajectory.reason
    assert trajectory.transient


def test_the_version_is_the_first_word(tmp_path, capture):
    executable = fake_claude(tmp_path, SUBAGENT)
    backend = make_backend(tmp_path, capture, None, str(executable))
    assert backend.version() == "2.1.289"


def test_no_real_home_is_touched(backend):
    # The unit's config dir is inside the run, never the developer's ~/.claude.
    root = backend.layout.unit_dir(unit())
    backend.prepare(unit())
    assert (root / "claude" / "settings.json").is_file()
    assert os.path.commonpath([root, backend.layout.root]) == str(backend.layout.root)


def test_a_permission_refusal_event_is_not_a_message():
    # `system/permission_denied` carries `message` as a string.
    events = [
        {"type": "system", "subtype": "permission_denied", "message": "blocked", "tool_name": "x"}
    ]
    assert backend_mod.activations(events) == []
    assert backend_mod.transcript(events) == ""


def test_injected_fails_when_the_denied_skill_was_loaded_anyway():
    injected = unit(condition="injected")
    loaded = [{"kind": "skill", "name": "capture/word-count"}]
    refused = [{"kind": "skill", "name": "capture/word-count", "blocked": True}]
    assert backend_mod.injection_failed(injected, loaded)
    assert backend_mod.injection_failed(injected, refused) is None
    assert backend_mod.injection_failed(unit(), loaded) is None


# --------------------------------------------------------------------------- redaction

KEY = "ghp_" + "A" * 36
SUITE_SECRET = "s3cr3t-value-123"


def leaky_stream():
    """The recorded subagent stream, with secrets in every free-text field an event copies."""
    events = stream()
    for event in events:
        content = backend_mod._message(event).get("content")
        for block in content if isinstance(content, list) else []:
            if isinstance(block, dict) and block.get("id") == "call_7zx8v67c":
                block["input"]["description"] = "deploy with password=hunter2hunter2"
    session = backend_mod.session_of(events)

    def said(role, *blocks):
        return {
            "type": role,
            "session_id": session,
            "parent_tool_use_id": None,
            "message": {"role": role, "content": list(blocks)},
        }

    bash = {"type": "tool_use", "id": "call_leak1", "name": "Bash"}
    events[-1:-1] = [
        said("assistant", {**bash, "input": {"command": f"echo {KEY}"}}),
        said("user", {"type": "tool_result", "tool_use_id": "call_leak1", "content": KEY}),
        said("assistant", {**bash, "id": "call_leak2", "input": {"command": "false"}}),
        said(
            "user",
            {
                "type": "tool_result",
                "tool_use_id": "call_leak2",
                "content": f"failed near {KEY}",
                "is_error": True,
            },
        ),
        said("assistant", {"type": "text", "text": f"The token is {SUITE_SECRET}."}),
    ]
    return events


def leaky_trajectory(events):
    from wikiskill.suite import Route, Task

    task = Task(
        id="count",
        prompt="How many words does notes.txt have?",
        split="val",
        expect=Route(skill="capture/word-count", agents=("capture/counter",)),
        env=(("DATASET_TOKEN", SUITE_SECRET),),
    )
    return runner_base.Trajectory(
        unit=runner_base.Unit(
            run_id=RUN_ID,
            suite="toy",
            task=task,
            model="ollama/qwen3:30b-a3b",
            condition="routed",
            repeat=0,
        ),
        outcome="completed",
        sessions=[{"stream": events}],
        session_id=backend_mod.session_of(events),
    )


def test_eval_events_are_redacted_with_the_units_environment(backend):
    events = backend.normalize(leaky_trajectory(leaky_stream()))
    written = json.dumps(events)

    assert KEY not in written and SUITE_SECRET not in written and "hunter2" not in written
    by_call = {e["payload"]["call_id"]: e for e in events if e["type"] == "tool_call"}
    ok, failed = by_call["call_leak1"], by_call["call_leak2"]
    assert ok["payload"]["output"] == "[REDACTED:api_key]"
    assert ok["payload"]["input"] == {"command": "echo [REDACTED:api_key]"}
    assert ok["payload"]["output_length"] == len(KEY)
    assert ok["redactions"] == [{"kind": "api_key", "count": 2}]
    assert failed["payload"]["error"] == "failed near [REDACTED:api_key]"

    turn = [e for e in events if e["type"] == "assistant_turn"][-1]
    assert turn["payload"]["text"] == "The token is [REDACTED:env_value]."

    delegation = [e for e in events if e["type"] == "delegation"][-1]
    assert delegation["payload"]["description"] == "deploy with password=[REDACTED:password]"
    activation = [e for e in events if e["type"] == "component_activated"][-1]
    assert activation["payload"]["input_summary"] == "deploy with password=[REDACTED:password]"
    for event in events:
        assert rawlog.schema_errors(event) == [], event


def test_eval_redaction_can_be_turned_off(tmp_path, capture):
    backend = make_backend(tmp_path, capture, redact=False)
    events = backend.normalize(leaky_trajectory(leaky_stream()))

    by_call = {e["payload"]["call_id"]: e for e in events if e["type"] == "tool_call"}
    assert by_call["call_leak1"]["payload"]["output"] == KEY
    assert not any("redactions" in event for event in events)


def test_normalising_leaves_the_units_stream_as_it_was(backend):
    events_in = leaky_stream()
    trajectory_ = leaky_trajectory(events_in)
    saved = backend.layout.unit_dir(trajectory_.unit) / "stream.jsonl"
    saved.parent.mkdir(parents=True, exist_ok=True)
    saved.write_text("\n".join(json.dumps(e) for e in events_in), encoding="utf-8")
    before = json.dumps(events_in)

    events = backend.normalize(trajectory_)

    assert json.dumps(events_in) == before
    assert KEY in saved.read_text(encoding="utf-8")
    assert KEY not in json.dumps(events)


# --------------------------------------------------------------------------- golden


@pytest.mark.parametrize(("name", "path"), [("subagent", SUBAGENT), ("skill", SKILL_ONLY)])
def test_normalized_events_match_the_golden_file(backend, tmp_path, name, path):
    from conftest import golden_events

    golden_events(backend.normalize(trajectory(stream(path))), f"claude-{name}", tmp_path)
