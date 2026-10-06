"""`wikiskill diff`: version references, text recovery, run choice, the report, and snapshots."""

from __future__ import annotations

import json
import os
import shutil
import stat

import pytest

import test_gate
import test_refine
from conftest import write_manifest
from test_refine import DOER, TEXT, git, replies
from test_run import MANIFEST, SUITE, FakeBackend
from wikiskill import collection as collection_mod
from wikiskill import compare, gate, paths, rawlog, refine, sources
from wikiskill import diff as diff_mod
from wikiskill import suite as suite_mod
from wikiskill.cli import main
from wikiskill.runner import run as run_mod
from wikiskill.runner.base import OFF, RunLayout

#: Shared with the refine and gate tests.
repo_collection = test_refine.repo_collection
evaluated = test_refine.evaluated
proposed = test_gate.proposed

CHANGED = TEXT.replace("- Report the branch.\n", "- Report the branch and the commit.\n")


def h(text: str) -> str:
    return rawlog.content_hash(text.encode())


def write_run(coll, run_id, source_hash, *, suite="doer-suite", tasks=("t",), proposal=None):
    """A finished run of the doer, one passing unit per task under OFF."""
    directory = paths.evals_dir(coll.name) / run_id
    directory.mkdir(parents=True)
    (directory / "run.json").write_text(
        json.dumps(
            {
                "run_id": run_id,
                "suite": suite,
                "suite_hash": f"sha256:{suite}",
                "collection": coll.name,
                "tasks": list(tasks),
                "components": [{"kind": "agent", "name": DOER, "source_hash": source_hash}],
                "proposal": proposal,
            }
        )
    )
    rows = [
        {
            "run_id": run_id,
            "task_id": task,
            "model": "ollama/m",
            "condition": "off",
            "repeat": 0,
            "outcome": "completed",
            "passed": True,
        }
        for task in tasks
    ]
    (directory / "results.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    return directory


def stored(collection):
    """The hashes of every snapshot of a collection."""
    directory = paths.sources_dir(collection)
    found = directory.glob("sha256-*") if directory.is_dir() else []
    return {"sha256:" + path.name.removeprefix("sha256-") for path in found}


def clear_snapshots(coll):
    shutil.rmtree(paths.sources_dir(coll.name), ignore_errors=True)


# --------------------------------------------------------------------------- 1. references


def test_every_reference_form_resolves(proposed):
    coll, doer, _ = proposed
    meta = gate.load(coll.name, "p-001")
    current = rawlog.file_hash(doer)
    write_run(coll, "01RUNA", current)
    assert diff_mod.resolve(coll, DOER, "current") == current
    assert diff_mod.resolve(coll, DOER, "p-001") == meta["candidate_hash"]
    assert diff_mod.resolve(coll, DOER, "p-001^") == meta["source_hash"]
    assert diff_mod.resolve(coll, DOER, "run:01RUNA") == current
    candidate = meta["candidate_hash"]
    assert diff_mod.resolve(coll, DOER, candidate[7:14]) == candidate
    assert diff_mod.resolve(coll, DOER, candidate[:20]) == candidate


@pytest.mark.parametrize(
    "ref, expected",
    [
        ("abcdef0", "matches no known version"),
        ("abc", "is not a version"),
        ("p-009", "no proposal 'p-009'"),
        ("run:01NONE", "no run at"),
        ("v2", "is not a version"),
    ],
)
def test_a_bad_reference_names_itself(proposed, ref, expected):
    coll, _, _ = proposed
    with pytest.raises(diff_mod.DiffError, match=expected):
        diff_mod.resolve(coll, DOER, ref)


def test_an_ambiguous_prefix_lists_every_match(proposed):
    coll, _, _ = proposed
    one, two = "sha256:abcdef1" + "0" * 57, "sha256:abcdef1" + "1" * 57
    write_run(coll, "01RUNA", one)
    write_run(coll, "01RUNB", two)
    with pytest.raises(diff_mod.DiffError) as raised:
        diff_mod.resolve(coll, DOER, "abcdef1")
    assert one in str(raised.value) and two in str(raised.value)


def test_a_proposal_for_another_component_is_refused(proposed):
    coll, _, _ = proposed
    meta = gate.load(coll.name, "p-001")
    meta["component"] = "govern/preregister"
    (gate.directory(coll.name, "p-001") / "meta.json").write_text(json.dumps(meta))
    with pytest.raises(diff_mod.DiffError, match="a proposal for govern/preregister"):
        diff_mod.resolve(coll, DOER, "p-001")


def test_an_unknown_component_is_named(proposed):
    coll, _, _ = proposed
    with pytest.raises(diff_mod.DiffError, match="'nope' is not a component"):
        diff_mod.resolve(coll, "nope", "current")


def test_a_candidate_run_records_the_proposals_candidate_hash(proposed, tmp_path):
    coll, _, _ = proposed
    candidate = gate.candidate_collection(coll, "p-001", tmp_path / "cand")
    recorded = {c["name"]: c["source_hash"] for c in run_mod._component_versions(candidate)}
    assert recorded[DOER] == gate.load(coll.name, "p-001")["candidate_hash"]


# --------------------------------------------------------------------------- 2. text


def test_text_is_found_in_a_snapshot(repo_collection):
    coll, _, _ = repo_collection
    sources.store(coll.name, CHANGED.encode())
    found = diff_mod.recover(coll, DOER, h(CHANGED))
    assert found.text == CHANGED.encode() and found.found_in == "source snapshot"


def test_text_is_found_in_the_current_file(repo_collection):
    coll, doer, _ = repo_collection
    found = diff_mod.recover(coll, DOER, rawlog.file_hash(doer))
    assert found.found_in.startswith("the current file")


def test_text_is_found_in_a_proposals_rendered_copy(proposed):
    coll, _, _ = proposed
    clear_snapshots(coll)
    found = diff_mod.recover(coll, DOER, gate.load(coll.name, "p-001")["candidate_hash"])
    assert found.found_in == "p-001's rendered copy"


def test_text_is_found_in_a_candidate_copy_and_a_mismatch_is_skipped(proposed, tmp_path):
    coll, doer, source = proposed
    clear_snapshots(coll)
    wanted = gate.load(coll.name, "p-001")["candidate_hash"]
    copy = paths.evals_dir(coll.name) / "01CAND" / "candidate-source"
    gate.candidate_collection(coll, "p-001", copy.parent)
    rendered = gate.directory(coll.name, "p-001") / "rendered" / doer.name
    rendered.write_text("tampered\n", encoding="utf-8")
    found = diff_mod.recover(coll, DOER, wanted)
    assert found.found_in == "run 01CAND's candidate source"
    assert (copy / doer.relative_to(source)).is_file()


def commit(root, path, text, message):
    path.write_text(text, encoding="utf-8")
    git(root, "add", "--all")
    git(root, "commit", "--quiet", "-m", message)


def test_a_version_only_in_git_history_is_recovered_read_only(repo_collection):
    coll, doer, source = repo_collection
    middle = TEXT + "\nMiddle.\n"
    commit(source, doer, middle, "middle")
    commit(source, doer, TEXT + "\nLatest.\n", "latest")
    head, status = git(source, "rev-parse", "HEAD"), git(source, "status", "--porcelain")
    found = diff_mod.recover(coll, DOER, h(middle))
    assert found.text == middle.encode()
    assert found.found_in.startswith("git ")
    assert git(source, "rev-parse", "HEAD") == head
    assert git(source, "status", "--porcelain") == status


def test_git_history_follows_a_rename(tmp_path):
    repo = tmp_path / "r"
    repo.mkdir()
    git(repo, "init", "--quiet")
    first = "".join(f"line {i}\n" for i in range(20))
    commit(repo, repo / "old.md", first, "one")
    git(repo, "mv", "old.md", "new.md")
    # Renamed and edited at once, so the first text exists only under the old name.
    commit(repo, repo / "new.md", first + "more\n", "rename")
    data, where = diff_mod.GitHistory(repo / "new.md").find(h(first))
    assert data == first.encode() and where.endswith(":old.md")


def test_the_git_limit_is_reported(repo_collection, monkeypatch):
    coll, doer, source = repo_collection
    commit(source, doer, TEXT + "\nTwo.\n", "two")
    commit(source, doer, TEXT + "\nThree.\n", "three")
    monkeypatch.setattr(diff_mod, "GIT_LIMIT", 2)
    found = diff_mod.recover(coll, DOER, h(TEXT))
    assert found.text is None
    assert "limit of 2 revisions" in (found.note or "")


def test_the_text_section_body_only(proposed):
    coll, _, _ = proposed
    text = diff_mod.text_diff(
        coll, DOER, *(diff_mod.resolve(coll, DOER, r) for r in ("p-001^", "p-001"))
    )
    assert text.diff and "+- Never use an empty/placeholder `-m` message. If none" in text.diff
    assert text.description_changed is False


def test_the_text_section_flags_a_description_change(repo_collection):
    coll, doer, _ = repo_collection
    moved = TEXT.replace("description: d", "description: saves datasets")
    sources.store(coll.name, moved.encode())
    found = diff_mod.text_diff(coll, DOER, rawlog.file_hash(doer), h(moved))
    assert found.description_changed is True


def test_the_text_section_identical_and_unavailable(repo_collection):
    coll, doer, _ = repo_collection
    current = rawlog.file_hash(doer)
    assert diff_mod.text_diff(coll, DOER, current, current).identical
    lost = "sha256:" + "0" * 64
    found = diff_mod.text_diff(coll, DOER, lost, current)
    assert found.a.text is None and found.diff is None
    assert "source snapshots" in found.a.searched
    assert any("git history" in place for place in found.a.searched)


# --------------------------------------------------------------------------- 3. results


def test_the_newest_shared_suite_wins(repo_collection):
    coll, _, _ = repo_collection
    a, b = "sha256:" + "a" * 64, "sha256:" + "b" * 64
    write_run(coll, "01R1", a, suite="s1")
    write_run(coll, "01R2", b, suite="s1")
    write_run(coll, "01R3", a, suite="s2")
    write_run(coll, "01R4", a, suite="s1")
    picked = diff_mod.pick_runs(coll, DOER, a, b)
    assert not isinstance(picked, diff_mod.Unavailable)
    assert [run.run_id for run in picked] == ["01R4", "01R2"]


def test_no_run_for_one_version_lists_the_others(proposed):
    coll, doer, _ = proposed
    write_run(coll, "01R1", rawlog.file_hash(doer))
    results = diff_mod.results_diff(
        coll, DOER, rawlog.file_hash(doer), gate.load(coll.name, "p-001")["candidate_hash"]
    )
    assert results.unavailable is not None
    assert results.unavailable.reason.startswith("version B has no finished runs")
    assert "--proposal p-001" in results.unavailable.reason
    # 01RUN is the fixture's own run of the current version.
    assert results.unavailable.runs_a == ["01R1 (suite doer-suite)", "01RUN (suite doer-suite)"]


def test_a_candidate_run_counts_for_its_version(proposed):
    coll, doer, _ = proposed
    candidate = gate.load(coll.name, "p-001")["candidate_hash"]
    write_run(coll, "01R1", rawlog.file_hash(doer))
    write_run(coll, "01R2", candidate, proposal="p-001")
    picked = diff_mod.pick_runs(coll, DOER, rawlog.file_hash(doer), candidate)
    assert [run.run_id for run in picked] == ["01R1", "01R2"]


def test_an_explicit_run_of_another_version_is_refused(repo_collection):
    coll, _, _ = repo_collection
    a, b = "sha256:" + "a" * 64, "sha256:" + "b" * 64
    write_run(coll, "01R1", a)
    write_run(coll, "01R2", b)
    with pytest.raises(diff_mod.DiffError, match=f"recorded {DOER} at {b}"):
        diff_mod.results_diff(coll, DOER, a, b, run_a="01R2")


def test_an_explicit_incompatible_pair_is_refused(repo_collection):
    coll, _, _ = repo_collection
    a, b = "sha256:" + "a" * 64, "sha256:" + "b" * 64
    write_run(coll, "01R1", a, suite="s1")
    write_run(coll, "01R2", b, suite="s2")
    with pytest.raises(diff_mod.DiffError, match="cannot be compared"):
        diff_mod.results_diff(coll, DOER, a, b, run_a="01R1", run_b="01R2")


def test_the_comparison_is_compares_own(repo_collection):
    coll, _, _ = repo_collection
    a, b = "sha256:" + "a" * 64, "sha256:" + "b" * 64
    write_run(coll, "01R1", a, tasks=("t", "u"))
    write_run(coll, "01R2", b, tasks=("t", "u"))
    results = diff_mod.results_diff(coll, DOER, a, b)
    direct = compare.compare(
        compare.load_run(coll.name, "01R1"), compare.load_run(coll.name, "01R2"), component=DOER
    )
    assert results.comparison is not None
    assert results.comparison.as_dict() == direct.as_dict()


# --------------------------------------------------------------------------- 4. report


def test_the_report_headings_files_and_keys(proposed):
    coll, doer, source = proposed
    candidate = gate.load(coll.name, "p-001")["candidate_hash"]
    write_run(coll, "01R1", rawlog.file_hash(doer))
    write_run(coll, "01R2", candidate, proposal="p-001")
    status = git(source, "status", "--porcelain")
    found = diff_mod.diff(coll, DOER, "p-001^", "p-001")
    markdown = diff_mod.render(found)
    headings = [line for line in markdown.splitlines() if line.startswith("#")]
    assert headings[:3] == [f"# Diff: {DOER}", "## Text", "## Results"]
    assert "### Compare: doer-suite" in headings and "#### off" in headings

    written = diff_mod.write(found)
    out = paths.evals_dir(coll.name) / "diff" / "datalad-datalad-doer"
    out = out / f"{diff_mod.short(found.hash_a)}_vs_{diff_mod.short(candidate)}"
    assert written == [out / "diff.md", out / "diff.json", out / "text.diff"]
    assert all(path.is_relative_to(paths.collection_data(coll.name)) for path in written)
    assert git(source, "status", "--porcelain") == status
    data = json.loads((out / "diff.json").read_text())
    assert sorted(data) == ["a", "b", "collection", "component", "results", "text"]
    assert data["a"]["ref"] == "p-001^" and data["b"]["source_hash"] == candidate
    assert data["results"]["run_a"] == "01R1"
    assert data["results"]["comparison"]["b"]["run_id"] == "01R2"
    assert data["text"]["b"]["found_in"] == "source snapshot"


def test_no_text_diff_file_when_a_text_is_unavailable(repo_collection):
    coll, _, _ = repo_collection
    lost = "sha256:" + "0" * 64
    write_run(coll, "01R1", lost)
    found = diff_mod.diff(coll, DOER, "0000000", "current")
    written = diff_mod.write(found)
    assert [path.name for path in written] == ["diff.md", "diff.json"]
    markdown = diff_mod.render(found)
    assert "Version A's text is unavailable" in markdown
    assert "Unavailable: version B has no finished runs" in markdown


@pytest.mark.parametrize("versions", [["p-001^", "p-001"], ["run:01RUN", "current"]])
def test_cli_diff(proposed, capsys, versions):
    """The README's examples, on the fixture collection."""
    coll, _, _ = proposed
    assert main(["diff", DOER, *versions, "--collection", coll.name]) == 0
    out = capsys.readouterr().out
    assert f"# Diff: {DOER}" in out and "wrote " in out


@pytest.mark.parametrize(
    "argv, expected",
    [
        (["diff", "nope", "current", "current"], "'nope' is not a component"),
        (["diff", DOER, "current", "zz"], "'zz' is not a version"),
        (["diff", DOER, "current"], "diff needs two versions"),
        (["diff", DOER, "current", "current", "--list"], "--list takes no versions"),
    ],
)
def test_cli_diff_misuse(proposed, capsys, argv, expected):
    coll, _, _ = proposed
    assert main([*argv, "--collection", coll.name]) == 2
    assert expected in capsys.readouterr().err


# --------------------------------------------------------------------------- 5. snapshots


def test_a_snapshot_is_written_once_under_its_hash(xdg):
    key = sources.store("c", b"one\n")
    target = sources.path_for("c", key)
    assert key == rawlog.content_hash(b"one\n") and target.name == key.replace(":", "-")
    before = target.stat().st_mtime_ns
    os.utime(target, ns=(before - 10**9, before - 10**9))
    assert sources.store("c", b"one\n") == key
    assert target.stat().st_mtime_ns == before - 10**9
    assert sources.read("c", key) == b"one\n"
    assert stored("c") == {key}


def test_an_unwritable_store_raises_a_reportable_error(xdg):
    directory = paths.sources_dir("c")
    directory.mkdir(parents=True)
    directory.chmod(stat.S_IRUSR | stat.S_IXUSR)
    try:
        with pytest.raises(sources.SnapshotError, match=str(directory)):
            sources.store("c", b"two\n")
    finally:
        directory.chmod(stat.S_IRWXU)


@pytest.fixture
def toy(xdg, opencode_source, tmp_path):
    write_manifest(xdg, "toy", MANIFEST.format(source=opencode_source))
    path = tmp_path / "suite.yaml"
    path.write_text(SUITE, encoding="utf-8")
    return collection_mod.load("toy"), suite_mod.load(path), tmp_path


def run_toy(coll, suite, tmp_path, run_id="01JRUN"):
    layout = RunLayout.create(coll.name, run_id, base=tmp_path / "evals")
    lines = []
    run = run_mod.run_suite(
        suite,
        FakeBackend(layout),
        collection=coll,
        models=["fake/model"],
        conditions=[OFF],
        layout=layout,
        run_id=run_id,
        on_event=lines.append,
    )
    return run, run_mod.load_manifest(layout), lines


def test_a_run_keeps_a_snapshot_per_watched_component(toy):
    coll, suite, tmp_path = toy
    _, manifest, _ = run_toy(coll, suite, tmp_path)
    recorded = {c["source_hash"] for c in manifest["components"]}
    assert recorded and recorded == stored(coll.name)
    assert manifest["warnings"] == []


def test_a_read_only_store_still_completes_the_run(toy):
    coll, suite, tmp_path = toy
    directory = paths.sources_dir(coll.name)
    directory.mkdir(parents=True)
    directory.chmod(stat.S_IRUSR | stat.S_IXUSR)
    try:
        run, manifest, lines = run_toy(coll, suite, tmp_path)
    finally:
        directory.chmod(stat.S_IRWXU)
    assert run.results and manifest["components"]
    assert len(manifest["warnings"]) == 1 and str(directory) in manifest["warnings"][0]
    assert any(line.startswith("warning: ") for line in lines)


def test_a_proposal_keeps_both_versions(proposed):
    coll, _, _ = proposed
    meta = gate.load(coll.name, "p-001")
    assert {meta["source_hash"], meta["candidate_hash"]} <= stored(coll.name)


def test_no_action_keeps_no_snapshot(repo_collection):
    coll, _, _ = repo_collection
    reply = {"action": "no_action", "component": DOER, "reason": "Fine.", "patterns": []}
    refine.refine(coll, DOER, ask=replies(json.dumps(reply)), proposer="fake")
    assert stored(coll.name) == set()


# --------------------------------------------------------------------------- 6. listing


def test_versions_lists_a_refined_component(proposed):
    coll, doer, _ = proposed
    first = gate.load(coll.name, "p-001")
    write_run(coll, "01R1", first["source_hash"])
    write_run(coll, "01R2", first["candidate_hash"], proposal="p-001")
    # A second proposal, made from the first's candidate once it was applied.
    doer.write_bytes(sources.read(coll.name, first["candidate_hash"]) or b"")
    second = refine.refine(
        coll,
        DOER,
        ask=replies(
            json.dumps(
                {
                    **test_gate.GOOD,
                    "edits": [
                        {
                            "find": "- Report the branch.",
                            "replace": "- Report the branch. Then stop.",
                        }
                    ],
                }
            )
        ),
        proposer="fake",
    )
    assert second.directory is not None and second.directory.name == "p-002"
    found = diff_mod.versions(coll, DOER)
    by_hash = {v.source_hash: v for v in found}
    third = gate.load(coll.name, "p-002")["candidate_hash"]
    assert [v.source_hash for v in found] == [first["source_hash"], first["candidate_hash"], third]
    assert by_hash[first["source_hash"]].base_of == ["p-001"]
    assert by_hash[first["source_hash"]].runs == ["01R1", "01RUN"]
    middle = by_hash[first["candidate_hash"]]
    assert (middle.produced_by, middle.base_of, middle.current) == (["p-001"], ["p-002"], True)
    assert by_hash[third].produced_by == ["p-002"] and not by_hash[third].runs


def test_cli_list(proposed, capsys):
    coll, doer, _ = proposed
    write_run(coll, "01R1", rawlog.file_hash(doer))
    assert main(["diff", DOER, "--list", "--collection", coll.name]) == 0
    out = capsys.readouterr().out
    assert "| version | first seen | text | proposals | runs | current |" in out
    assert "base of p-001" in out and "candidate of p-001" in out
    current = next(line for line in out.splitlines() if "base of p-001" in line)
    assert current.endswith("| 2 | yes |")


def test_raw_log_activations_count(proposed):
    coll, _, _ = proposed
    raw = paths.raw_dir(coll.name) / "2026-10-01"
    raw.mkdir(parents=True)
    other = "sha256:" + "c" * 64
    event = {
        "type": "component_activated",
        "ts": "2026-10-01T00:00:00.000Z",
        "component": {"kind": "agent", "name": "datalad-doer", "source_hash": other},
    }
    (raw / "s.jsonl").write_text(json.dumps(event) + "\n" + json.dumps({"type": "x"}) + "\n")
    found = {v.source_hash: v for v in diff_mod.versions(coll, DOER)}
    assert found[other].activations == 1
    assert diff_mod.resolve(coll, DOER, "ccccccc") == other


# --------------------------------------------------------------------------- review fixes


def test_a_snapshot_failure_never_stops_a_proposal(repo_collection):
    """The base is the proposal's own text; an unreadable file is a warning, not an exception."""
    coll, doer, _ = repo_collection
    found = refine.context(coll, DOER)
    rendered = doer.parent / "rendered.md"
    rendered.write_text(CHANGED, encoding="utf-8")
    doer.unlink()
    assert refine._snapshot(coll.name, found, rendered) == []
    assert {h(TEXT), h(CHANGED)} <= stored(coll.name)
    found.text = "edited since\n"
    warnings = refine._snapshot(coll.name, found, doer.parent / "gone.md")
    assert len(warnings) == 1 and "its base was not kept" in warnings[0]


def test_a_prefix_of_another_components_snapshot_is_not_a_version(repo_collection):
    coll, _, _ = repo_collection
    other = sources.store(coll.name, b"another component's text\n")
    with pytest.raises(diff_mod.DiffError, match="matches no known version"):
        diff_mod.resolve(coll, DOER, other[7:14])


def test_git_history_reads_a_non_ascii_path(tmp_path):
    repo = tmp_path / "r"
    (repo / "café").mkdir(parents=True)
    git(repo, "init", "--quiet")
    commit(repo, repo / "café" / "SKILL.md", "first\n", "one")
    commit(repo, repo / "café" / "SKILL.md", "second\n", "two")
    data, where = diff_mod.GitHistory(repo / "café" / "SKILL.md").find(h("first\n"))
    assert data == b"first\n" and where.endswith(":café/SKILL.md")


def test_a_damaged_snapshot_is_replaced_with_the_usual_mode(xdg):
    key = sources.store("c", b"whole\n")
    target = sources.path_for("c", key)
    target.write_bytes(b"who")
    assert sources.read("c", key) is None
    sources.store("c", b"whole\n")
    assert sources.read("c", key) == b"whole\n"
    umask = os.umask(0)
    os.umask(umask)
    assert stat.S_IMODE(target.stat().st_mode) == 0o666 & ~umask


def test_a_given_run_is_never_paired_with_itself(repo_collection):
    coll, _, _ = repo_collection
    a = "sha256:" + "a" * 64
    write_run(coll, "01R1", a)
    write_run(coll, "01R2", a)
    write_run(coll, "01R3", a)
    results = diff_mod.results_diff(coll, DOER, a, a, run_a="01R3")
    assert results.comparison is not None
    assert (results.comparison.a.run_id, results.comparison.b.run_id) == ("01R3", "01R2")
    alone = diff_mod.results_diff(coll, DOER, a, a, run_b="01R1", loaded=[])
    assert alone.unavailable is not None and "no other finished run" in alone.unavailable.reason


def test_a_symlinked_source_still_diffs(tmp_path):
    real = tmp_path / "real"
    real.mkdir()
    git(real, "init", "--quiet")
    commit(real, real / "a.md", "one\n", "one")
    link = tmp_path / "link"
    link.symlink_to(real)
    assert diff_mod._relative(link / "a.md", real) == diff_mod._relative(real / "a.md", real)
    assert refine.make_diff(link / "a.md", "one\n", "two\n").startswith("--- a/a.md\n")
    assert diff_mod.GitHistory(link / "a.md").find(h("one\n"))[0] == b"one\n"


def test_list_reads_the_git_history_once(repo_collection, monkeypatch, capsys):
    coll, doer, source = repo_collection
    for i in range(3):
        old = TEXT + f"\nVersion {i}.\n"
        commit(source, doer, old, f"v{i}")
        write_run(coll, f"01R{i}", h(old))
    commit(source, doer, TEXT, "back")
    calls = []
    real = diff_mod._git
    monkeypatch.setattr(
        diff_mod, "_git", lambda repo, *args: calls.append(args[0]) or real(repo, *args)
    )
    assert main(["diff", DOER, "--list", "--collection", coll.name]) == 0
    assert calls.count("log") == 1
    assert calls.count("show") <= 5
    assert capsys.readouterr().out.count("| yes |") >= 3


# --------------------------------------------------------------------------- second review


class EditingBackend(FakeBackend):
    """Edits a component's file while a unit runs, as a user might during a long eval."""

    def __init__(self, layout, path):
        super().__init__(layout)
        self.path = path

    def execute(self, unit):
        self.path.write_text("---\nname: smoke\ndescription: edited mid-run\n---\n", "utf-8")
        return super().execute(unit)


def test_a_run_records_the_text_that_ran_not_the_text_at_the_end(toy, opencode_source):
    coll, suite, tmp_path = toy
    skill = opencode_source / "skills" / "smoke" / "SKILL.md"
    before = skill.read_bytes()
    layout = RunLayout.create(coll.name, "01JRUN", base=tmp_path / "evals")
    run_mod.run_suite(
        suite,
        EditingBackend(layout, skill),
        collection=coll,
        models=["fake/model"],
        conditions=[OFF],
        layout=layout,
        run_id="01JRUN",
    )
    recorded = {c["name"]: c["source_hash"] for c in run_mod.load_manifest(layout)["components"]}
    assert recorded["smoke"] == rawlog.content_hash(before)
    assert sources.read(coll.name, recorded["smoke"]) == before


def test_a_bare_activation_shared_by_two_plugins_is_not_guessed(xdg, plugin_source):
    other = plugin_source / "analyze" / "skills" / "preregister"
    other.mkdir(parents=True)
    (other / "SKILL.md").write_text("---\nname: preregister\ndescription: x\n---\n", "utf-8")
    write_manifest(
        xdg,
        "two",
        f'name = "two"\nsources = [{{ path = "{plugin_source}", layout = "claude-plugin" }}]\n'
        '[watch]\nskills = ["*"]\n',
    )
    coll = collection_mod.load("two")
    raw = paths.raw_dir("two") / "2026-10-01"
    raw.mkdir(parents=True)
    events = [
        ("preregister", "skill", "a"),
        ("govern/preregister", "skill", "b"),
        ("govern/preregister", "command", "d"),
    ]
    (raw / "s.jsonl").write_text(
        "".join(
            json.dumps(
                {
                    "type": "component_activated",
                    "ts": "2026-10-01T00:00:00.000Z",
                    "component": {"kind": kind, "name": name, "source_hash": "sha256:" + c * 64},
                }
            )
            + "\n"
            for name, kind, c in events
        )
    )
    found = {v.source_hash for v in diff_mod.versions(coll, "govern/preregister")}
    assert "sha256:" + "b" * 64 in found
    assert "sha256:" + "a" * 64 not in found and "sha256:" + "d" * 64 not in found


def test_a_given_b_is_paired_with_an_older_a(repo_collection):
    coll, _, _ = repo_collection
    a = "sha256:" + "a" * 64
    for run_id in ("01R1", "01R2", "01R3"):
        write_run(coll, run_id, a)
    results = diff_mod.results_diff(coll, DOER, a, a, run_b="01R2")
    assert results.comparison is not None
    assert (results.comparison.a.run_id, results.comparison.b.run_id) == ("01R1", "01R2")


def test_a_vanished_file_has_no_time_rather_than_an_error(tmp_path):
    assert diff_mod._mtime(tmp_path / "gone") == ""


def test_list_reads_the_proposals_and_components_once(proposed, monkeypatch, capsys):
    coll, _, _ = proposed
    for i in range(3):
        write_run(coll, f"01R{i}", "sha256:" + str(i) * 64)
    calls = {"proposals": 0, "discover": 0}
    real_proposals, real_discover = diff_mod._proposals, type(coll).discover

    def proposals(*args):
        calls["proposals"] += 1
        return real_proposals(*args)

    def discover(self):
        calls["discover"] += 1
        return real_discover(self)

    monkeypatch.setattr(diff_mod, "_proposals", proposals)
    monkeypatch.setattr(type(coll), "discover", discover)
    assert main(["diff", DOER, "--list", "--collection", coll.name]) == 0
    assert capsys.readouterr().out.count("\n| `") >= 5
    assert calls["proposals"] == 2
    assert calls["discover"] <= 4


def test_a_prefix_found_in_runs_never_reads_the_raw_log(repo_collection, monkeypatch):
    coll, _, _ = repo_collection
    wanted = "sha256:" + "e" * 64
    write_run(coll, "01R1", wanted)

    def no_raw(*_args):
        raise AssertionError("the raw log was read")

    monkeypatch.setattr(diff_mod, "_activations", no_raw)
    assert diff_mod.resolve(coll, DOER, "eeeeeee") == wanted
