"""add-findings-export: the report over the pool, the call classifier, and study findings."""

from __future__ import annotations

import csv
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from test_leaderboard import result
from test_pilot_reporting import judged
from test_version_board import COMPONENT, V1, V2, units
from test_version_board import write_run as write_versioned
from wikiskill import findings
from wikiskill import report as report_mod
from wikiskill.cli import main

ROW_KEYS = {
    "task_id",
    "model",
    "condition",
    "attempted",
    "pass_rate",
    "pass_basis",
    "failed_verifiers",
    "rubric",
    "tokens",
    "wall_time_ms",
    "outcomes",
    "harness",
}


def _rows(results):
    report = report_mod.build_report(results, {"run_id": "r", "suite": "toy-routing"})
    return {(row["task_id"], row["condition"]): row for row in report["rows"]}


def test_report_rows_keep_their_keys_and_take_counts_from_the_pool():
    ran = result("t", "m", "routed", passed=True, first="trace")
    ran.update(duration_ms=2000, tokens={"input": 10, "output": 5, "reasoning": 1})
    lost = result("t", "m", "routed", passed=False, outcome="infra_error")
    rows = _rows([ran, lost])

    row = rows[("t", "routed")]
    assert set(row) >= ROW_KEYS
    assert (row["pass_rate"], row["pass_basis"]) == (1.0, "verifier")
    assert row["tokens"] == {"input": 10, "output": 5, "reasoning": 1}
    assert row["wall_time_ms"] == 2000
    assert row["outcomes"] == {"completed": 1, "infra_error": 1}


def test_a_route_only_task_is_measured_only_under_routed():
    rows = _rows(
        [
            result("t", "m", "routed", first="trace"),
            result("t", "m", "off", first="trace"),
        ]
    )
    assert (rows[("t", "routed")]["pass_rate"], rows[("t", "routed")]["pass_basis"]) == (
        1.0,
        "route",
    )
    assert rows[("t", "off")]["pass_rate"] is None
    assert rows[("t", "off")]["pass_basis"] == "not measured"


# --------------------------------------------------------------------------- the call classifier


def test_a_call_is_classified_by_its_harness_names():
    from wikiskill import calls

    assert calls.target("Skill", {"skill": "dsh:plan"}, calls.CLAUDE_CODE) == ("skill", "dsh:plan")
    assert calls.target("task", {"subagentType": "x"}, calls.OPENCODE) == ("agent", "x")
    # Claude Code names an agent by `subagent_type` alone.
    assert calls.target("Agent", {"name": "x"}, calls.CLAUDE_CODE) is None
    assert calls.target("bash", {"agent": "x"}) is None
    assert calls.qualified("dsh:plan") == "dsh/plan"
    assert calls.delegation("Task", {"agent": "a", "prompt": "p"}) == {
        "agent": "a",
        "description": "",
        "prompt": "p",
    }
    assert calls.delegation("Skill", {"skill": "s"}) is None


# --------------------------------------------------------------------------- studies


def study_with(tmp_path, body, runs):
    root = tmp_path / "study"
    root.mkdir()
    entries = "".join(
        f'\n[[runs]]\nid = "{run_id}"\nrole = "{role}"\npath = "{path}"\n'
        + (f'label = "{label}"\n' if label else "")
        for run_id, role, path, label in runs
    )
    (root / "findings.toml").write_text('[study]\nname = "s"\n' + entries + body, "utf-8")
    return root


LEADERBOARD = '\n[[tables]]\nname = "sweep"\nkind = "leaderboard"\nroles = ["v1"]\n'
BOARD = (
    '\n[[tables]]\nname = "versions"\nkind = "version-board"\nroles = ["v1", "cand"]\n'
    f'component = "{COMPONENT}"\nbaseline = "v1"\n'
)


@pytest.fixture
def sources(tmp_path):
    base = tmp_path / "evals"
    v1 = write_versioned(
        base,
        "r1",
        V1,
        units("t", "ollama/a", "injected", 3, 1) + units("t", "ollama/a", "off", 1, 3),
    )
    v2 = write_versioned(base, "r2", V2, units("t", "ollama/a", "injected", 4, 0))
    (v1 / "units" / "u1").mkdir(parents=True)
    (v1 / "units" / "u1" / "transcript.json").write_text("{}", "utf-8")
    return v1, v2


@pytest.fixture
def study(tmp_path, sources):
    v1, v2 = sources
    root = study_with(
        tmp_path, LEADERBOARD + BOARD, [("r1", "v1", v1, "v1"), ("r2", "cand", v2, "p-001")]
    )
    findings.bundle(findings.load(root))
    return root


@pytest.mark.parametrize(
    ("body", "message"),
    [
        ('\n[[tables]]\nname = "x"\nkind = "pie"\nroles = ["v1"]\n', "`kind` must be one of"),
        ('\n[[tables]]\nname = "x"\nkind = "leaderboard"\nroles = ["routing"]\n', "'routing'"),
    ],
)
def test_a_malformed_study_is_refused_naming_the_entry(tmp_path, sources, body, message):
    root = study_with(tmp_path, body, [("r1", "v1", sources[0], None)])
    with pytest.raises(findings.FindingsError, match=message):
        findings.load(root)


def test_a_run_named_twice_is_refused(tmp_path, sources):
    root = study_with(
        tmp_path, "", [("r1", "v1", sources[0], None), ("r1", "v1", sources[0], None)]
    )
    with pytest.raises(findings.FindingsError, match="named twice"):
        findings.load(root)


def test_bundling_copies_two_files_keeps_bundled_runs_and_refuses_changed_ones(study, sources):
    assert sorted(p.name for p in (study / "runs" / "r1").iterdir()) == [
        "results.jsonl",
        "run.json",
    ]
    again = findings.bundle(findings.load(study))
    assert sorted(again.kept) == ["r1", "r2"] and not again.copied

    with (sources[0] / "results.jsonl").open("a", encoding="utf-8") as handle:
        handle.write("{}\n")
    before = (study / "runs" / "r1" / "results.jsonl").read_text()
    changed = findings.bundle(findings.load(study))
    assert changed.changed == ["r1"]
    assert (study / "runs" / "r1" / "results.jsonl").read_text() == before


def test_a_missing_run_is_reported_and_the_rest_bundled(tmp_path, sources):
    root = study_with(
        tmp_path, "", [("gone", "v1", tmp_path / "nope", None), ("r1", "v1", sources[0], None)]
    )
    result = findings.bundle(findings.load(root))
    assert result.missing == ["gone"] and result.copied == ["r1"]


def test_add_appends_a_run_and_refuses_a_duplicate(study):
    findings.add(study, "r3", "sweep", "v9")
    assert findings.load(study).runs[-1] == findings.StudyRun(id="r3", role="sweep", label="v9")
    with pytest.raises(findings.FindingsError, match="already in"):
        findings.add(study, "r3", "sweep")
    assert main(["findings", "add", str(study), "r3", "--role", "sweep"]) == 2


def test_tables_come_from_the_bundle_alone(study, xdg, sources):
    for source in sources:
        for name in ("run.json", "results.jsonl"):
            (source / name).unlink()
    rendered = findings.render(findings.load(study))

    assert "`p-001`" in rendered.files["tables/versions.slim.md"]
    overall = rendered.files["tables/versions.overall.slim.md"]
    assert "`v1`" in overall and "`p-001`" in overall
    assert rendered.files["tables/sweep.md"].startswith(findings.GENERATED)
    assert "### Ranking" in rendered.files["tables/sweep.md"], "headings sit under the document's"


def test_slim_tables_have_at_most_six_columns(study):
    rendered = findings.render(findings.load(study))
    for name, text in rendered.files.items():
        if name.endswith(".slim.md"):
            for line in text.splitlines():
                if line.startswith("|"):
                    assert line.count("|") - 1 <= findings.SLIM_COLUMNS, (name, line)


def test_every_slim_rate_is_a_csv_row(study):
    rendered = findings.render(findings.load(study))
    rows = list(csv.DictReader(rendered.files["findings.csv"].splitlines()))
    pooled = {
        (r["entrant"].split("/", 1)[-1], r["condition"]): r
        for r in rows
        if r["table"] == "sweep" and not r["task"]
    }
    for line in rendered.files["tables/sweep.slim.md"].splitlines()[4:]:
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        passed, total = re.match(r"(\d+)/(\d+)", cells[3]).groups()
        row = pooled[(cells[0], cells[2])]
        assert (row["passed"], row["total"]) == (passed, total)
        assert row["low"] and row["high"]
    assert any(r["table"] == "sweep" and r["task"] == "t" for r in rows)
    versions = [r for r in rows if r["table"] == "versions" and r["version"] == "p-001"]
    assert versions and versions[0]["lift"]


def test_check_finds_stale_files(study, tmp_path):
    loaded = findings.load(study)
    assert main(["findings", "tables", str(study), "--check"]) == 1, "nothing is written yet"
    findings.write(loaded, findings.render(loaded))
    assert main(["findings", "tables", str(study), "--check"]) == 0

    extra = write_versioned(tmp_path / "evals", "r3", V1, units("t", "ollama/b", "injected", 1, 0))
    findings.add(study, "r3", "v1", None)
    text = (
        (study / "findings.toml").read_text().replace('id = "r3"', f'id = "r3"\npath = "{extra}"')
    )
    (study / "findings.toml").write_text(text)
    findings.bundle(findings.load(study))
    assert findings.stale(findings.load(study), findings.render(findings.load(study)))
    assert main(["findings", "tables", str(study), "--check"]) == 1


def test_a_report_table_gives_each_judges_levels(tmp_path):
    from test_leaderboard import write_run

    opinions = [("gpt-oss:120b", "yes"), ("llama3.3", "no"), ("nemotron", "no")]
    run = write_run(tmp_path / "evals", "r1", [judged("ollama/m", opinions)])
    root = study_with(
        tmp_path,
        '\n[[tables]]\nname = "judges"\nkind = "report"\nroles = ["routing"]\n',
        [("r1", "routing", run, None)],
    )
    findings.bundle(findings.load(root))
    rendered = findings.render(findings.load(root))
    assert "llama3.3: no x1" in rendered.files["tables/judges.md"]
    assert "| handoff | m | routed | sufficient |" in rendered.files["tables/judges.slim.md"]


# --------------------------------------------------------------------------- documents


BUILD = Path(__file__).parent.parent / "bin" / "build-docs"


def build_docs(study, path_dir=None):
    env = {"PATH": str(path_dir)} if path_dir else None
    return subprocess.run(
        [sys.executable, str(BUILD), str(study)],
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )


def doc_study(tmp_path, include="tables/t.slim.md"):
    study = tmp_path / "doc"
    (study / "tables").mkdir(parents=True)
    (study / "tables" / "t.slim.md").write_text(
        findings.GENERATED + "\n\n| a | b |\n|---|---|\n| 1 | 2 |\n", "utf-8"
    )
    (study / "report.md").write_text(f"# R\n\n<!-- include: {include} -->\n", "utf-8")
    return study


def test_includes_are_expanded_without_the_generated_marker(tmp_path):
    import runpy

    module = runpy.run_path(str(BUILD))
    text = module["expand"](doc_study(tmp_path) / "report.md")
    assert "| 1 | 2 |" in text and "generated by" not in text and "include:" not in text


def test_no_pandoc_writes_nothing(tmp_path):
    study = doc_study(tmp_path)
    empty = tmp_path / "empty-bin"
    empty.mkdir()
    done = build_docs(study, empty)
    assert done.returncode == 1 and "pandoc" in done.stderr
    assert not list(study.glob("*.docx"))


@pytest.mark.skipif(shutil.which("pandoc") is None, reason="pandoc is not installed")
def test_a_missing_include_writes_nothing(tmp_path):
    study = doc_study(tmp_path, include="tables/nope.md")
    done = build_docs(study)
    assert done.returncode == 1 and "tables/nope.md" in done.stderr
    assert not list(study.glob("*.docx"))


@pytest.mark.skipif(shutil.which("pandoc") is None, reason="pandoc is not installed")
def test_the_report_builds_to_docx(tmp_path):
    study = doc_study(tmp_path)
    done = build_docs(study)
    assert done.returncode == 0, done.stderr
    assert (study / "report.docx").stat().st_size > 0
    assert (study / "build.txt").read_text().startswith("pandoc")


def test_an_include_keeps_the_blank_line_after_it(tmp_path):
    import runpy

    study = doc_study(tmp_path)
    (study / "report.md").write_text("<!-- include: tables/t.slim.md -->\n\n## Next\n", "utf-8")
    text = runpy.run_path(str(BUILD))["expand"](study / "report.md")
    assert "| 1 | 2 |\n\n## Next" in text


def test_csv_rows_carry_the_catalogues_family_size_and_shape(sources, tmp_path):
    v1, v2 = sources
    (tmp_path / "models.toml").write_text(
        '[models."a"]\nfamily = "qwen"\nsize_b = 30.5\nshape = "moe"\n', "utf-8"
    )
    root = study_with(
        tmp_path,
        LEADERBOARD + BOARD,
        [("r1", "v1", v1, "v1"), ("r2", "cand", v2, "p-001")],
    )
    text = (root / "findings.toml").read_text()
    (root / "findings.toml").write_text(
        text.replace('name = "s"\n', 'name = "s"\nmodels_file = "../models.toml"\n', 1)
    )
    findings.bundle(findings.load(root))

    rendered = findings.render(findings.load(root))
    rows = list(csv.DictReader(rendered.files["findings.csv"].splitlines()))

    assert rows, "the study renders rows"
    assert {(r["family"], r["size_b"], r["shape"]) for r in rows} == {("qwen", "30.5", "moe")}
