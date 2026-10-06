"""Ranking versions of one component across models: what pools, what is best, and what is not."""

from __future__ import annotations

import json

import pytest

import test_gate
import test_refine
from test_refine import DOER, TEXT
from wikiskill import paths, rawlog
from wikiskill import version_board as board_mod
from wikiskill.cli import main
from wikiskill.compare import load_run

repo_collection = test_refine.repo_collection
evaluated = test_refine.evaluated
proposed = test_gate.proposed

COMPONENT = "archive/archive-doer"
OTHER = "archive-cli/zenodo"
SUITE_HASH = "sha256:" + "a" * 64
OTHER_HASH = "sha256:" + "c" * 64
V1, V2, V3 = ("sha256:" + digit * 64 for digit in "123")


def unit(task, model, condition, passed, *, repeat=0, verifiers=None, outcome="completed"):
    return {
        "task_id": task,
        "model": model,
        "condition": condition,
        "repeat": repeat,
        "outcome": outcome,
        "passed": passed,
        "verifiers": verifiers
        if verifiers is not None
        else [
            {"kind": "regex", "passed": True, "detail": "no DOI"},
            {"kind": "command", "passed": passed, "detail": "the task's own check"},
        ],
        "expected": {"primary": COMPONENT, "agents": []},
    }


def units(task, model, condition, passed, failed):
    """``passed`` passing then ``failed`` failing repeats of one task."""
    outcomes = [True] * passed + [False] * failed
    return [unit(task, model, condition, ok, repeat=r) for r, ok in enumerate(outcomes)]


def write_run(
    root,
    run_id,
    version,
    results,
    *,
    suite_hash=SUITE_HASH,
    other_hash=OTHER_HASH,
    proposal=None,
    component=True,
):
    directory = root / run_id
    directory.mkdir(parents=True)
    parts = [{"kind": "skill", "name": OTHER, "source_hash": other_hash}]
    if component:
        parts.insert(0, {"kind": "agent", "name": COMPONENT, "source_hash": version})
    manifest = {
        "run_id": run_id,
        "suite": "archive-doer",
        "suite_hash": suite_hash,
        "collection": "dsh",
        "harness_version": "1.18.34",
        "models": sorted({r["model"] for r in results}),
        "conditions": sorted({r["condition"] for r in results}),
        "tasks": sorted({r["task_id"] for r in results}),
        "components": parts,
        "proposal": proposal,
    }
    (directory / "run.json").write_text(json.dumps(manifest), encoding="utf-8")
    (directory / "results.jsonl").write_text(
        "".join(json.dumps(r) + "\n" for r in results), encoding="utf-8"
    )
    return directory


def loaded(*directories):
    return [load_run("", directory) for directory in directories]


@pytest.fixture
def three(tmp_path):
    """v1 with OFF on models a and b; v2 better on a, worse on b; v3 better on a, level on b."""
    v1 = write_run(
        tmp_path,
        "r1",
        V1,
        units("t", "a", "off", 2, 8)
        + units("t", "b", "off", 2, 8)
        + units("t", "a", "injected", 2, 8)
        + units("t", "b", "injected", 9, 1),
    )
    v2 = write_run(
        tmp_path,
        "r2",
        V2,
        units("t", "a", "injected", 10, 0) + units("t", "b", "injected", 4, 6),
        proposal="p-002",
    )
    v3 = write_run(
        tmp_path,
        "r3",
        V3,
        units("t", "a", "injected", 7, 3) + units("t", "b", "injected", 9, 1),
    )
    return loaded(v1, v2, v3)


# --------------------------------------------------------------------------- pooling


def test_versions_become_an_axis_and_the_first_run_is_the_baseline(three):
    board = board_mod.pool(three, COMPONENT)

    assert board.baseline == V1
    assert board.versions == [V1, V2, V3]
    assert board.others == {OTHER: OTHER_HASH}
    assert board.cells[("a", V2)].passed == 10


def test_runs_of_one_version_pool(tmp_path):
    one = write_run(tmp_path, "r1", V1, units("t", "a", "injected", 1, 1))
    two = write_run(tmp_path, "r2", V1, units("t", "a", "injected", 2, 0))

    board = board_mod.pool(loaded(one, two), COMPONENT)

    assert board.versions == [V1]
    assert (board.cells[("a", V1)].passed, board.cells[("a", V1)].total) == (3, 4)


def test_a_second_component_that_differs_is_refused(tmp_path):
    one = write_run(tmp_path, "r1", V1, units("t", "a", "injected", 1, 0))
    two = write_run(
        tmp_path, "r2", V2, units("t", "a", "injected", 1, 0), other_hash="sha256:" + "d" * 64
    )
    with pytest.raises(board_mod.LeaderboardError, match=f"{OTHER} differs between runs"):
        board_mod.pool(loaded(one, two), COMPONENT)


def test_different_suite_content_is_refused(tmp_path):
    one = write_run(tmp_path, "r1", V1, units("t", "a", "injected", 1, 0))
    two = write_run(tmp_path, "r2", V2, units("t", "a", "injected", 1, 0), suite_hash="sha256:x")
    with pytest.raises(board_mod.LeaderboardError, match="different content of suite"):
        board_mod.pool(loaded(one, two), COMPONENT)


def test_a_run_without_the_component_is_refused(tmp_path):
    one = write_run(tmp_path, "r1", V1, units("t", "a", "injected", 1, 0))
    two = write_run(tmp_path, "r2", V2, units("t", "a", "injected", 1, 0), component=False)
    with pytest.raises(board_mod.BoardError, match="recorded no source_hash"):
        board_mod.pool(loaded(one, two), COMPONENT)


def test_only_a_condition_that_uses_the_component_is_ranked(three):
    with pytest.raises(board_mod.BoardError, match="not 'off'"):
        board_mod.pool(three, COMPONENT, condition="off")


def test_a_baseline_no_run_ran_is_refused(three):
    with pytest.raises(board_mod.BoardError, match="is not a version any of these runs ran"):
        board_mod.pool(three, COMPONENT, baseline="sha256:" + "9" * 64)


def test_other_conditions_are_left_off_the_board_with_a_warning(tmp_path):
    run = write_run(
        tmp_path,
        "r1",
        V1,
        units("t", "a", "injected", 1, 0) + units("t", "a", "routed", 0, 1),
    )
    board = board_mod.pool(loaded(run), COMPONENT)
    assert board.cells[("a", V1)].total == 1
    assert any("routed" in w for w in board.warnings)


# --------------------------------------------------------------------------- OFF and lift


def test_off_is_shared_by_every_version_of_a_model(three):
    board = board_mod.pool(three, COMPONENT)

    assert board.control["a"].total == 10
    entries = {e.version: e for e in board.entries("a")}
    assert entries[V2].lift == pytest.approx(1.0 - 0.2), "v2 ran no OFF; v1's OFF is its control"
    assert entries[V1].lift == pytest.approx(0.0)


def test_units_that_did_not_run_are_counted_beside_the_rate(tmp_path):
    run = write_run(
        tmp_path,
        "r1",
        V1,
        [*units("t", "a", "injected", 1, 0), unit("t", "a", "injected", None, outcome="skipped")],
    )
    board = board_mod.pool(loaded(run), COMPONENT)
    (entry,) = board.entries("a")
    assert (entry.rate.total, entry.not_run) == (1, 1)


# --------------------------------------------------------------------------- per model


def test_the_best_version_per_model_carries_its_direction(three):
    board = board_mod.pool(three, COMPONENT)

    best_a = board.best("a")
    assert best_a is not None and best_a.version == V2
    assert best_a.direction == "up", "10/10 against 2/10: the intervals do not overlap"
    best_b = board.best("b")
    assert best_b is not None and best_b.version == V1, "a tie goes to the earlier version"
    assert best_b.direction == "no detectable difference"


def test_a_fall_beyond_the_tolerance_is_a_regression(three):
    board = board_mod.pool(three, COMPONENT)

    assert board.regression("b", V2), "9/10 to 4/10 falls by half"
    assert not board.regression("a", V2)
    assert not board.regression("b", V1), "the baseline never regresses against itself"


# --------------------------------------------------------------------------- overall


def test_a_higher_mean_that_regresses_a_model_is_not_best_overall(three):
    board = board_mod.pool(three, COMPONENT)

    rows = {row["version"]: row for row in board.overall()}
    assert rows[V2]["mean"] == pytest.approx(0.7)
    assert rows[V3]["mean"] == pytest.approx(0.8)
    assert rows[V2]["regressions"] == ["b"]
    best = board.best_overall()
    assert best is not None and best["version"] == V3


def test_a_version_that_regresses_is_still_ranked_but_never_named(tmp_path):
    v1 = write_run(
        tmp_path, "r1", V1, units("t", "a", "injected", 5, 5) + units("t", "b", "injected", 9, 1)
    )
    v2 = write_run(
        tmp_path, "r2", V2, units("t", "a", "injected", 10, 0) + units("t", "b", "injected", 5, 5)
    )

    board = board_mod.pool(loaded(v1, v2), COMPONENT)

    rows = {row["version"]: row for row in board.overall()}
    assert rows[V2]["mean"] > rows[V1]["mean"]
    best = board.best_overall()
    assert best is not None and best["version"] == V1
    (line,) = [row for row in board_mod.render(board).splitlines() if row.startswith("| `2222")]
    assert "| b |" in line, "the overall table names the model it regressed"


def test_the_overall_mean_uses_only_models_that_ran_every_version(tmp_path):
    v1 = write_run(
        tmp_path,
        "r1",
        V1,
        units("t", "a", "injected", 5, 5) + units("t", "c", "injected", 0, 10),
    )
    v2 = write_run(tmp_path, "r2", V2, units("t", "a", "injected", 6, 4))

    board = board_mod.pool(loaded(v1, v2), COMPONENT)

    assert board.panel == ["a"]
    assert board.left_out == ["c"]
    rows = {row["version"]: row for row in board.overall()}
    assert rows[V1]["mean"] == pytest.approx(0.5), "model c is left out of v1's mean too"
    assert "Left out, missing a version: c." in board_mod.render(board)


def test_versions_are_paired_with_the_baseline_over_model_and_task_cells(tmp_path):
    v1 = write_run(
        tmp_path,
        "r1",
        V1,
        units("t1", "a", "injected", 1, 1)
        + units("t2", "a", "injected", 1, 1)
        + units("t3", "a", "injected", 2, 0),
    )
    v2 = write_run(
        tmp_path,
        "r2",
        V2,
        units("t1", "a", "injected", 2, 0)
        + units("t2", "a", "injected", 2, 0)
        + units("t3", "a", "injected", 2, 0),
    )
    board = board_mod.pool(loaded(v1, v2), COMPONENT)

    rows = {row["version"]: row for row in board.overall()}
    assert (rows[V2]["won"], rows[V2]["lost"]) == (2, 0)
    assert rows[V2]["sign_test_p"] == pytest.approx(0.5)
    assert rows[V1]["sign_test_p"] is None


def test_one_task_collapsing_is_a_regression_though_the_model_barely_moves(tmp_path):
    tasks = [f"t{i}" for i in range(10)]
    base = [r for task in tasks for r in units(task, "a", "injected", 3, 0)]
    fell = [r for task in tasks[1:] for r in units(task, "a", "injected", 3, 0)]
    fell += units(tasks[0], "a", "injected", 0, 3)
    v1 = write_run(tmp_path, "r1", V1, base)
    v2 = write_run(tmp_path, "r2", V2, fell)

    board = board_mod.pool(loaded(v1, v2), COMPONENT)

    assert board.entries("a")[1].direction == "no detectable difference", "27/30 against 30/30"
    assert board.fallen_tasks("a", V2) == ["t0"]
    assert board.regression("a", V2)
    assert "fell on t0" in board_mod.render(board)


def test_a_regression_on_a_model_left_out_of_the_panel_still_counts(tmp_path):
    v1 = write_run(
        tmp_path,
        "r1",
        V1,
        units("t", "a", "injected", 5, 5) + units("t", "m", "injected", 10, 0),
    )
    v2 = write_run(
        tmp_path,
        "r2",
        V2,
        units("t", "a", "injected", 9, 1) + units("t", "m", "injected", 0, 10),
    )
    v3 = write_run(tmp_path, "r3", V3, units("t", "a", "injected", 6, 4))

    board = board_mod.pool(loaded(v1, v2, v3), COMPONENT)

    assert board.panel == ["a"], "m did not run v3"
    rows = {row["version"]: row for row in board.overall()}
    assert rows[V2]["regressions"] == ["m"]
    best = board.best_overall()
    assert best is not None and best["version"] == V3, "v2 has the top mean but broke m"


def test_a_version_that_never_ran_on_a_model_is_shown_not_run(tmp_path):
    v1 = write_run(tmp_path, "r1", V1, units("t", "a", "injected", 5, 5))
    skipped = [unit("t", "a", "injected", None, repeat=r, outcome="infra_error") for r in range(4)]
    v2 = write_run(tmp_path, "r2", V2, skipped)

    board = board_mod.pool(loaded(v1, v2), COMPONENT)

    entries = {e.version: e for e in board.entries("a")}
    assert entries[V2].rate.total == 0 and entries[V2].not_run == 4
    best = board.best("a")
    assert best is not None and best.version == V1
    (line,) = [r for r in board_mod.render(board).splitlines() if r.startswith("| a |  | `2222")]
    assert "| 4 |" in line and "not run" in line
    assert board.left_out == ["a"]


def test_boards_ranked_differently_are_written_apart(three, tmp_path):
    injected = board_mod.pool(three, COMPONENT)
    against_v3 = board_mod.pool(three, COMPONENT, baseline=V3)
    critical = board_mod.load_critical(critical_file(tmp_path, "- { task: t, verifier: 0 }\n"))
    checked = board_mod.pool(three, COMPONENT, critical=critical)

    found = {board_mod.output_dir("dsh", b) for b in (injected, against_v3, checked)}
    assert len(found) == 3


def test_a_baseline_no_run_ran_names_the_versions_that_did(three):
    with pytest.raises(board_mod.BoardError, match=r"they ran p-002, .*--baseline"):
        board_mod.pool(three, COMPONENT, baseline="sha256:" + "9" * 64, labels={V1: "p-002"})


def test_the_sign_test():
    assert board_mod.sign_test(0, 0) == 1.0
    assert board_mod.sign_test(10, 0) == pytest.approx(2 / 1024, abs=1e-6)
    assert board_mod.sign_test(3, 3) == 1.0


# --------------------------------------------------------------------------- critical checks


def critical_file(tmp_path, body):
    path = tmp_path / "critical.yaml"
    path.write_text(body, encoding="utf-8")
    return path


def test_a_critical_failure_disqualifies_a_version_everywhere(tmp_path):
    invented = [
        {"kind": "regex", "passed": False, "detail": "negated: DOI found"},
        {"kind": "command", "passed": True, "detail": "tags unmoved"},
    ]
    v1 = write_run(
        tmp_path, "r1", V1, units("t", "a", "injected", 5, 5) + units("t", "b", "injected", 5, 5)
    )
    v2 = write_run(
        tmp_path,
        "r2",
        V2,
        [
            *units("t", "a", "injected", 9, 0),
            unit("t", "a", "injected", False, repeat=9, verifiers=invented),
            *units("t", "b", "injected", 9, 1),
        ],
    )
    critical = board_mod.load_critical(critical_file(tmp_path, "- { task: '*', verifier: 0 }\n"))

    board = board_mod.pool(loaded(v1, v2), COMPONENT, critical=critical)

    assert board.disqualified(V2) and not board.disqualified(V1)
    assert board.best("b").version == V1, "disqualified on b too, where it did not fail"
    assert board.best_overall()["version"] == V1
    found = board.as_dict()["critical_failures"][V2]
    assert any(f["model"] == "a" and f["detail"] == "negated: DOI found" for f in found)
    assert "failed verifier 0 of `t` on a" in board_mod.render(board)
    assert board.as_dict()["critical"]["content_hash"].startswith("sha256:")


def test_an_ordinary_failure_does_not_disqualify(three, tmp_path):
    critical = board_mod.load_critical(critical_file(tmp_path, "- { task: t, verifier: 0 }\n"))
    board = board_mod.pool(three, COMPONENT, critical=critical)
    assert not any(board.disqualified(v) for v in board.versions)
    assert "No version failed a critical check." in board_mod.render(board)


@pytest.mark.parametrize(
    ("body", "message"),
    [
        ("- { task: t, verifier: 5 }\n", "records 2 verifier"),
        ("- { task: nope, verifier: 0 }\n", "none of the runs ran"),
        ("- { task: '*', verifier: 2 }\n", "fewer than 3 verifiers"),
    ],
)
def test_a_critical_check_a_task_does_not_have_is_refused(three, tmp_path, body, message):
    critical = board_mod.load_critical(critical_file(tmp_path, body))
    with pytest.raises(board_mod.BoardError, match=message):
        board_mod.pool(three, COMPONENT, critical=critical)


@pytest.mark.parametrize(
    ("body", "message"),
    [
        ("[]\n", "non-empty list"),
        ("- { task: t }\n", "exactly `task` and `verifier`"),
        ("- { task: t, verifier: -1 }\n", "0-based index"),
        ("- { task: '', verifier: 0 }\n", "task id or `\\*`"),
        ("- [unclosed\n", "not valid YAML"),
    ],
)
def test_a_malformed_critical_file_is_refused(tmp_path, body, message):
    with pytest.raises(board_mod.BoardError, match=message):
        board_mod.load_critical(critical_file(tmp_path, body))


# --------------------------------------------------------------------------- output


def test_the_json_keeps_every_unit_behind_a_figure(three, tmp_path):
    board = board_mod.pool(three, COMPONENT, labels={V2: "p-002"})
    md, js = board_mod.write(board, tmp_path / "out")
    data = json.loads(js.read_text())

    rows = [u for u in data["units"] if u["model"] == "a" and u["version"] == V2]
    assert len(rows) == 10 and {u["run_id"] for u in rows} == {"r2"}
    assert data["versions_compared"] == 3
    assert data["best_overall"]["version"] == V3
    assert data["per_model"]["a"]["best"]["label"] == "p-002"
    text = md.read_text()
    assert "`p-002`" in text and "versions compared: 3" in text
    assert "flattered by noise" in text


# --------------------------------------------------------------------------- the CLI


def doer_run(coll, run_id, version, rows, *, proposal=None):
    directory = paths.evals_dir(coll.name) / run_id
    directory.mkdir(parents=True)
    (directory / "run.json").write_text(
        json.dumps(
            {
                "run_id": run_id,
                "suite": "doer-suite",
                "suite_hash": SUITE_HASH,
                "collection": coll.name,
                "tasks": ["t"],
                "components": [{"kind": "agent", "name": DOER, "source_hash": version}],
                "proposal": proposal,
            }
        )
    )
    (directory / "results.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    return run_id


def test_the_cli_labels_versions_and_writes_under_versions(proposed, capsys):
    coll, _, _ = proposed
    candidate = test_gate.meta(coll)["candidate_hash"]
    current = rawlog.content_hash(TEXT.encode())
    base = doer_run(
        coll, "01BASE", current, units("t", "m", "off", 1, 1) + units("t", "m", "injected", 1, 1)
    )
    cand = doer_run(coll, "01CAND", candidate, units("t", "m", "injected", 2, 0), proposal="p-001")

    code = main(["leaderboard", base, cand, "--collection", "dsh", "--by-version", DOER])

    out = capsys.readouterr().out
    assert code == 0
    assert "baseline: `current`" in out and "`p-001`" in out
    written = paths.evals_dir("dsh") / "versions" / "datalad-datalad-doer"
    assert len(list(written.glob("*/board.md"))) == 1


def test_the_cli_refuses_board_options_without_by_version(proposed, capsys):
    assert main(["leaderboard", "r", "--collection", "dsh", "--baseline", "current"]) == 2
    assert "only apply with --by-version" in capsys.readouterr().err


def test_the_cli_needs_a_collection_to_name_versions(tmp_path, capsys):
    run = write_run(tmp_path, "r1", V1, units("t", "a", "injected", 1, 0))
    assert main(["leaderboard", str(run), "--by-version", COMPONENT]) == 2
    assert "--by-version needs --collection" in capsys.readouterr().err


def test_the_cli_reports_a_refused_board_as_misuse(proposed, capsys):
    coll, _, _ = proposed
    current = rawlog.content_hash(TEXT.encode())
    run = doer_run(coll, "01BASE", current, units("t", "m", "injected", 1, 0))
    code = main(
        ["leaderboard", run, "--collection", "dsh", "--by-version", DOER, "--condition", "routed"]
    )
    assert code == 0, "a routed board of a run with no routed units is empty, not refused"
    capsys.readouterr()
    assert (
        main(
            ["leaderboard", run, "--collection", "dsh", "--by-version", DOER, "--baseline", "p-009"]
        )
        == 2
    )
    assert "p-009" in capsys.readouterr().err
