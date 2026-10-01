"""Pooling runs from several machines: what is refused, what counts, and how it ranks."""

from __future__ import annotations

import json

import pytest

from wikiskill import leaderboard
from wikiskill.cli import main
from wikiskill.compare import load_run
from wikiskill.report import build_report, render_markdown

SUITE_HASH = "sha256:" + "a" * 64
SKILL_HASH = "sha256:" + "b" * 64


def result(task, model, condition, *, passed=None, first=None, expected="trace", outcome=None):
    return {
        "task_id": task,
        "model": model,
        "condition": condition,
        "repeat": 0,
        "outcome": outcome or "completed",
        "passed": passed,
        "activations": [{"kind": "skill", "name": first}] if first else [],
        "expected": {"primary": expected, "agents": []},
    }


def write_run(
    root, run_id, results, *, suite_hash=SUITE_HASH, skill_hash=SKILL_HASH, contexts=None
):
    directory = root / run_id
    directory.mkdir(parents=True)
    models = sorted({r["model"] for r in results})
    manifest = {
        "run_id": run_id,
        "suite": "toy-routing",
        "suite_hash": suite_hash,
        "collection": "self",
        "harness_version": "1.18.34",
        "models": models,
        "conditions": sorted({r["condition"] for r in results}),
        "tasks": sorted({r["task_id"] for r in results}),
        "components": [{"kind": "skill", "name": "trace", "source_hash": skill_hash}],
        "preflight": {
            model: {"details": {"context_tokens": (contexts or {}).get(model, 16384)}}
            for model in models
        },
    }
    (directory / "run.json").write_text(json.dumps(manifest), encoding="utf-8")
    (directory / "results.jsonl").write_text(
        "".join(json.dumps(r) + "\n" for r in results), encoding="utf-8"
    )
    return directory


def loaded(*directories):
    return [load_run("", directory) for directory in directories]


# --------------------------------------------------------------------------- refusals


def test_runs_of_different_suite_content_are_refused(tmp_path):
    one = write_run(tmp_path, "r1", [result("t", "m", "routed", first="trace")])
    two = write_run(
        tmp_path, "r2", [result("t", "m", "routed", first="trace")], suite_hash="sha256:other"
    )
    with pytest.raises(leaderboard.LeaderboardError, match="different content of suite"):
        leaderboard.pool(loaded(one, two))


def test_runs_of_different_component_versions_are_refused(tmp_path):
    one = write_run(tmp_path, "r1", [result("t", "m", "routed", first="trace")])
    two = write_run(
        tmp_path, "r2", [result("t", "m", "routed", first="trace")], skill_hash="sha256:" + "c" * 64
    )
    with pytest.raises(leaderboard.LeaderboardError, match="trace differs between runs"):
        leaderboard.pool(loaded(one, two))


# --------------------------------------------------------------------------- counting


def test_two_machines_pool_per_model_and_condition(tmp_path):
    one = write_run(
        tmp_path,
        "laptop-a",
        [result("t1", "m", "routed", first="trace"), result("t2", "m", "routed", first="other")],
        contexts={"m": 16384},
    )
    two = write_run(
        tmp_path,
        "laptop-b",
        [result("t1", "m", "routed", first="trace"), result("t2", "m", "routed", first="trace")],
        contexts={"m": 32768},
    )

    board = leaderboard.pool(loaded(one, two))

    cell = board.cells[("m", "routed")]
    assert (cell.passed, cell.total) == (3, 4)
    assert cell.runs == {"laptop-a", "laptop-b"}
    assert cell.contexts == {16384, 32768}, "machines that served different contexts say so"
    assert (
        board.matrix[("t2", "m", "routed")].passed,
        board.matrix[("t2", "m", "routed")].total,
    ) == (1, 2)


def test_a_route_counts_only_where_one_is_possible(tmp_path):
    """OFF installs nothing and INJECTED denies the skill: a route there fails by construction."""
    run = write_run(
        tmp_path,
        "r1",
        [
            result("t", "m", "off"),
            result("t", "m", "routed", first="trace"),
            result("t", "m", "injected"),
        ],
    )

    board = leaderboard.pool(loaded(run))

    assert board.cells[("m", "routed")].total == 1
    assert board.cells[("m", "off")].total == 0
    assert board.cells[("m", "injected")].total == 0
    assert board.bases == {"t": "route"}


def test_verifiers_decide_under_every_condition(tmp_path):
    run = write_run(
        tmp_path,
        "r1",
        [
            result("c", "m", "off", passed=True, expected=None),
            result("c", "m", "routed", passed=False, expected=None),
        ],
    )

    board = leaderboard.pool(loaded(run))

    assert (board.cells[("m", "off")].passed, board.cells[("m", "off")].total) == (1, 1)
    assert (board.cells[("m", "routed")].passed, board.cells[("m", "routed")].total) == (0, 1)
    assert board.bases == {"c": "verifier"}


def test_a_unit_that_did_not_run_is_counted_beside_the_rate(tmp_path):
    run = write_run(
        tmp_path,
        "r1",
        [
            result("t", "m", "routed", first="trace"),
            result("t2", "m", "routed", outcome="infra_error"),
        ],
    )

    cell = leaderboard.pool(loaded(run)).cells[("m", "routed")]

    assert (cell.passed, cell.total, cell.not_run) == (1, 1, 1)


# --------------------------------------------------------------------------- ranking


def test_a_place_is_marked_when_it_is_not_a_finding(tmp_path):
    results = [result(f"t{n}", "strong", "routed", first="trace") for n in range(12)]
    results += [
        result(f"t{n}", "close", "routed", first="trace" if n < 10 else None) for n in range(12)
    ]
    results += [result(f"t{n}", "weak", "routed") for n in range(12)]
    run = write_run(tmp_path, "r1", results)

    ranked = leaderboard.pool(loaded(run)).ranked("routed")

    assert [cell.model for cell, _ in ranked] == ["strong", "close", "weak"]
    assert [clear for _, clear in ranked] == [False, False, True]
    text = leaderboard.render(leaderboard.pool(loaded(run)))
    assert "| 2≈ | close |" in text
    assert "| 3 | weak |" in text


# --------------------------------------------------------------------------- surfaces


def test_the_cli_pools_run_directories_and_writes_both_files(tmp_path, capsys):
    one = write_run(tmp_path / "in", "r1", [result("t", "m", "routed", first="trace")])
    two = write_run(tmp_path / "in", "r2", [result("t", "m", "routed")])
    out = tmp_path / "out"

    assert main(["leaderboard", str(one), str(two), "--out", str(out)]) == 0

    assert "1/2" in (out / "leaderboard.md").read_text(encoding="utf-8")
    data = json.loads((out / "leaderboard.json").read_text(encoding="utf-8"))
    assert data["ranking"]["routed"][0]["total"] == 2
    assert "wrote" in capsys.readouterr().out


def test_the_cli_says_so_when_a_run_id_has_no_collection(tmp_path, capsys):
    assert main(["leaderboard", "01NOSUCHRUN"]) == 2
    assert "--collection" in capsys.readouterr().err


def test_the_cli_refuses_runs_it_cannot_pool(tmp_path, capsys):
    one = write_run(tmp_path, "r1", [result("t", "m", "routed", first="trace")])
    two = write_run(tmp_path, "r2", [result("t", "m", "routed")], suite_hash="sha256:other")
    assert main(["leaderboard", str(one), str(two), "--out", str(tmp_path / "out")]) == 1
    assert "different content of suite" in capsys.readouterr().err


def test_a_single_runs_report_carries_the_same_pooled_table(tmp_path):
    run = write_run(tmp_path, "r1", [result("t", "m", "routed", first="trace")])
    loaded_run = load_run("", run)

    report = build_report(list(loaded_run.results), loaded_run.manifest)

    assert report["pooled"]["routed"][0]["passed"] == 1
    assert "## Pooled per model and condition" in render_markdown(report)
