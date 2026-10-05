"""The collection graph: dependency edges from declarations, conflict edges from routing."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

from conftest import FIXTURES, write_manifest
from wikiskill import collection as collection_mod
from wikiskill import graph, paths
from wikiskill.cli import main

SOURCE = FIXTURES / "graph-source"
RELEASE, PUBLISH = "disseminate/dataset-release", "disseminate/publish"
CHECKPOINT, DOER = "analyze/checkpoint", "archive/archive-doer"
GEMMA, QWEN = "ollama/gemma4", "ollama/qwen3:1.7b"

#: The real repository, when this machine has it. Nothing here writes to it.
DSH = Path(
    os.environ.get("WIKISKILL_DSH", "~/Projects/claude/data-science-harness/plugins")
).expanduser()


@pytest.fixture
def dsh(xdg):
    write_manifest(
        xdg,
        "dsh",
        f'name = "dsh"\nsources = [{{ path = "{SOURCE}", layout = "claude-plugin" }}]\n'
        '[watch]\nskills = ["*"]\n',
    )
    return collection_mod.load("dsh")


def write_run(coll, run_id, routes, *, proposal=None):
    """``routes`` maps (task, model) to (expected route, first activation of each repeat)."""
    directory = paths.evals_dir(coll.name) / run_id
    directory.mkdir(parents=True)
    manifest = {"run_id": run_id, "suite": "routing", "collection": coll.name}
    if proposal:
        manifest["proposal"] = proposal
    (directory / "run.json").write_text(json.dumps(manifest))
    rows = [
        {
            "run_id": run_id,
            "task_id": task,
            "model": model,
            "condition": "routed",
            "repeat": repeat,
            "outcome": "completed",
            "passed": None,
            "expected": {"primary": expected},
            "activations": [{"kind": "skill", "name": chosen}] if chosen else [],
        }
        for (task, model), (expected, chosen_per_repeat) in routes.items()
        for repeat, chosen in enumerate(chosen_per_repeat)
    ]
    (directory / "results.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    return directory


def edge(found, kind, source, target):
    (match,) = [e for e in found.edges if (e.kind, e.source, e.target) == (kind, source, target)]
    return match


def test_a_declared_delegation_points_at_the_plugins_agents(dsh):
    found = graph.build(dsh)
    declared = edge(found, graph.DEPENDENCY, RELEASE, DOER)
    assert declared.weight == graph.DECLARED
    (where,) = declared.evidence
    assert where["via"] == "delegates_to"
    assert where["path"].endswith("dataset-release/SKILL.md") and where["line"] == 8


def test_a_full_name_in_a_body_is_a_weaker_dependency(dsh):
    found = graph.build(dsh)
    mention = edge(found, graph.DEPENDENCY, RELEASE, PUBLISH)
    assert mention.weight == graph.MENTIONED
    assert mention.evidence[0]["via"] == "mention" and mention.evidence[0]["line"] == 14
    assert not [e for e in found.edges if e.source == PUBLISH], (
        "a bare name in prose, or one in the frontmatter, is not a mention"
    )


def test_a_delegation_outside_the_collection_is_kept_unresolved(dsh):
    (unresolved,) = graph.build(dsh).unresolved
    assert (unresolved["component"], unresolved["delegates_to"]) == (CHECKPOINT, "datalad")
    assert unresolved["line"] == 7


def test_routing_confusion_is_a_conflict_edge_per_model(dsh):
    write_run(
        dsh,
        "01R1",
        {
            ("save-progress", GEMMA): ("checkpoint", ["dataset-release", "dataset-release", None]),
            ("save-progress", QWEN): ("checkpoint", ["checkpoint", "checkpoint", "checkpoint"]),
            ("cut-release", GEMMA): ("dataset-release", ["dataset-release"]),
        },
    )
    found = graph.build(dsh)
    conflict = edge(found, graph.CONFLICT, CHECKPOINT, RELEASE)
    assert conflict.per_model == {GEMMA: pytest.approx(2 / 3, abs=1e-3), QWEN: 0.0}
    assert conflict.weight == conflict.per_model[GEMMA]
    assert conflict.evidence == [
        {"run_id": "01R1", "task_id": "save-progress", "model": GEMMA, "taken": 2, "repeats": 3}
    ]
    assert found.runs == ["01R1"]
    assert not [e for e in found.edges if e.kind == graph.CONFLICT and e.source == RELEASE]


def test_candidate_runs_add_no_conflict(dsh):
    write_run(dsh, "01CAND", {("t", GEMMA): ("checkpoint", ["publish"])}, proposal="p-001")
    found = graph.build(dsh)
    assert found.runs == []
    assert not [e for e in found.edges if e.kind == graph.CONFLICT]


def test_neighbours_are_depth_one_both_ways_and_thresholded(dsh):
    write_run(
        dsh, "01R1", {("t", GEMMA): ("checkpoint", ["dataset-release"] + ["checkpoint"] * 19)}
    )
    found = graph.build(dsh)
    assert edge(found, graph.CONFLICT, CHECKPOINT, RELEASE).weight == 0.05

    names = [n.name for n in found.neighbours(RELEASE)]
    assert names == [DOER, PUBLISH, CHECKPOINT]
    assert [n.name for n in found.neighbours(DOER)] == [RELEASE], "the planner of the doer"
    assert CHECKPOINT not in [n.name for n in found.neighbours(RELEASE, min_conflict=0.1)]


def test_build_commits_graph_json_and_the_cli_reads_it(dsh, capsys):
    write_run(dsh, "01R1", {("t", GEMMA): ("checkpoint", ["dataset-release"])})
    assert main(["graph", "neighbours", RELEASE, "--collection", "dsh"]) == 1
    assert "no graph yet" in capsys.readouterr().err

    assert main(["graph", "build", "--collection", "dsh"]) == 0
    stored = graph.load("dsh")
    assert stored is not None and stored.runs == ["01R1"]
    log = subprocess.run(
        ["git", "-C", str(paths.wiki_dir("dsh")), "log", "-1", "--format=%s"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    assert log.startswith("graph: 2 dependency, 1 conflict edge(s) from 1 run(s)")

    capsys.readouterr()
    assert main(["graph", "show", "--collection", "dsh"]) == 0
    shown = capsys.readouterr().out
    assert f"{RELEASE} -> {DOER}  1.00  (delegates_to SKILL.md:8)" in shown
    assert f"{CHECKPOINT} delegates_to datalad: nothing in the collection" in shown
    assert main(["graph", "neighbours", DOER, "--collection", "dsh"]) == 0
    assert f"{RELEASE}  (dependency <- 1.00)" in capsys.readouterr().out


@pytest.mark.skipif(not DSH.is_dir(), reason="data-science-harness is not checked out here")
def test_the_real_release_skill_depends_on_the_archive_doer(xdg):
    write_manifest(
        xdg,
        "real",
        f'name = "real"\nsources = [{{ path = "{DSH}", layout = "claude-plugin", '
        'plugins = ["disseminate", "archive"] }]\n[watch]\nskills = ["*"]\n',
    )
    found = graph.build(collection_mod.load("real"))
    assert edge(found, graph.DEPENDENCY, RELEASE, DOER).weight == graph.DECLARED
