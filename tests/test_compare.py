"""Comparing two runs of one suite across versions of a component: the light gate."""

from __future__ import annotations

import json
import subprocess

import pytest

from wikiskill import compare as compare_mod
from wikiskill import paths
from wikiskill.cli import main
from wikiskill.compare import DOWN, SAME, UP, CompareError, Rate, wilson

MODEL = "opencode/big-pickle"


def make_run(
    root,
    run_id,
    *,
    passes,
    total=10,
    suite="datalad-doer",
    tasks=("t",),
    hash_="h1",
    condition="injected",
    model=MODEL,
    timeouts=0,
    suite_hash="sha256:s1",
):
    """A finished run on disk: `passes` of `total` units pass, then `timeouts` time out."""
    directory = root / run_id
    directory.mkdir(parents=True)
    (directory / "run.json").write_text(
        json.dumps(
            {
                "run_id": run_id,
                "suite": suite,
                "suite_hash": suite_hash,
                "collection": "dsh-datalad",
                "tasks": list(tasks),
                "components": [
                    {"kind": "agent", "name": "datalad/datalad-doer", "source_hash": hash_}
                ],
            }
        ),
        encoding="utf-8",
    )
    lines = []
    for repeat in range(total + timeouts):
        timed_out = repeat >= total
        lines.append(
            {
                "run_id": run_id,
                "suite": suite,
                "task_id": tasks[0],
                "model": model,
                "condition": condition,
                "repeat": repeat,
                "outcome": "infra_error" if timed_out else "completed",
                "reason": "timed out after 600s" if timed_out else None,
                "passed": None if timed_out else repeat < passes,
                "expected": {"primary": "datalad-doer", "agents": []},
            }
        )
    (directory / "results.jsonl").write_text(
        "".join(json.dumps(line) + "\n" for line in lines), encoding="utf-8"
    )
    return compare_mod.load_run("dsh-datalad", directory)


def tool_event(run_id, repeat, command, condition="injected", tool="bash"):
    return {
        "schema_version": 1,
        "type": "tool_call",
        "model": "big-pickle",
        "eval": {
            "run_id": run_id,
            "suite": "datalad-doer",
            "task_id": "t",
            "condition": condition,
            "repeat": repeat,
        },
        "payload": {"tool": tool, "input": {"command": command}},
    }


# --------------------------------------------------------------------------- statistics


def test_wilson_matches_a_known_value():
    low, high = wilson(5, 10)
    assert low == pytest.approx(0.2366, abs=1e-3)
    assert high == pytest.approx(0.7634, abs=1e-3)


def test_wilson_stays_inside_zero_and_one():
    assert wilson(0, 5)[0] == 0.0
    assert wilson(5, 5)[1] == pytest.approx(1.0)
    assert wilson(0, 0) is None


@pytest.mark.parametrize(
    "a, b, expected",
    [
        (Rate(5, 10), Rate(7, 10), SAME),
        (Rate(1, 20), Rate(19, 20), UP),
        (Rate(19, 20), Rate(1, 20), DOWN),
        (Rate(0, 0), Rate(5, 5), SAME),
    ],
)
def test_a_direction_needs_intervals_that_do_not_overlap(a, b, expected):
    assert compare_mod.direction(a, b) == expected


# --------------------------------------------------------------------------- comparing


def test_overlapping_intervals_say_no_detectable_difference(tmp_path):
    a = make_run(tmp_path, "A", passes=5)
    b = make_run(tmp_path, "B", passes=7, hash_="h2")
    comparison = compare_mod.compare(a, b, raw_root=tmp_path / "raw")

    ra, rb, move = comparison.rows[("injected", MODEL)]
    assert (ra.passed, ra.total, rb.passed, rb.total) == (5, 10, 7, 10)
    assert move == SAME
    assert comparison.component == "datalad/datalad-doer"
    assert (comparison.hash_a, comparison.hash_b) == ("h1", "h2")
    assert comparison.warnings == []


def test_separated_intervals_report_a_direction(tmp_path):
    a = make_run(tmp_path, "A", passes=1, total=20)
    b = make_run(tmp_path, "B", passes=19, total=20, hash_="h2")
    assert compare_mod.compare(a, b, raw_root=tmp_path / "raw").rows[("injected", "pooled")][2] == UP


def test_different_suites_are_refused(tmp_path):
    a = make_run(tmp_path, "A", passes=5)
    b = make_run(tmp_path, "B", passes=5, suite="other")
    with pytest.raises(CompareError, match="different suites"):
        compare_mod.compare(a, b)


def test_different_tasks_are_refused(tmp_path):
    a = make_run(tmp_path, "A", passes=5)
    b = make_run(tmp_path, "B", passes=5, tasks=("u",))
    with pytest.raises(CompareError, match="different tasks"):
        compare_mod.compare(a, b)


def test_different_suite_content_is_refused(tmp_path):
    a = make_run(tmp_path, "A", passes=5)
    b = make_run(tmp_path, "B", passes=5, hash_="h2", suite_hash="sha256:s2")
    with pytest.raises(CompareError, match="different content"):
        compare_mod.compare(a, b)


def test_the_same_suite_content_is_not_warned_about(tmp_path):
    a = make_run(tmp_path, "A", passes=5)
    b = make_run(tmp_path, "B", passes=5, hash_="h2")
    comparison = compare_mod.compare(a, b)
    assert not any("unverified" in warning for warning in comparison.warnings)


def test_a_run_without_a_suite_hash_is_compared_but_warned(tmp_path):
    a = make_run(tmp_path, "A", passes=5, suite_hash=None)
    b = make_run(tmp_path, "B", passes=5, hash_="h2")
    comparison = compare_mod.compare(a, b)
    assert any("suite content unverified: A" in warning for warning in comparison.warnings)


def test_the_same_version_twice_is_warned(tmp_path):
    a = make_run(tmp_path, "A", passes=5)
    b = make_run(tmp_path, "B", passes=6)
    comparison = compare_mod.compare(a, b, raw_root=tmp_path / "raw")
    assert any("same source_hash" in w for w in comparison.warnings)


def test_a_model_in_only_one_run_is_listed_not_compared(tmp_path):
    a = make_run(tmp_path, "A", passes=5)
    b = make_run(tmp_path, "B", passes=5, model="ollama/qwen3:1.7b")
    comparison = compare_mod.compare(a, b, raw_root=tmp_path / "raw")
    assert comparison.unmatched_models == ["ollama/qwen3:1.7b", MODEL]
    assert comparison.rows[("injected", "pooled")][0].total == 0


def test_timeouts_are_excluded_but_also_shown_as_failures(tmp_path):
    a = make_run(tmp_path, "A", passes=5, timeouts=0)
    b = make_run(tmp_path, "B", passes=5, hash_="h2", timeouts=4)
    comparison = compare_mod.compare(a, b, raw_root=tmp_path / "raw")

    assert comparison.rows[("injected", "pooled")][1].total == 10, "timeouts are not scored"
    counted = comparison.with_timeouts["injected"][1]
    assert (counted.passed, counted.total) == (5, 14)
    assert "timeouts as failures" in compare_mod.render(comparison)


# --------------------------------------------------------------------------- tool choice


@pytest.mark.parametrize(
    "command, expected",
    [
        ("datalad save -m x", "datalad save"),
        ("/usr/bin/git commit -m x", "git commit"),
        ("git -C . status", "git"),
        ("ls -la", "ls"),
        ("", "bash"),
    ],
)
def test_a_shell_command_is_keyed_by_program_and_subcommand(command, expected):
    assert compare_mod.tool_key(tool_event("A", 0, command)) == expected


def test_tool_choice_counts_units_not_calls(tmp_path):
    a = make_run(tmp_path, "A", passes=5)
    b = make_run(tmp_path, "B", passes=5, hash_="h2")
    raw = tmp_path / "raw" / "2026-09-22"
    raw.mkdir(parents=True)
    events = [
        tool_event("A", 0, "git commit -m x"),
        tool_event("A", 1, "datalad save -m x"),
        tool_event("B", 0, "datalad save -m x"),
        tool_event("B", 0, "datalad save -m y"),
        tool_event("B", 1, "datalad save -m x"),
        tool_event("B", 2, "", tool="read"),
        tool_event("Z", 0, "datalad push"),
    ]
    (raw / "ses.jsonl").write_text("".join(json.dumps(e) + "\n" for e in events))
    comparison = compare_mod.compare(a, b, raw_root=tmp_path / "raw")

    counts_a, units_a = comparison.tools[("injected", "A")]
    counts_b, units_b = comparison.tools[("injected", "B")]
    assert counts_a == {"datalad save": 1, "git commit": 1}
    assert counts_b == {"datalad save": 2, "read": 1}, "two saves in one unit count once"
    assert units_a == units_b == 10


# --------------------------------------------------------------------------- recording


def test_record_appends_a_decision_and_changes_nothing_else(xdg, tmp_path):
    a = make_run(tmp_path, "A", passes=5)
    b = make_run(tmp_path, "B", passes=7, hash_="h2")
    comparison = compare_mod.compare(a, b, raw_root=tmp_path / "raw")

    target = compare_mod.record("dsh-datalad", comparison, "reject", "p-001")
    compare_mod.record("dsh-datalad", comparison, "accept", "p-002")

    text = target.read_text()
    assert target == paths.wiki_dir("dsh-datalad") / "skill-impact.md"
    assert text.count("## p-") == 2
    assert "## p-001: reject" in text and "`h1`" in text and "`h2`" in text
    patterns = target.parent / "patterns"
    assert not any(patterns.iterdir()), "a decision touches no pattern"
    log = subprocess.run(
        ["git", "-C", str(target.parent), "log", "--format=%s"],
        capture_output=True,
        text=True,
        check=True,
    )
    assert log.stdout.splitlines()[0] == "accept p-002 for datalad/datalad-doer"


def test_cli_compare_writes_both_reports_and_records(xdg, tmp_path, capsys):
    evals = paths.evals_dir("dsh-datalad")
    make_run(evals, "A", passes=5)
    make_run(evals, "B", passes=7, hash_="h2")

    assert (
        main(
            [
                "compare",
                "A",
                "B",
                "--collection",
                "dsh-datalad",
                "--record",
                "accept",
                "--proposal",
                "p-001",
            ]
        )
        == 0
    )
    out = capsys.readouterr().out
    assert "no detectable difference" in out
    written = evals / "compare" / "A_vs_B"
    assert (written / "compare.md").is_file() and (written / "compare.json").is_file()
    assert "p-001: accept" in (paths.wiki_dir("dsh-datalad") / "skill-impact.md").read_text()


def test_cli_compare_refuses_mismatched_suites(xdg, capsys):
    evals = paths.evals_dir("dsh-datalad")
    make_run(evals, "A", passes=5)
    make_run(evals, "B", passes=5, suite="other")
    assert main(["compare", "A", "B", "--collection", "dsh-datalad"]) == 1
    assert "different suites" in capsys.readouterr().err
