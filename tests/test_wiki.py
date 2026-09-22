"""The experience wiki and the review that feeds it: validated output only, scope from evidence."""

from __future__ import annotations

import json
import subprocess

import pytest

from conftest import write_manifest
from wikiskill import collection as collection_mod
from wikiskill import paths, review, wiki
from wikiskill.cli import main
from wikiskill.frontmatter import read as read_frontmatter

DOER = "datalad/datalad-doer"
RUN = "01M35BCRYHJGDFYM3651PFTDMD"


def evidence(label, model="opencode/big-pickle", hash_="h1", condition="injected"):
    return wiki.Evidence(
        id=label,
        component=DOER,
        model=model,
        harness="opencode",
        source_hash=hash_,
        ref={"run_id": RUN, "task_id": "t", "condition": condition, "repeat": 0, "model": model},
    )


EVIDENCE = {"E1": evidence("E1"), "E2": evidence("E2", model="ollama/qwen3:1.7b", hash_="h2")}


def good_output(**changes):
    output = {
        "create": [
            {
                "slug": "invents-commit-message",
                "title": "Invents a commit message when none is given",
                "trigger": "A save request with no message",
                "cause": "instruction_ignored",
                "evidence": ["E1", "E2"],
                "observation": "The instructions say never to guess -m; the run guessed one.",
                "suggestion": "Move the rule into the Steps list.",
            }
        ],
        "update": [],
        "index": {"invents-commit-message": "Guesses -m instead of asking"},
        "log": "Two failures of one rule.",
    }
    output.update(changes)
    return output


# --------------------------------------------------------------------------- validation


def test_a_good_reply_validates():
    assert wiki.validate(good_output(), component=DOER, evidence=EVIDENCE, existing=[]) == []


def test_a_schema_break_is_reported_with_its_path():
    output = good_output()
    del output["log"]
    problems = wiki.validate(output, component=DOER, evidence=EVIDENCE, existing=[])
    assert problems and "'log' is a required property" in problems[0]


@pytest.mark.parametrize(
    "changes, existing, expected",
    [
        ({}, ["invents-commit-message"], "already exists; put new evidence under `update`"),
        (
            {
                "update": [{"slug": "nope", "evidence": ["E1"], "observation": "x"}],
            },
            [],
            "there is no pattern 'nope'",
        ),
        (
            {
                "create": [
                    {**good_output()["create"][0], "evidence": ["E9"]},
                ]
            },
            [],
            "cites evidence that was not given: E9",
        ),
        ({"index": {}}, [], "index: missing a summary for invents-commit-message"),
    ],
)
def test_output_that_cannot_be_applied_says_why(changes, existing, expected):
    problems = wiki.validate(
        good_output(**changes), component=DOER, evidence=EVIDENCE, existing=existing
    )
    assert any(expected in p for p in problems), problems


def test_a_slug_another_component_owns_is_taken():
    problems = wiki.validate(
        good_output(),
        component=DOER,
        evidence=EVIDENCE,
        existing=[],
        taken=["invents-commit-message"],
    )
    assert any("already exists" in p for p in problems)


def test_a_reply_is_read_past_thinking_and_fences():
    text = '<think>hmm {not json}</think>\nHere:\n```json\n{"a": 1}\n```'
    assert wiki.parse_reply(text) == {"a": 1}
    with pytest.raises(wiki.WikiError, match="no JSON object"):
        wiki.parse_reply("I could not decide.")


# --------------------------------------------------------------------------- applying


def test_apply_writes_a_pattern_whose_scope_comes_from_its_evidence(xdg):
    applied = wiki.apply(
        "dsh", good_output(), component=DOER, evidence=EVIDENCE, maintainer="m", runs=[RUN]
    )

    root = paths.wiki_dir("dsh")
    meta = read_frontmatter(root / "patterns" / "invents-commit-message.md").meta
    assert applied.created == ["invents-commit-message"]
    assert meta["models"] == ["ollama/qwen3:1.7b", "opencode/big-pickle"]
    assert meta["source_hashes"] == ["h1", "h2"]
    assert meta["harnesses"] == ["opencode"]
    assert meta["evidence"][0]["run_id"] == RUN
    assert "invents-commit-message" in (root / "index.md").read_text()
    assert "Two failures of one rule." in (root / "log.md").read_text()
    assert applied.committed
    log = subprocess.run(
        ["git", "-C", str(root), "log", "--format=%s"], capture_output=True, text=True, check=True
    )
    assert log.stdout.startswith(f"review {DOER}: 1 created, 0 updated")


def test_an_update_merges_evidence_and_scope(xdg):
    one = {"E1": EVIDENCE["E1"]}
    wiki.apply(
        "dsh",
        good_output(create=[{**good_output()["create"][0], "evidence": ["E1"]}]),
        component=DOER,
        evidence=one,
        maintainer="m",
    )
    update = {
        "create": [],
        "update": [{"slug": "invents-commit-message", "evidence": ["E2"], "observation": "Again."}],
        "index": {"invents-commit-message": "Still guesses -m"},
        "log": "One more.",
    }
    applied = wiki.apply("dsh", update, component=DOER, evidence=EVIDENCE, maintainer="m")

    document = read_frontmatter(paths.wiki_dir("dsh") / "patterns" / "invents-commit-message.md")
    assert applied.updated == ["invents-commit-message"]
    assert document.meta["models"] == ["ollama/qwen3:1.7b", "opencode/big-pickle"]
    assert len(document.meta["evidence"]) == 2
    assert document.meta["summary"] == "Still guesses -m"
    assert "Again." in document.body


# --------------------------------------------------------------------------- review


@pytest.fixture
def doer_collection(xdg, plugin_source):
    (plugin_source / "datalad" / "agents" / "datalad-doer.md").write_text(
        "---\nname: datalad-doer\ndescription: d\n---\n\nNever guess a -m message.\n",
        encoding="utf-8",
    )
    write_manifest(
        xdg,
        "dsh",
        f'name = "dsh"\nsources = [{{ path = "{plugin_source}", layout = "claude-plugin", '
        'plugins = ["datalad"] }]\n[watch]\nagents = ["datalad/datalad-doer"]\n'
        '[roles.maintainer]\nbase_url = "http://localhost:9/v1"\nmodel = "qwen3:1.7b"\n',
    )
    evals = paths.evals_dir("dsh") / RUN
    evals.mkdir(parents=True)
    (evals / "run.json").write_text(
        json.dumps(
            {
                "run_id": RUN,
                "suite": "datalad-doer",
                "harness": "opencode",
                "tasks": ["save", "log"],
                "components": [{"kind": "agent", "name": DOER, "source_hash": "h1"}],
            }
        )
    )
    results = []
    for task, passed, repeats in (("save", False, 2), ("log", True, 3)):
        for repeat in range(repeats):
            results.append(
                {
                    "run_id": RUN,
                    "task_id": task,
                    "model": "opencode/big-pickle",
                    "condition": "injected",
                    "repeat": repeat,
                    "outcome": "completed",
                    "passed": passed,
                    "verifiers": [{"kind": "command", "passed": passed, "detail": "no commit"}],
                    "expected": {"primary": "datalad-doer", "agents": []},
                }
            )
    (evals / "results.jsonl").write_text("".join(json.dumps(r) + "\n" for r in results))
    raw = paths.raw_dir("dsh") / "2026-09-22"
    raw.mkdir(parents=True)
    event = {
        "schema_version": 1,
        "type": "tool_call",
        "model": "big-pickle",
        "eval": {
            "run_id": RUN,
            "suite": "datalad-doer",
            "task_id": "save",
            "condition": "injected",
            "repeat": 0,
        },
        "payload": {"tool": "bash", "ok": True, "input": {"command": "datalad save -m 'Add data'"}},
    }
    (raw / "ses.jsonl").write_text(json.dumps(event) + "\n")
    return collection_mod.load("dsh")


def test_the_digest_puts_failures_first_and_keeps_one_pass_per_task(doer_collection):
    found = review.digest(doer_collection, DOER)

    assert "Never guess a -m message." in found.text, "the component's own instructions"
    assert found.text.index("[E1] task=save") < found.text.index("task=log")
    assert "datalad save: datalad save -m 'Add data'" in found.text
    assert "failed checks: no commit" in found.text
    assert sum(1 for e in found.evidence.values() if e.ref["task_id"] == "log") == 1
    assert found.runs == [RUN]


def test_the_digest_respects_its_budget(doer_collection):
    full = review.digest(doer_collection, DOER)
    found = review.digest(doer_collection, DOER, budget=len(full.text) - 50)
    assert len(found.evidence) < len(full.evidence)
    assert found.omitted == len(full.evidence) - len(found.evidence)
    assert "did not fit" in found.text


def test_reviewing_something_the_collection_lacks_is_refused(doer_collection):
    with pytest.raises(review.ReviewError, match="is not a component"):
        review.digest(doer_collection, "govern/preregister")


def reply_for(found):
    first = next(iter(found.evidence))
    return json.dumps(
        {
            "create": [
                {
                    "slug": "invents-commit-message",
                    "title": "Invents a message",
                    "trigger": "save without -m",
                    "cause": "instruction_ignored",
                    "evidence": [first],
                    "observation": "It guessed one.",
                }
            ],
            "update": [],
            "index": {"invents-commit-message": "Guesses -m"},
            "log": "One pattern.",
        }
    )


def test_a_bad_reply_is_returned_with_its_problems_then_applied(doer_collection):
    found = review.digest(doer_collection, DOER)
    replies = iter(["no json here", reply_for(found)])
    seen = []

    def ask(messages):
        seen.append(messages)
        return next(replies)

    outcome = review.review(doer_collection, DOER, ask=ask, maintainer="fake")

    assert outcome.attempts == 2
    assert outcome.applied.created == ["invents-commit-message"]
    assert "holds no JSON object" in seen[1][-1]["content"], "the problems go back to the model"


def test_a_reply_that_never_validates_writes_nothing(doer_collection):
    outcome = review.review(
        doer_collection, DOER, ask=lambda _m: "{}", maintainer="fake", retries=2
    )
    assert outcome.applied is None
    assert outcome.attempts == 3
    assert not paths.wiki_dir("dsh").exists()


def test_cli_review_dry_run_and_reply_file(doer_collection, tmp_path, capsys):
    assert main(["review", DOER, "--collection", "dsh", "--dry-run"]) == 0
    assert "[E1]" in capsys.readouterr().out
    assert not paths.wiki_dir("dsh").exists(), "a dry run writes nothing"

    reply = tmp_path / "reply.json"
    reply.write_text(reply_for(review.digest(doer_collection, DOER)))
    assert main(["review", DOER, "--collection", "dsh", "--reply-file", str(reply)]) == 0
    assert "created  invents-commit-message" in capsys.readouterr().out

    reply.write_text("{}")
    assert main(["review", DOER, "--collection", "dsh", "--reply-file", str(reply)]) == 1
    assert "nothing written" in capsys.readouterr().out
