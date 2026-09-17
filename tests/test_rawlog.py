"""The raw event schema, the reader's version refusal, and the append-only writer."""

from __future__ import annotations

import json

import pytest

from conftest import RAW_FIXTURES
from wikiskill import RAW_SCHEMA_VERSION, rawlog

VALID_FIXTURES = ["opencode-skill-session.jsonl", "opencode-delegation.jsonl"]


@pytest.mark.parametrize("name", VALID_FIXTURES)
def test_recorded_fixtures_validate(name):
    problems = rawlog.validate_file(RAW_FIXTURES / name)
    assert problems == [], "\n".join(str(p) for p in problems)


@pytest.mark.parametrize("name", VALID_FIXTURES)
def test_fixture_event_ids_are_ulids(name):
    for event in rawlog.read_events(RAW_FIXTURES / name):
        assert rawlog.is_event_id(event["event_id"]), event["event_id"]


def test_fixtures_carry_harness_and_model_on_every_event():
    """Comparing a skill across models is the point; identity cannot be optional."""
    for name in VALID_FIXTURES:
        for event in rawlog.read_events(RAW_FIXTURES / name):
            assert event["harness"] == "opencode"
            assert event["harness_version"]
            assert event["provider"] and event["model"]
            assert event["session_id"] and event["root_session_id"]


def test_reader_refuses_an_unknown_major_version():
    path = RAW_FIXTURES / "opencode-unsupported-version.jsonl"
    with pytest.raises(rawlog.UnsupportedSchemaVersion) as excinfo:
        list(rawlog.read_events(path))
    message = str(excinfo.value)
    assert "2" in message
    assert str(RAW_SCHEMA_VERSION) in message
    assert str(path) in message


def test_reader_refuses_before_yielding_the_bad_line(tmp_path):
    """A half-consumed file is worse than a refused one."""
    good = next(rawlog.read_events(RAW_FIXTURES / "opencode-skill-session.jsonl"))
    future = dict(good, schema_version=99)
    path = tmp_path / "mixed.jsonl"
    path.write_text(
        json.dumps(good) + "\n" + json.dumps(future) + "\n", encoding="utf-8"
    )
    events = rawlog.read_events(path)
    assert next(events)["schema_version"] == 1
    with pytest.raises(rawlog.UnsupportedSchemaVersion):
        next(events)


def test_reader_reports_malformed_json_with_a_line_number(tmp_path):
    path = tmp_path / "broken.jsonl"
    path.write_text('{"schema_version": 1}\nnot json\n', encoding="utf-8")
    with pytest.raises(rawlog.RawLogError, match=r"broken\.jsonl:2"):
        list(rawlog.read_events(path))


# --------------------------------------------------------------------------- schema shape


def _event(**overrides):
    event = json.loads(
        (RAW_FIXTURES / "opencode-skill-session.jsonl").read_text().splitlines()[1]
    )
    event.update(overrides)
    return event


def test_an_activation_must_name_its_component():
    """Attribution is the whole point of an activation event."""
    assert rawlog.schema_errors(_event()) == []
    assert rawlog.schema_errors(_event(component=None))


def test_source_hash_must_look_like_a_sha256():
    bad = _event()
    bad["component"] = dict(bad["component"], source_hash="deadbeef")
    assert rawlog.schema_errors(bad)


def test_unknown_event_type_is_rejected():
    assert rawlog.schema_errors(_event(type="invented"))


def test_unknown_envelope_key_is_rejected():
    assert rawlog.schema_errors(_event(surprise=1))


def test_tool_call_requires_its_truncation_bookkeeping():
    call = json.loads(
        (RAW_FIXTURES / "opencode-skill-session.jsonl").read_text().splitlines()[2]
    )
    assert rawlog.schema_errors(call) == []
    del call["payload"]["output_length"]
    assert rawlog.schema_errors(call)


# --------------------------------------------------------------------------- writer


def test_writer_appends_and_fills_identity(tmp_path):
    path = tmp_path / "2026-09-17" / "ses_x.jsonl"
    writer = rawlog.RawLogWriter(path)
    template = _event()
    template.pop("event_id")
    template.pop("ts")
    template.pop("schema_version")

    first = writer.append(template)
    second = writer.append(template)

    assert rawlog.is_event_id(first["event_id"])
    assert first["event_id"] != second["event_id"]
    assert first["schema_version"] == RAW_SCHEMA_VERSION
    assert len(path.read_text().strip().splitlines()) == 2


def test_writer_refuses_an_invalid_event(tmp_path):
    writer = rawlog.RawLogWriter(tmp_path / "log.jsonl")
    with pytest.raises(rawlog.RawLogError, match="refusing to append"):
        writer.append(_event(type="invented"))
    assert not (tmp_path / "log.jsonl").exists()


def test_session_log_path_is_one_file_per_root_session(tmp_path):
    path = rawlog.session_log_path(tmp_path, "2026-09-17T19:44:16.523Z", "ses_abc")
    assert path == tmp_path / "2026-09-17" / "ses_abc.jsonl"


def test_session_log_path_sanitises_a_hostile_session_id(tmp_path):
    path = rawlog.session_log_path(tmp_path, "2026-09-17T00:00:00.000Z", "../../etc/passwd")
    assert path.parent == tmp_path / "2026-09-17"
    assert path.name == ".._.._etc_passwd.jsonl"


def test_log_files_skips_logger_bookkeeping(tmp_path):
    day = tmp_path / "2026-09-17"
    day.mkdir()
    (day / "ses_a.jsonl").write_text("", encoding="utf-8")
    (tmp_path / "_logger-errors.log").write_text("boom", encoding="utf-8")
    (day / "_scratch.jsonl").write_text("", encoding="utf-8")
    assert [p.name for p in rawlog.log_files(tmp_path)] == ["ses_a.jsonl"]


def test_event_ids_sort_by_time():
    earlier = rawlog.new_event_id(1_700_000_000_000)
    later = rawlog.new_event_id(1_800_000_000_000)
    assert earlier < later
    assert rawlog.is_event_id(earlier) and rawlog.is_event_id(later)


def test_file_hash_is_none_for_an_unreadable_file(tmp_path):
    assert rawlog.file_hash(tmp_path / "absent.md") is None
    present = tmp_path / "present.md"
    present.write_bytes(b"x")
    assert rawlog.file_hash(present).startswith("sha256:")


# --------------------------------------------------------------------------- rejection probes


@pytest.mark.parametrize(
    "label, mutate",
    [
        ("model is identity, not decoration", lambda e: {**e, "model": ""}),
        (
            "harness version makes a drift visible",
            lambda e: {k: v for k, v in e.items() if k != "harness_version"},
        ),
        ("an unknown harness", lambda e: {**e, "harness": "emacs"}),
        ("an unknown origin", lambda e: {**e, "origin": "backfill"}),
        ("an event id that will not sort", lambda e: {**e, "event_id": "not-a-ulid"}),
        (
            "an unknown component kind",
            lambda e: {**e, "component": {**e["component"], "kind": "plugin"}},
        ),
        ("a stray payload key", lambda e: {**e, "payload": {**e["payload"], "surprise": 1}}),
        (
            "an activation with no trigger",
            lambda e: {
                **e,
                "payload": {k: v for k, v in e["payload"].items() if k != "trigger"},
            },
        ),
        (
            "a trigger the logger cannot produce",
            lambda e: {**e, "payload": {**e["payload"], "trigger": "telepathy"}},
        ),
        ("an unknown redaction kind", lambda e: {**e, "redactions": [{"kind": "vibes", "count": 1}]}),
        (
            "a redaction that redacted nothing",
            lambda e: {**e, "redactions": [{"kind": "api_key", "count": 0}]},
        ),
    ],
    ids=lambda v: v if isinstance(v, str) else "",
)
def test_the_schema_rejects(label, mutate):
    assert rawlog.schema_errors(mutate(_event())), label
