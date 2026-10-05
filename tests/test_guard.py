"""The Claude Code evaluation guard: the OpenCode guard's rules, as a `PreToolUse` hook."""

from __future__ import annotations

import io
import json
import subprocess
import sys

import pytest

from wikiskill import guard


@pytest.mark.parametrize(
    ("subject", "pattern", "expected"),
    [
        ("git push origin main", "git push*", True),
        ("git pushd", "git push*", True),
        ("git status", "git push*", False),
        ("rm -rf /", "rm -rf /*", True),
        ("rm -rf /tmp/x", "rm -rf /*", True),
        ("rm -rf ./x", "rm -rf /*", False),
        ("a.b", "a?b", True),
        ("aXb", "a.b", False),
        ("line\nnext", "line*", True),
    ],
)
def test_patterns_match_as_the_opencode_guard_does(subject, pattern, expected):
    assert guard.matches(subject, pattern) is expected


def test_chained_commands_are_each_checked():
    commands = guard.commands_in({"command": "cd repo && git push; echo done | tee log"})
    assert "git push" in commands
    assert "cd repo && git push; echo done | tee log" in commands


def test_only_shell_tools_are_checked_against_command_patterns():
    assert guard.denial_for("Bash", {"command": "git push"}, ["git push*"], []) == (
        "git push",
        "git push*",
    )
    assert guard.denial_for("Write", {"command": "git push"}, ["git push*"], []) is None
    assert guard.denial_for("WebFetch", {}, [], ["webfetch"]) == ("tool webfetch", "webfetch")


def test_a_denied_command_is_refused_in_the_shared_words():
    reason = guard.decide(
        {"tool_name": "Bash", "tool_input": {"command": "git push"}},
        {"WIKISKILL_GUARD_DENY": json.dumps(["git push*"])},
    )
    assert reason.startswith(guard.BLOCKED_PREFIX)
    assert "git push*" in reason


def test_the_step_budget_counts_every_call(tmp_path):
    env = {"WIKISKILL_MAX_STEPS": "2", "WIKISKILL_GUARD_STATE": str(tmp_path / "steps")}
    call = {"tool_name": "Read", "tool_input": {"file_path": "x"}}
    assert guard.decide(call, env) is None
    assert guard.decide(call, env) is None
    reason = guard.decide(call, env)
    assert reason == guard.STEP_EXHAUSTED.format(budget=2)
    assert guard.STEP_MARKER in reason


def test_unreadable_configuration_blocks_nothing():
    call = {"tool_name": "Bash", "tool_input": {"command": "git push"}}
    assert guard.decide(call, {"WIKISKILL_GUARD_DENY": "not json"}) is None


def test_main_prints_a_deny_decision_only_when_refusing(monkeypatch):
    monkeypatch.setenv("WIKISKILL_GUARD_DENY", json.dumps(["curl *"]))
    monkeypatch.delenv("WIKISKILL_GUARD_STATE", raising=False)
    out = io.StringIO()
    payload = {"tool_name": "Bash", "tool_input": {"command": "curl http://x"}}
    assert guard.main(io.StringIO(json.dumps(payload)), out) == 0
    decision = json.loads(out.getvalue())["hookSpecificOutput"]
    assert decision["hookEventName"] == "PreToolUse"
    assert decision["permissionDecision"] == "deny"

    quiet = io.StringIO()
    allowed = {"tool_name": "Bash", "tool_input": {"command": "ls"}}
    assert guard.main(io.StringIO(json.dumps(allowed)), quiet) == 0
    assert quiet.getvalue() == ""


def test_the_cli_entry_point_is_what_the_hook_runs(tmp_path):
    # The settings run `<wikiskill> guard`; exercise that, not just the function.
    done = subprocess.run(
        [sys.executable, "-m", "wikiskill", "guard"],
        input=json.dumps({"tool_name": "Bash", "tool_input": {"command": "git push"}}),
        capture_output=True,
        text=True,
        env={"WIKISKILL_GUARD_DENY": json.dumps(["git push*"]), "PATH": "/usr/bin:/bin"},
        check=False,
    )
    assert done.returncode == 0, done.stderr
    assert json.loads(done.stdout)["hookSpecificOutput"]["permissionDecision"] == "deny"
