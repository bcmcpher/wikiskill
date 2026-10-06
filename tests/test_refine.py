"""Refinement: one proposal, grounded in the wiki, written as a patch and never applied."""

from __future__ import annotations

import json
import subprocess

import pytest

from conftest import write_manifest
from wikiskill import collection as collection_mod
from wikiskill import paths, rawlog, refine, wiki
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
    "component": DOER,
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
    assert meta["evidence_model"] is None, "it cites no evidence, so names no model"
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
        ({"action": "rewrite", "component": DOER, "reason": "x", "patterns": []}, "action"),
        ({**PATCH, "component": "disseminate/publish"}, "one proposal changes one component"),
        ({**PATCH, "evidence": ["E9"]}, "E9 were not shown to you"),
    ],
)
def test_a_reply_that_is_not_a_proposal_says_why(repo_collection, reply, expected):
    coll, _, _ = repo_collection
    problems = refine.validate(reply, refine.context(coll, DOER))
    assert any(expected in p for p in problems), problems


def test_no_action_writes_nothing(repo_collection):
    coll, _, _ = repo_collection
    reply = {"action": "no_action", "component": DOER, "reason": "Right already.", "patterns": []}
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


# --------------------------------------------------------------------------- step 8: the checks

SUITE = """suite: doer-suite
tasks:
  - id: save-with-message
    prompt: Save my work in this dataset.
    split: val
    verifiers:
      - { kind: regex, target: final_text, pattern: 'Saved dataset state \\d+ with message' }
  - id: plain
    prompt: Say hello.
    split: val
    verifiers:
      - { kind: regex, target: final_text, pattern: "hello" }
"""


def evaluated_run(coll, doer, tmp_path, *, run_id="01RUN", units=6, model="ollama/qwen3:1.7b"):
    """A finished run of the doer on a real suite file, every unit failing."""
    suite = tmp_path / "doer-suite.yaml"
    suite.write_text(SUITE, encoding="utf-8")
    directory = paths.evals_dir(coll.name) / run_id
    directory.mkdir(parents=True)
    (directory / "run.json").write_text(
        json.dumps(
            {
                "run_id": run_id,
                "suite": "doer-suite",
                "suite_path": str(suite),
                "collection": coll.name,
                "harness": "opencode",
                "tasks": ["save-with-message", "plain"],
                "components": [
                    {"kind": "agent", "name": DOER, "source_hash": rawlog.file_hash(doer)}
                ],
            }
        )
    )
    rows = [
        {
            "run_id": run_id,
            "task_id": "save-with-message",
            "model": model,
            "condition": "injected",
            "repeat": repeat,
            "outcome": "completed",
            "passed": False,
            "expected": {"primary": "datalad-doer"},
            # As a real result carries it: the harness's session, not a live session's ref.
            "session_id": f"ses_{run_id}_{repeat}",
        }
        for repeat in range(units)
    ]
    (directory / "results.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    return rows


def cite_all(coll, rows, slug="no-message-given", model="ollama/qwen3:1.7b"):
    """A second pattern, citing every unit of ``rows``."""
    evidence = {
        f"E{i}": wiki.Evidence(
            id=f"E{i}",
            component=DOER,
            model=model,
            harness="opencode",
            source_hash="h1",
            ref={k: row[k] for k in ("run_id", "task_id", "condition", "repeat", "model")},
        )
        for i, row in enumerate(rows, 1)
    }
    wiki.apply(
        coll.name,
        {
            "create": [
                {
                    "slug": slug,
                    "title": "Saves without a message",
                    "trigger": "save, no message",
                    "cause": "instruction_ignored",
                    "evidence": sorted(evidence),
                    "observation": "Saved without asking for a message.",
                }
            ],
            "update": [],
            "index": {slug: "saves without a message"},
            "log": "x",
        },
        component=DOER,
        evidence=evidence,
        maintainer="m",
    )


@pytest.fixture
def evaluated(repo_collection, tmp_path):
    coll, doer, source = repo_collection
    rows = evaluated_run(coll, doer, tmp_path)
    cite_all(coll, rows)
    return coll, doer, source


def test_the_prompt_shows_the_evidence_behind_the_patterns(evaluated):
    coll, _, _ = evaluated
    found = refine.context(coll, DOER)
    assert sorted(found.evidence.evidence) == [f"E{i}" for i in range(1, 7)]
    assert "Cite at least 4 of these labels" in found.prompt
    assert "task=save-with-message" in found.prompt
    assert "Earlier decisions on this component" in found.prompt


@pytest.mark.parametrize(
    "evidence, expected",
    [
        (["E1", "E2"], "must cite at least 4 of the evidence labels shown; it cites 2"),
        (["E1", "E2", "E7", "S3"], "E7, S3 were not shown to you"),
    ],
)
def test_a_patch_must_cite_enough_shown_evidence(evaluated, evidence, expected):
    coll, _, _ = evaluated
    reply = {**PATCH, "evidence": evidence}
    problems = refine.validate(reply, refine.context(coll, DOER))
    assert any(expected in p for p in problems), problems


def test_enough_shown_evidence_passes(evaluated):
    coll, _, _ = evaluated
    reply = {**PATCH, "evidence": ["E1", "E2", "E3", "E4"]}
    assert refine.validate(reply, refine.context(coll, DOER)) == []


def with_addition(text, **extra):
    edit = {"find": "- Report the branch.", "replace": f"- Report the branch.\n{text}"}
    return {**PATCH, "evidence": ["E1", "E2", "E3", "E4"], "edits": [edit], **extra}


@pytest.mark.parametrize(
    "added, expected",
    [
        ("- As in save-with-message, ask first.", "names `save-with-message`, a task id"),
        ("- Report: Saved dataset state 3 with message.", "contains `Saved dataset state`"),
    ],
)
def test_suite_content_in_added_text_is_a_leak(evaluated, added, expected):
    coll, _, _ = evaluated
    problems = refine.validate(with_addition(added), refine.context(coll, DOER))
    assert any(expected in p for p in problems), problems


def test_an_override_lets_matched_text_through(evaluated):
    coll, _, _ = evaluated
    reply = with_addition("- As in save-with-message, ask first.")
    assert refine.validate(reply, refine.context(coll, DOER), allow_overlap=True) == []


def test_a_rubric_anchor_or_long_note_shared_is_named():
    anchor = "The agent asks the user for a commit message before it saves anything at all."
    leaks = refine.Leaks(passages=[("rubric r, msg/good", anchor)])
    problems = refine.leak_problems(
        "Always: the agent asks the user for a commit message before it saves.", leaks
    )
    assert problems == [
        (
            "leak: the added text shares `the agent asks the user for a commit message before "
            "it saves` with rubric r, msg/good"
        )
    ]
    assert refine.leak_problems("Ask for a message first.", leaks) == []


def test_an_unmarked_model_name_is_refused(evaluated):
    coll, _, _ = evaluated
    reply = with_addition("- If you are qwen3, ask for the message first.")
    problems = refine.validate(reply, refine.context(coll, DOER))
    assert any("names qwen3" in p for p in problems), problems


def test_marked_guidance_needs_scoped_patterns_with_enough_evidence(evaluated):
    coll, _, _ = evaluated
    found = refine.context(coll, DOER)
    small = with_addition("- Small models: ask first.", models=["qwen3"])

    scoped = {**small, "patterns": ["no-message-given"]}
    assert refine.validate(scoped, found) == [], "six items from qwen3 alone"

    thin = {**small, "patterns": ["invents-commit-message"]}
    problems = refine.validate(thin, found)
    assert any("also seen on opencode/big-pickle" in p for p in problems), problems
    assert any("rests on 1 evidence item(s); at least 3" in p for p in problems), problems


def test_the_harness_path_checks_a_reply_against_its_prepared_prompt(evaluated, tmp_path, capsys):
    _, doer, source = evaluated
    assert main(["refine", DOER, "--collection", "dsh", "--prepare"]) == 0
    out = capsys.readouterr().out
    prompt_id = out.split()[1]
    directory = paths.collection_data("dsh") / "samples" / prompt_id
    assert "wikiskill-proposer" not in (directory / "prompt.md").read_text()
    assert "Reply with one JSON object" in (directory / "instructions.md").read_text()

    reply = tmp_path / "reply.json"
    reply.write_text(json.dumps({**PATCH, "evidence": ["E1", "E2", "E3", "E4"]}))
    args = ["refine", DOER, "--collection", "dsh", "--prompt", prompt_id, "--reply-file"]
    assert main([*args, str(reply)]) == 0
    meta = json.loads((paths.wiki_dir("dsh") / "proposals" / "p-001" / "meta.json").read_text())
    assert meta["prompt"] == prompt_id
    assert sorted(meta["evidence"]) == ["E1", "E2", "E3", "E4"]
    assert meta["candidate_hash"] and meta["candidate_hash"] != meta["source_hash"]
    rendered = paths.wiki_dir("dsh") / "proposals" / "p-001" / "rendered" / doer.name
    assert "If none was given, stop and ask" in rendered.read_text()
    assert json.loads((rendered.parent.parent / "proposal.json").read_text())["component"] == DOER
    assert git(source, "status", "--porcelain") == ""


def test_a_prepared_prompt_goes_stale_when_the_component_changes(evaluated, tmp_path, capsys):
    _, doer, _ = evaluated
    main(["refine", DOER, "--collection", "dsh", "--prepare"])
    prompt_id = capsys.readouterr().out.split()[1]
    doer.write_text(TEXT + "- One more rule.\n")
    reply = tmp_path / "reply.json"
    reply.write_text(json.dumps(PATCH))
    args = ["refine", DOER, "--collection", "dsh", "--prompt", prompt_id, "--reply-file"]
    assert main([*args, str(reply)]) == 1
    assert "changed after prompt" in capsys.readouterr().err


def test_a_proposal_records_the_one_model_its_evidence_ran_on():
    def cited(label, model, ref):
        return wiki.Evidence(
            id=label, component=DOER, model=model, harness="opencode", source_hash="h", ref=ref
        )

    unit = {"run_id": "R", "task_id": "t", "condition": "injected", "repeat": 0}
    one = [cited("E1", "ollama/qwen3:1.7b", unit), cited("E2", "qwen3:1.7b", unit)]
    assert refine.evidence_model(one) == "ollama/qwen3:1.7b"
    mixed = [*one, cited("E3", "ollama/gemma4", unit)]
    assert refine.evidence_model(mixed) is None
    live = [*one, cited("E4", "ollama/qwen3:1.7b", {"session_id": "s"})]
    assert refine.evidence_model(live) == "ollama/qwen3:1.7b", "a live session records its model"
    unknown = [*one, cited("E5", "unknown", {"session_id": "s"})]
    assert refine.evidence_model(unknown) is None, "an unrecorded model could be any"
    assert refine.evidence_model([]) is None
