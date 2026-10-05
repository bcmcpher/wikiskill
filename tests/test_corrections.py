"""Correction signals: the 1.1 schema additions and `wikiskill note`.

The follow-up window and repeat detection live in the OpenCode logger and are tested there
(`harness/opencode/plugin/test/logger.test.ts`); what the plugin emits is validated against this
schema by `test_plugin_contract.py`.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest

from conftest import write_manifest
from wikiskill import cli, corrections, rawlog
from wikiskill import collection as collection_mod

ROOT = "ses_root"
CHILD = "ses_child"
HASH = "sha256:" + "a" * 64

MANIFEST = """
name = "dsh"
sources = [{{ path = "{source}", layout = "claude-plugin" }}]

[watch]
skills = ["govern/*"]
agents = ["datalad/datalad-doer"]
"""


def base(**overrides):
    event = {
        "schema_version": rawlog.RAW_SCHEMA_VERSION,
        "event_id": rawlog.new_event_id(),
        "ts": rawlog.now_ts(),
        "origin": "live",
        "harness": "opencode",
        "harness_version": "1.18.34",
        "provider": "ollama",
        "model": "qwen3:1.7b",
        "collection": "dsh",
        "session_id": ROOT,
        "root_session_id": ROOT,
        "parent_session_id": None,
        "component": None,
    }
    event.update(overrides)
    return event


SKILL = {"kind": "skill", "name": "govern/preregister", "source_hash": HASH}


# --------------------------------------------------------------------------- schema


def test_a_user_turn_validates():
    event = base(
        component=SKILL,
        type="user_turn",
        confidence="high",
        payload={"text": "no, use a mixed model", "text_length": 21, "turns_since_activation": 1},
    )
    assert rawlog.schema_errors(event) == []


@pytest.mark.parametrize(
    ("change", "complaint"),
    [
        ({"confidence": None}, "confidence"),
        ({"component": None}, "component"),
        ({"confidence": "explicit"}, "confidence"),
        ({"payload": {"text_length": 1, "turns_since_activation": 0}}, "turns_since_activation"),
        ({"payload": {"text_length": 1, "turns_since_activation": 1, "label": "correction"}}, ""),
    ],
)
def test_a_user_turn_must_be_attributed_unlabelled_and_counted(change, complaint):
    event = base(
        component=SKILL,
        type="user_turn",
        confidence="high",
        payload={"text_length": 1, "turns_since_activation": 1},
    )
    event.update(change)
    if event["confidence"] is None:
        del event["confidence"]
    problems = rawlog.schema_errors(event)
    assert problems
    assert any(complaint in problem for problem in problems)


def test_only_correction_signals_carry_a_confidence():
    event = base(
        type="session_end", confidence="high", payload={"reason": "idle", "duration_ms": None}
    )
    assert rawlog.schema_errors(event)


def test_a_note_may_name_no_component():
    event = base(
        type="note",
        confidence="explicit",
        payload={"text": "the plot used the wrong axis scale", "attributed_by": "none"},
    )
    assert rawlog.schema_errors(event) == []


def test_a_note_is_always_explicit():
    event = base(type="note", confidence="high", payload={"text": "x"})
    assert rawlog.schema_errors(event)


def test_a_repeat_activation_and_an_output_edit_validate():
    repeat = base(
        component=SKILL,
        type="repeat_activation",
        confidence="high",
        payload={
            "turns_since_previous": 2,
            "seconds_since_previous": 41.5,
            "trigger": "skill_tool",
        },
    )
    edit = base(
        component=SKILL,
        type="output_edit",
        confidence="low",
        payload={
            "path": "analysis.py",
            "before_hash": HASH,
            "after_hash": None,
            "diff": None,
            "diff_truncated": False,
        },
    )
    assert rawlog.schema_errors(repeat) == []
    assert rawlog.schema_errors(edit) == []


# --------------------------------------------------------------------------- note


@pytest.fixture
def dsh(xdg, plugin_source):
    write_manifest(xdg, "dsh", MANIFEST.format(source=plugin_source))
    return collection_mod.load("dsh")


@pytest.fixture
def raw(tmp_path):
    return tmp_path / "raw"


@pytest.fixture
def project(tmp_path):
    directory = tmp_path / "project"
    directory.mkdir()
    return directory


def log_session(raw, *events, root=ROOT):
    path = rawlog.session_log_path(raw, rawlog.now_ts(), root)
    rawlog.RawLogWriter(path).extend(events)
    return path


def publish(raw, directory, **sessions):
    """What the OpenCode logger writes for `wikiskill note` to find."""
    path = corrections.active_sessions_path(raw, directory)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"directory": str(directory), "sessions": sessions}), encoding="utf-8"
    )


def ago(**delta):
    return (datetime.now(UTC) - timedelta(**delta)).isoformat().replace("+00:00", "Z")


def activated(component=SKILL, **overrides):
    return base(
        component=component,
        type="component_activated",
        payload={"trigger": "skill_tool"},
        **overrides,
    )


def test_the_project_hash_matches_the_plugins():
    """`harness/opencode/plugin/test/writer.test.ts` asserts the same digest."""
    path = corrections.active_sessions_path("/raw", "/tmp/wikiskill-capture")
    assert path.name == "f87d00567a7a8385.json"


def test_a_note_attaches_to_the_last_activated_component(dsh, raw, project):
    other = {"kind": "agent", "name": "datalad/datalad-doer", "source_hash": None}
    path = log_session(raw, base(type="session_start", payload={}), activated(), activated(other))
    publish(raw, project, **{ROOT: ago(minutes=1)})

    note = corrections.write_note(
        dsh, "  the dataset is in the wrong place ", cwd=project, raw_dir=raw
    )

    assert note.path == path
    assert note.event["type"] == "note"
    assert note.event["confidence"] == "explicit"
    assert note.event["component"] == other
    assert note.event["payload"]["text"] == "the dataset is in the wrong place"
    assert note.event["payload"]["attributed_by"] == "last_activated"
    assert rawlog.validate_file(path) == []
    assert list(rawlog.read_events(path))[-1]["event_id"] == note.event["event_id"]


def test_a_named_component_uses_the_version_that_ran(dsh, raw, project):
    log_session(
        raw,
        activated(),
        activated({"kind": "agent", "name": "datalad/datalad-doer", "source_hash": None}),
    )
    publish(raw, project, **{ROOT: ago(minutes=1)})

    note = corrections.write_note(
        dsh, "wrong axis scale", component="preregister", cwd=project, raw_dir=raw
    )

    assert note.event["component"] == SKILL
    assert note.event["payload"]["attributed_by"] == "named"


def test_a_named_component_that_did_not_run_is_hashed_from_disk(dsh, raw):
    log_session(raw, activated())
    note = corrections.write_note(
        dsh, "should have been used", component="agent:datalad-doer", session=ROOT, raw_dir=raw
    )
    component = note.event["component"]
    assert component["kind"] == "agent"
    assert component["name"] == "datalad/datalad-doer"
    assert component["source_hash"].startswith("sha256:")


def test_a_component_that_is_not_watched_is_refused(dsh, raw):
    log_session(raw, activated())
    with pytest.raises(corrections.NoteError, match="not a watched component"):
        corrections.write_note(dsh, "x", component="nonesuch", session=ROOT, raw_dir=raw)


def test_a_note_with_nothing_activated_names_no_component(dsh, raw):
    log_session(raw, base(type="session_start", payload={}))
    note = corrections.write_note(dsh, "this went badly", session=ROOT, raw_dir=raw)
    assert note.event["component"] is None
    assert note.event["payload"]["attributed_by"] == "none"
    assert note.warnings


def test_a_childs_note_goes_into_its_roots_file(dsh, raw):
    path = log_session(
        raw,
        activated(),
        activated(session_id=CHILD, parent_session_id=ROOT),
    )
    note = corrections.write_note(dsh, "the subagent forgot", session=CHILD, raw_dir=raw)
    assert note.path == path
    assert note.event["session_id"] == CHILD
    assert note.event["root_session_id"] == ROOT
    assert note.event["parent_session_id"] == ROOT


def test_several_open_sessions_pick_the_latest_and_say_so(dsh, raw, project):
    log_session(raw, activated(session_id="ses_old", root_session_id="ses_old"), root="ses_old")
    log_session(raw, activated())
    publish(raw, project, ses_old=ago(minutes=20), **{ROOT: ago(minutes=2)})

    note = corrections.write_note(dsh, "x", cwd=project, raw_dir=raw)

    assert note.event["session_id"] == ROOT
    assert any("ses_old" in warning for warning in note.warnings)


def test_no_published_session_asks_for_one(dsh, raw, project):
    log_session(raw, activated())
    with pytest.raises(corrections.NoteError, match="--session"):
        corrections.write_note(dsh, "x", cwd=project, raw_dir=raw)


def test_an_empty_note_is_refused(dsh, raw):
    with pytest.raises(corrections.NoteError, match="text"):
        corrections.write_note(dsh, "   ", session=ROOT, raw_dir=raw)


def test_the_cli_writes_a_note(dsh, capsys):
    log_session(collection_mod.paths.raw_dir("dsh"), activated())
    code = cli.main(["note", "--collection", "dsh", "--session", ROOT, "--", "wrong", "test"])
    assert code == cli.OK
    assert "skill:govern/preregister" in capsys.readouterr().out


def test_the_cli_reports_a_session_it_cannot_find(dsh, capsys):
    code = cli.main(["note", "--session", "ses_nowhere", "--", "x"])
    assert code == cli.FAILED
    assert "ses_nowhere" in capsys.readouterr().err


# --------------------------------------------------------------------------- manifest


def test_the_follow_up_window_reaches_the_logger(xdg, plugin_source):
    write_manifest(
        xdg, "dsh", MANIFEST.format(source=plugin_source) + "\n[logging]\nfollow_up_turns = 5\n"
    )
    assert collection_mod.load("dsh").runtime_config()["follow_up_turns"] == 5


def test_the_follow_up_window_defaults_to_three_and_must_be_positive(xdg, plugin_source):
    write_manifest(xdg, "dsh", MANIFEST.format(source=plugin_source))
    assert collection_mod.load("dsh").runtime_config()["follow_up_turns"] == 3
    write_manifest(
        xdg, "dsh", MANIFEST.format(source=plugin_source) + "\n[logging]\nfollow_up_turns = 0\n"
    )
    with pytest.raises(collection_mod.ManifestError, match="follow_up_turns"):
        collection_mod.load("dsh")
