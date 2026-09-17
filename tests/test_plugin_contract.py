"""The cross-language contract.

The OpenCode logger is TypeScript and the schema lives in Python's world. These tests run the
plugin's own mapper and validate what it really emits against `schemas/raw-event.schema.json`, so
the two halves cannot drift apart silently.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from wikiskill import RAW_SCHEMA_VERSION, rawlog

PLUGIN = Path(__file__).resolve().parent.parent / "harness" / "opencode" / "plugin"

BUN = shutil.which("bun") or shutil.which(
    "bun", path=os.path.expanduser("~/.claude-node-tools/bin")
)

pytestmark = pytest.mark.skipif(BUN is None, reason="bun is not installed")


@pytest.fixture(scope="module")
def emitted():
    result = subprocess.run(
        [BUN, "run", "test/emit-sample.ts"],
        cwd=PLUGIN,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    return [json.loads(line) for line in result.stdout.splitlines() if line.strip()]


def test_the_plugin_emits_events(emitted):
    assert len(emitted) >= 10


def test_every_emitted_event_validates_against_the_schema(emitted):
    problems = []
    for index, event in enumerate(emitted):
        for message in rawlog.schema_errors(event):
            problems.append(f"event {index} ({event.get('type')}): {message}")
    assert problems == [], "\n".join(problems)


def test_the_plugin_writes_the_schema_version_python_reads(emitted):
    assert {event["schema_version"] for event in emitted} == {RAW_SCHEMA_VERSION}


def test_emitted_event_ids_are_ulids_python_accepts(emitted):
    assert all(rawlog.is_event_id(event["event_id"]) for event in emitted)


def test_emitted_timestamps_parse_as_the_day_python_files_them_under(emitted):
    for event in emitted:
        assert rawlog.day_of(event["ts"]).count("-") == 2


def test_every_event_type_this_change_defines_is_exercised(emitted):
    """A type in the schema that the plugin never produces is a gap, not a feature."""
    produced = {event["type"] for event in emitted}
    assert produced == set(rawlog.EVENT_TYPES)


def test_a_python_reader_accepts_a_log_the_plugin_wrote(emitted, tmp_path):
    path = tmp_path / "2026-09-17" / "ses_root.jsonl"
    path.parent.mkdir(parents=True)
    path.write_text("".join(json.dumps(e) + "\n" for e in emitted), encoding="utf-8")
    assert rawlog.validate_file(path) == []
    assert len(list(rawlog.read_events(path))) == len(emitted)


def test_secrets_do_not_survive_into_the_log(emitted):
    blob = json.dumps(emitted)
    assert "sk-ant-api03" not in blob
    assert "correct-horse-battery" not in blob
    assert "[REDACTED:" in blob


def test_a_truncated_output_keeps_its_original_length(emitted):
    truncated = [
        e for e in emitted if e["type"] == "tool_call" and e["payload"]["output_truncated"]
    ]
    assert truncated
    for event in truncated:
        assert event["payload"]["output_length"] > len(event["payload"]["output"])


def test_a_delegation_names_its_child_session(emitted):
    delegation = next(e for e in emitted if e["type"] == "delegation")
    assert delegation["payload"]["child_session_id"]
    child_events = [e for e in emitted if e["parent_session_id"]]
    assert child_events
    assert all(e["root_session_id"] == delegation["root_session_id"] for e in child_events)


def test_every_activation_carries_a_component(emitted):
    activations = [e for e in emitted if e["type"] == "component_activated"]
    assert len(activations) >= 3
    assert {a["payload"]["trigger"] for a in activations} >= {"skill_tool", "read", "command"}
    assert all(a["component"] for a in activations)


def test_the_plugin_agrees_with_python_on_the_log_path(emitted, tmp_path):
    """Both sides must put a session's events in the same file."""
    result = subprocess.run(
        [
            BUN,
            "-e",
            (
                'import {sessionLogPath} from "./wikiskill/writer";'
                'console.log(sessionLogPath("/raw", "2026-09-17T19:44:16.523Z", "ses_root"))'
            ),
        ],
        cwd=PLUGIN,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    expected = rawlog.session_log_path("/raw", "2026-09-17T19:44:16.523Z", "ses_root")
    assert result.stdout.strip() == str(expected)
