"""Refinement: one proposal, grounded in the wiki, written as a patch and never applied."""

from __future__ import annotations

import json
import subprocess

import pytest

from conftest import write_manifest
from wikiskill import collection as collection_mod
from wikiskill import paths, refine, wiki
from wikiskill.cli import main

DOER = "datalad/datalad-doer"
TEXT = (
    "---\nname: datalad-doer\ndescription: d\n---\n\n# Doer\n\n"
    "## Constraints\n- Never use an empty/placeholder `-m` message.\n- Report the branch.\n"
)


def git(root, *args):
    return subprocess.run(
        ["git", "-C", str(root), *args], capture_output=True, text=True, check=True
    ).stdout


@pytest.fixture
def repo_collection(xdg, plugin_source):
    """The doer in a committed git repository, as the real source is, with one wiki pattern."""
    doer = plugin_source / "datalad" / "agents" / "datalad-doer.md"
    doer.write_text(TEXT, encoding="utf-8")
    git(plugin_source, "init", "--quiet")
    git(plugin_source, "add", "--all")
    git(plugin_source, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "--quiet", "-m", "x")
    write_manifest(
        xdg,
        "dsh",
        f'name = "dsh"\nsources = [{{ path = "{plugin_source}", layout = "claude-plugin", '
        'plugins = ["datalad"] }]\n[watch]\nagents = ["datalad/datalad-doer"]\n',
    )
    evidence = {
        "E1": wiki.Evidence(
            id="E1",
            component=DOER,
            model="opencode/big-pickle",
            harness="opencode",
            source_hash="h1",
            ref={"run_id": "R", "task_id": "t", "condition": "injected", "repeat": 0},
        )
    }
    wiki.apply(
        "dsh",
        {
            "create": [
                {
                    "slug": "invents-commit-message",
                    "title": "Invents a message",
                    "trigger": "save with no -m",
                    "cause": "instruction_ignored",
                    "evidence": ["E1"],
                    "observation": "Guessed a message.",
                }
            ],
            "update": [],
            "index": {"invents-commit-message": "Guesses -m"},
            "log": "x",
        },
        component=DOER,
        evidence=evidence,
        maintainer="m",
    )
    return collection_mod.load("dsh"), doer, plugin_source


PATCH = {
    "action": "patch",
    "reason": "Make the rule say what to do instead.",
    "patterns": ["invents-commit-message"],
    "edits": [
        {
            "find": "- Never use an empty/placeholder `-m` message.",
            "replace": "- Never use an empty/placeholder `-m` message. If none was given, stop and "
            "ask for one.",
        }
    ],
}


def replies(*answers):
    queue = iter(answers)
    return lambda _messages: next(queue)


def test_a_patch_is_written_checked_and_never_applied(repo_collection):
    coll, doer, source = repo_collection
    before = doer.read_bytes()

    proposal = refine.refine(coll, DOER, ask=replies(json.dumps(PATCH)), proposer="fake")

    assert proposal.action == "patch"
    assert proposal.directory.name == "p-001"
    assert doer.read_bytes() == before, "wikiskill never applies a proposal"
    assert git(source, "status", "--porcelain") == ""
    diff = (proposal.directory / "patch.diff").read_text()
    assert "a/datalad/agents/datalad-doer.md" in diff
    assert "+- Never use an empty/placeholder `-m` message. If none was given" in diff
    subprocess.run(
        ["git", "-C", str(source), "apply", "--check", str(proposal.directory / "patch.diff")],
        check=True,
    )
    meta = json.loads((proposal.directory / "meta.json").read_text())
    assert meta["patterns"] == ["invents-commit-message"]
    assert meta["source_hash"] and meta["status"] == "proposed"
    assert "Nothing has been applied" in (proposal.directory / "preview.md").read_text()
    assert git(paths.wiki_dir("dsh"), "log", "-1", "--format=%s").startswith("propose p-001")


def test_an_edit_that_does_not_match_goes_back_then_fails(repo_collection):
    coll, _, _ = repo_collection
    wrong = {**PATCH, "edits": [{"find": "Never guess", "replace": "Always guess"}]}
    seen = []

    def ask(messages):
        seen.append(messages)
        return json.dumps(wrong)

    proposal = refine.refine(coll, DOER, ask=ask, proposer="fake", retries=1)

    assert proposal.action == "failed"
    assert "`find` does not occur" in seen[1][-1]["content"]
    assert not (paths.wiki_dir("dsh") / "proposals").exists()


@pytest.mark.parametrize(
    "reply, expected",
    [
        ({**PATCH, "patterns": []}, "must cite at least one wiki pattern"),
        ({**PATCH, "patterns": ["made-up"]}, "made-up are not patterns of this component"),
        ({**PATCH, "edits": []}, "needs at least one edit"),
        ({"action": "rewrite", "reason": "x", "patterns": []}, "action"),
    ],
)
def test_a_reply_that_is_not_a_proposal_says_why(reply, expected):
    problems = refine.validate(reply, text=TEXT, known_patterns=["invents-commit-message"])
    assert any(expected in p for p in problems), problems


def test_no_action_writes_nothing(repo_collection):
    coll, _, _ = repo_collection
    reply = {"action": "no_action", "reason": "The text is right already.", "patterns": []}
    proposal = refine.refine(coll, DOER, ask=replies(json.dumps(reply)), proposer="fake")
    assert proposal.action == "no_action"
    assert not (paths.wiki_dir("dsh") / "proposals").exists()


def test_without_patterns_nothing_is_asked(xdg, plugin_source):
    write_manifest(
        xdg,
        "dsh",
        f'name = "dsh"\nsources = [{{ path = "{plugin_source}", layout = "claude-plugin" }}]\n'
        '[watch]\nagents = ["datalad/datalad-doer"]\n',
    )

    def never(_messages):
        raise AssertionError("the proposer must not be called without patterns")

    proposal = refine.refine(collection_mod.load("dsh"), DOER, ask=never, proposer="fake")
    assert proposal.action == "no_action"
    assert "run `wikiskill review` first" in proposal.reason


def test_proposal_ids_count_up(repo_collection):
    coll, _, _ = repo_collection
    first = refine.refine(coll, DOER, ask=replies(json.dumps(PATCH)), proposer="fake")
    second = refine.refine(coll, DOER, ask=replies(json.dumps(PATCH)), proposer="fake")
    assert (first.directory.name, second.directory.name) == ("p-001", "p-002")


def test_cli_refine_from_a_reply_file(repo_collection, tmp_path, capsys):
    reply = tmp_path / "reply.json"
    reply.write_text(json.dumps(PATCH))
    assert main(["refine", DOER, "--collection", "dsh", "--reply-file", str(reply)]) == 0
    out = capsys.readouterr().out
    assert "nothing has been applied" in out
    assert "preview.md" in out
