"""The Claude Code hooks logger, driven by hook payloads captured from Claude Code 2.1.289.

The fixtures in `fixtures/claude-code/` are real: a throwaway plugin's hooks appended their stdin
while Haiku ran a skill, a background subagent, a resumed follow-up and a slash command. Every event
the logger writes from them is validated against the raw schema.
"""

from __future__ import annotations

import copy
import io
import json
import shutil
import time
from contextlib import redirect_stdout
from pathlib import Path

import pytest

from conftest import FIXTURES
from wikiskill import corrections, hooks, rawlog

CAPTURE = json.loads((FIXTURES / "claude-code" / "hooks-2.1.289.json").read_text(encoding="utf-8"))
SESSION = "64cc5c7d-fd0b-4859-9904-efc7614e034c"
AGENT = "aa4d3eb256b95648d"
NO_ENV: dict[str, str] = {}


@pytest.fixture(autouse=True)
def scans(monkeypatch):
    """Scans the hooks would start, recorded instead of spawned."""
    started: list[bool] = []
    monkeypatch.setattr(hooks, "start_scan", lambda: started.append(True))
    return started


@pytest.fixture
def world(tmp_path, xdg):
    """A collection watching the capture plugin's skill, agent and command, and the transcripts."""
    skill = tmp_path / "src" / "skills" / "probe-skill" / "SKILL.md"
    agent = tmp_path / "src" / "agents" / "probe-agent.md"
    for path in (skill, agent):
        path.parent.mkdir(parents=True)
        path.write_text(f"---\nname: {path.stem}\ndescription: d\n---\n", encoding="utf-8")
    transcript = tmp_path / "transcript.jsonl"
    agent_transcript = tmp_path / "agent.jsonl"
    shutil.copy(FIXTURES / "claude-code" / "transcript-2.1.289.jsonl", transcript)
    shutil.copy(FIXTURES / "claude-code" / "agent-transcript-2.1.289.jsonl", agent_transcript)
    config = {
        "collection": "wscapture",
        "raw_dir": str(tmp_path / "raw"),
        "error_log": str(tmp_path / "raw" / "_logger-errors.log"),
        "buffer_size": 200,
        "output_limit_bytes": 16384,
        "redact": True,
        "follow_up_turns": 3,
        "watch": {
            "skill": ["wscapture/probe-skill"],
            "agent": ["wscapture/probe-agent"],
            "command": ["wscapture/probe-cmd"],
        },
        "source_roots": [],
        "watched": [
            {"kind": "skill", "name": "wscapture/probe-skill", "path": str(skill)},
            {"kind": "agent", "name": "wscapture/probe-agent", "path": str(agent)},
        ],
    }
    return {
        "config": config,
        "raw": tmp_path / "raw",
        "transcript": str(transcript),
        "agent_transcript": str(agent_transcript),
        "skill": skill,
    }


def payloads(world, name):
    """The captured payloads, pointed at this test's copies of the transcripts."""
    out = copy.deepcopy(CAPTURE[name])
    for payload in out:
        if "transcript_path" in payload:
            payload["transcript_path"] = world["transcript"]
        if "agent_transcript_path" in payload:
            payload["agent_transcript_path"] = world["agent_transcript"]
    return out


def replay(world, *names, configs=None, env=NO_ENV):
    """Each payload a second after the last: real hooks are separate processes, never microseconds
    apart, and event ids are only ordered across hooks at that kind of spacing."""
    clock = time.time()
    for name in names:
        for payload in payloads(world, name):
            clock += 1
            hooks.handle(
                payload["hook_event_name"],
                payload,
                env=env,
                configs=[world["config"]] if configs is None else configs,
                now=clock,
            )


def logged(world):
    events = []
    for path in rawlog.log_files(world["raw"]):
        events.extend(rawlog.read_events(path))
    return events


def of(events, type_):
    return [e for e in events if e["type"] == type_]


# --------------------------------------------------------------------------- the whole session


def test_every_event_from_a_real_session_validates(world):
    replay(world, "session", "resume")
    events = logged(world)
    assert events
    problems = [f"{e['type']}: {p}" for e in events for p in rawlog.schema_errors(e)]
    assert problems == []
    for path in rawlog.log_files(world["raw"]):
        assert rawlog.validate_file(path) == []


def test_identity_comes_from_the_transcript(world):
    replay(world, "session")
    events = logged(world)
    assert {e["harness"] for e in events} == {"claude-code"}
    assert {e["harness_version"] for e in events} == {"2.1.289"}
    assert {e["provider"] for e in events} == {"anthropic"}
    assert "claude-haiku-4-5-20251001" in {e["model"] for e in events}
    assert {e["root_session_id"] for e in events} == {SESSION}


def test_a_skill_call_is_an_activation_with_the_version_that_ran(world):
    replay(world, "session")
    [skill] = [
        e for e in of(logged(world), "component_activated") if e["component"]["kind"] == "skill"
    ]
    assert skill["component"] == {
        "kind": "skill",
        "name": "wscapture/probe-skill",
        "source_hash": rawlog.file_hash(world["skill"]),
    }
    assert skill["payload"]["trigger"] == "skill_tool"


def test_the_events_before_an_activation_are_flushed_with_it(world):
    replay(world, "session")
    types = [e["type"] for e in logged(world)]
    assert types[0] == "session_start"
    assert types.index("session_start") < types.index("component_activated")


def test_a_background_subagent_is_a_linked_child_doing_the_agents_work(world):
    replay(world, "session")
    events = logged(world)
    [delegation] = of(events, "delegation")
    assert delegation["payload"]["subagent_type"] == "wscapture/probe-agent"
    assert delegation["payload"]["child_session_id"] == AGENT

    [read] = [e for e in of(events, "tool_call") if e["payload"]["tool"] == "Read"]
    assert read["session_id"] == AGENT
    assert read["parent_session_id"] == SESSION
    assert read["component"]["name"] == "wscapture/probe-agent"
    assert read["payload"]["output"] == "probe readme first line\n"

    ends = [e for e in of(events, "session_end") if e["session_id"] == AGENT]
    assert [e["payload"]["reason"] for e in ends] == ["subagent_stop"]


def test_usage_is_counted_once_per_message(world):
    replay(world, "session")
    transcript = [json.loads(line) for line in Path(world["transcript"]).read_text().splitlines()]
    agent = [json.loads(line) for line in Path(world["agent_transcript"]).read_text().splitlines()]
    expected = len({e["message"]["id"] for e in transcript + agent})
    usage = of(logged(world), "step_usage")
    assert len(usage) == expected
    assert all(e["payload"]["tokens"]["output"] is not None for e in usage)


def test_a_finished_turn_ends_the_session_once(world):
    replay(world, "session")
    root_ends = [e for e in of(logged(world), "session_end") if e["session_id"] == SESSION]
    # One idle end for the first turn, one for the turn the task notification started, and the end
    # Claude Code reported when the process exited.
    assert [e["payload"]["reason"] for e in root_ends] == ["idle", "idle", "other"]


# --------------------------------------------------------------------------- corrections


def test_a_task_notification_is_not_a_user_turn(world):
    replay(world, "session")
    assert of(logged(world), "user_turn") == []


def test_a_resumed_follow_up_is_a_high_confidence_turn_for_the_last_component(world):
    replay(world, "session", "resume")
    [turn] = of(logged(world), "user_turn")
    assert turn["confidence"] == "high"
    assert turn["component"]["name"] == "wscapture/probe-agent"
    assert turn["payload"]["text"] == "That was wrong. Use the probe-skill skill again."
    assert turn["payload"]["turns_since_activation"] == 1


def test_re_running_a_skill_after_a_follow_up_is_a_repeat(world):
    session = payloads(world, "session")
    resume = payloads(world, "resume")
    skill = next(p for p in session if p.get("tool_name") == "Skill" and "tool_response" in p)
    prompt = next(p for p in resume if p["hook_event_name"] == "UserPromptSubmit")
    again = next(p for p in resume if p.get("tool_name") == "Skill" and "tool_response" in p)
    for payload in (skill, prompt, again):
        hooks.handle(payload["hook_event_name"], payload, env=NO_ENV, configs=[world["config"]])

    [repeat] = of(logged(world), "repeat_activation")
    assert repeat["confidence"] == "high"
    assert repeat["payload"]["turns_since_previous"] == 1
    assert repeat["component"]["name"] == "wscapture/probe-skill"


def test_a_slash_command_activates_it_and_is_not_a_user_turn(world):
    replay(world, "command")
    events = logged(world)
    [activation] = of(events, "component_activated")
    assert activation["component"]["kind"] == "command"
    assert activation["component"]["name"] == "wscapture/probe-cmd"
    assert activation["payload"]["input_summary"] == "hello there"
    assert of(events, "user_turn") == []


def test_a_logged_session_can_take_a_note(world):
    replay(world, "session")
    cwd = CAPTURE["session"][0]["cwd"]
    assert corrections.active_sessions(world["raw"], cwd)[0][0] == SESSION


# --------------------------------------------------------------------------- output edits


def _write_call(world, target, content):
    """A Write after the capture's skill call: the payload shape Claude Code 2.1.289 sends."""
    skill = next(p for p in payloads(world, "session") if p.get("tool_name") == "Skill")
    target.write_text(content, encoding="utf-8")
    return {
        **{k: skill[k] for k in ("session_id", "transcript_path", "cwd")},
        "hook_event_name": "PostToolUse",
        "tool_name": "Write",
        "tool_input": {"file_path": str(target), "content": content},
        "tool_response": {"type": "create", "filePath": str(target)},
        "tool_use_id": "toolu_write",
    }


def test_a_write_records_the_file_it_produced(world, tmp_path):
    skill = next(p for p in payloads(world, "session") if p.get("tool_name") == "Skill")
    hooks.handle("PostToolUse", skill, env=NO_ENV, configs=[world["config"]])
    target = tmp_path / "analysis.py"
    payload = _write_call(world, target, "print(1)\n")
    hooks.handle("PostToolUse", payload, env=NO_ENV, configs=[world["config"]])

    [write] = [e for e in of(logged(world), "tool_call") if e["payload"]["tool"] == "Write"]
    assert write["payload"]["produced_files"] == [
        {"path": str(target), "hash": rawlog.file_hash(target)}
    ]
    assert write["component"]["name"] == "wscapture/probe-skill"
    assert rawlog.schema_errors(write) == []


def test_a_failed_write_produced_nothing(world, tmp_path):
    payload = _write_call(world, tmp_path / "analysis.py", "x")
    hooks.handle("PostToolUseFailure", payload, env=NO_ENV, configs=[world["config"]])
    hooks.handle(
        "PostToolUse", payloads(world, "session")[3], env=NO_ENV, configs=[world["config"]]
    )
    failed = [e for e in of(logged(world), "tool_call") if e["payload"]["tool"] == "Write"]
    assert failed
    assert "produced_files" not in failed[0]["payload"]


def test_a_session_start_starts_one_scan(world, scans):
    replay(world, "session", "resume")
    starts = sum(
        p["hook_event_name"] == "SessionStart" for n in ("session", "resume") for p in CAPTURE[n]
    )
    assert starts >= 2
    # The resume is seconds after the first start: one scan covers both.
    assert scans == [True]


# --------------------------------------------------------------------------- the gate


def test_a_session_that_touches_nothing_watched_writes_nothing(world):
    world["config"]["watch"] = {"skill": ["other/*"], "agent": [], "command": []}
    replay(world, "session", "resume")
    assert logged(world) == []


def test_an_evaluation_is_not_logged_by_the_hooks(world):
    replay(world, "session", env={"WIKISKILL_ORIGIN": "eval"})
    assert logged(world) == []


def test_another_plugins_skill_of_the_same_name_is_not_watched(world):
    config = world["config"]
    assert hooks.watched_name(config, "skill", "wscapture:probe-skill") == "wscapture/probe-skill"
    assert hooks.watched_name(config, "skill", "elsewhere:probe-skill") is None
    flat = {**config, "watch": {"skill": ["probe-skill"]}}
    assert hooks.watched_name(flat, "skill", "wikiskill:probe-skill") == "probe-skill"


def test_a_secret_in_a_follow_up_is_redacted(world):
    replay(world, "session")
    prompt = next(
        p for p in payloads(world, "resume") if p["hook_event_name"] == "UserPromptSubmit"
    )
    prompt["prompt"] = "no, use key sk-ant-api03-AAAABBBBCCCCDDDDEEEE"
    hooks.handle("UserPromptSubmit", prompt, env=NO_ENV, configs=[world["config"]])
    [turn] = of(logged(world), "user_turn")
    assert "sk-ant" not in turn["payload"]["text"]
    assert turn["redactions"] == [{"kind": "api_key", "count": 1}]


# --------------------------------------------------------------------------- fail-open


def test_a_corrupt_state_file_costs_nothing_but_an_error_line(world, monkeypatch):
    monkeypatch.setattr(hooks, "load_configs", lambda: [world["config"]])
    state = hooks.state_path(SESSION)
    state.parent.mkdir(parents=True, exist_ok=True)
    state.write_text("{not json", encoding="utf-8")
    payload = payloads(world, "session")[3]
    out = io.StringIO()
    with redirect_stdout(out):
        code = hooks.run("PostToolUse", json.dumps(payload))
    assert code == 0
    assert out.getvalue() == ""
    assert "hook PostToolUse" in Path(world["config"]["error_log"]).read_text(encoding="utf-8")


def test_garbage_on_stdin_is_silent_too(world, monkeypatch, capsys):
    monkeypatch.setattr(hooks, "load_configs", lambda: [world["config"]])
    assert hooks.run("Stop", "this is not json") == 0
    assert capsys.readouterr().out == ""


def test_the_cli_entry_point_is_silent_and_succeeds(world, monkeypatch, capsys):
    from wikiskill import cli

    monkeypatch.setattr(hooks, "load_configs", lambda: [world["config"]])
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(payloads(world, "session")[3])))
    assert cli.main(["hook", "PostToolUse"]) == 0
    assert capsys.readouterr().out == ""
    assert of(logged(world), "component_activated")


def test_events_from_one_hook_sort_in_the_order_they_were_written(world):
    replay(world, "session")
    events = logged(world)
    assert [e["event_id"] for e in events] == sorted(e["event_id"] for e in events)
