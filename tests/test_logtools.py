"""Read-side tools: validation, the summary, and the missed-activation signal."""

from __future__ import annotations

import json
import shutil

import pytest

from conftest import RAW_FIXTURES, write_manifest
from wikiskill import collection as collection_mod
from wikiskill import logtools, paths


def seed(raw_dir, *fixtures, day="2026-09-17"):
    target = raw_dir / day
    target.mkdir(parents=True, exist_ok=True)
    for name in fixtures:
        shutil.copy(RAW_FIXTURES / name, target / name)
    return target


@pytest.fixture
def seeded(xdg):
    raw = paths.raw_dir("dsh")
    seed(raw, "opencode-skill-session.jsonl", "opencode-delegation.jsonl")
    return raw


def test_validate_counts_events_and_activations(seeded):
    report = logtools.validate("dsh")
    assert report.ok
    assert report.files == 2
    assert report.events == 14
    assert report.activations == 2
    assert report.problems == []


def test_validate_reports_a_schema_error_with_its_location(xdg):
    raw = paths.raw_dir("dsh")
    day = raw / "2026-09-17"
    day.mkdir(parents=True)
    line = (RAW_FIXTURES / "opencode-skill-session.jsonl").read_text().splitlines()[0]
    (day / "ses_bad.jsonl").write_text(line.replace('"type":"session_start"', '"type":"nope"'), encoding="utf-8")

    report = logtools.validate("dsh")

    assert not report.ok
    assert any("ses_bad.jsonl" in str(p) for p in report.problems)


def test_validate_refuses_a_future_schema_version_without_crashing(xdg):
    raw = paths.raw_dir("dsh")
    seed(raw, "opencode-unsupported-version.jsonl")
    report = logtools.validate("dsh")
    assert not report.ok
    assert any("not supported" in message for message in report.refused)


def test_stats_summarise_sessions_models_and_components(seeded):
    summary = logtools.stats("dsh")
    assert summary.sessions == 2
    assert summary.events == 14
    assert summary.days == ["2026-09-17"]
    assert summary.by_type["tool_call"] == 4
    assert summary.by_model["ollama/qwen3:1.7b"] == 14
    assert summary.by_component["skill:govern/preregister"] == 7
    assert summary.by_component["agent:datalad-doer"] == 5
    assert summary.bytes > 0


def test_stats_flag_a_watched_source_read_without_an_activation(xdg, plugin_source):
    """A model that consumed a skill some way the logger missed is worth surfacing."""
    write_manifest(
        xdg,
        "dsh",
        f'name = "dsh"\nsources = [{{ path = "{plugin_source}", layout = "claude-plugin" }}]\n'
        '[watch]\nskills = ["govern/preregister"]\n',
    )
    coll = collection_mod.load("dsh")
    watched_path = str(plugin_source / "govern" / "skills" / "preregister" / "SKILL.md")

    raw = paths.raw_dir("dsh")
    day = raw / "2026-09-17"
    day.mkdir(parents=True)
    lines = (RAW_FIXTURES / "opencode-skill-session.jsonl").read_text().splitlines()
    # Keep the session and a read of the watched file, but drop the activation.
    read_line = lines[3].replace(
        "/home/u/Projects/dsh/openspec/specs/preregistration/spec.md", watched_path
    )
    (day / "ses_silent.jsonl").write_text(lines[0] + "\n" + read_line + "\n", encoding="utf-8")

    summary = logtools.stats(coll)

    assert summary.reads_without_activation == ["ses_silent"]


def test_stats_do_not_flag_a_session_that_activated(xdg, plugin_source, seeded):
    write_manifest(
        xdg,
        "dsh",
        f'name = "dsh"\nsources = [{{ path = "{plugin_source}", layout = "claude-plugin" }}]\n'
        '[watch]\nskills = ["govern/preregister"]\n',
    )
    coll = collection_mod.load("dsh")
    assert logtools.stats(coll).reads_without_activation == []


def test_stats_on_an_empty_log_are_zeroes(xdg):
    summary = logtools.stats("never-used")
    assert summary.sessions == 0 and summary.events == 0
    assert summary.errors == []


def test_tail_returns_the_most_recent_events_in_order(seeded):
    events = list(logtools.tail("dsh", count=5))
    assert len(events) == 5
    assert [e["event_id"] for e in events] == sorted(e["event_id"] for e in events)


def test_tail_of_an_empty_log_is_empty(xdg):
    assert list(logtools.tail("never-used")) == []


def test_validate_reports_the_real_line_of_a_bad_event(xdg):
    # A blank line above the bad event used to shift every reported line number.
    raw = paths.raw_dir("dsh")
    day = raw / "2026-09-17"
    day.mkdir(parents=True)
    lines = (RAW_FIXTURES / "opencode-skill-session.jsonl").read_text().splitlines()
    broken = lines[1].replace('"type":"component_activated"', '"type":"nope"')
    (day / "ses_gap.jsonl").write_text(
        f"{lines[0]}\n\n\n{broken}\n", encoding="utf-8"
    )

    report = logtools.validate("dsh")
    assert [p.line for p in report.problems] == [4]


def test_stats_survives_a_malformed_component(xdg):
    # `stats` is what a broken log is looked at with, so it reports rather than raising.
    raw = paths.raw_dir("dsh")
    day = raw / "2026-09-17"
    day.mkdir(parents=True)
    lines = (RAW_FIXTURES / "opencode-skill-session.jsonl").read_text().splitlines()
    mangled = lines[1].replace(
        '"component":{"kind":"skill"', '"component":{"unexpected":"shape"'
    )
    (day / "ses_odd.jsonl").write_text(f"{lines[0]}\n{mangled}\n", encoding="utf-8")

    summary = logtools.stats("dsh")
    assert summary.events == 2
    assert any(label.startswith("?:") for label in summary.by_component)


def test_tail_reads_a_line_that_has_no_event_id(xdg):
    raw = paths.raw_dir("dsh")
    day = raw / "2026-09-17"
    day.mkdir(parents=True)
    lines = (RAW_FIXTURES / "opencode-skill-session.jsonl").read_text().splitlines()
    stripped = json.loads(lines[0])
    del stripped["event_id"]
    (day / "ses_noid.jsonl").write_text(
        json.dumps(stripped) + "\n" + lines[1] + "\n", encoding="utf-8"
    )

    events = list(logtools.tail("dsh", count=10))
    assert len(events) == 2


def test_tail_skips_a_log_it_cannot_read_instead_of_stopping(xdg):
    # One log from a future schema version must not end a tail over a whole collection.
    raw = paths.raw_dir("dsh")
    day = seed(raw, "opencode-skill-session.jsonl")
    (day / "ses_future.jsonl").write_text(
        '{"schema_version":99,"event_id":"01J000000000000000000FUTUR","type":"session_start"}\n',
        encoding="utf-8",
    )

    events = list(logtools.tail("dsh", count=50))
    assert events
    assert all(event.get("schema_version") == 1 for event in events)
