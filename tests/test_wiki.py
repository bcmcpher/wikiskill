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


def git_log(root):
    done = subprocess.run(
        ["git", "-C", str(root), "log", "--format=%s"], capture_output=True, text=True, check=True
    )
    return done.stdout.splitlines()


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
    assert "wait for a later review" in found.text


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


def test_a_reply_that_never_validates_writes_only_a_log_entry(doer_collection):
    outcome = review.review(
        doer_collection, DOER, ask=lambda _m: "{}", maintainer="fake", retries=2
    )
    assert outcome.applied is None
    assert outcome.attempts == 3
    root = paths.wiki_dir("dsh")
    assert not list((root / "patterns").glob("*.md"))
    assert not (root / wiki.WATERMARK).exists(), "the evidence is still unreviewed"
    log = (root / "log.md").read_text()
    assert f"review of `{DOER}` by fake failed" in log
    assert "after 3 attempt(s)" in log
    assert git_log(root) == [f"review {DOER}: failed after 3 attempt(s)"]
    # The failed review did not use the evidence up.
    assert review.digest(doer_collection, DOER).evidence


def test_cli_review_dry_run_and_reply_file(doer_collection, tmp_path, capsys):
    assert main(["review", DOER, "--collection", "dsh", "--dry-run"]) == 0
    assert "[E1]" in capsys.readouterr().out
    assert not paths.wiki_dir("dsh").exists(), "a dry run writes nothing"

    reply = tmp_path / "reply.json"
    reply.write_text(reply_for(review.digest(doer_collection, DOER)))
    assert main(["review", DOER, "--collection", "dsh", "--reply-file", str(reply)]) == 0
    assert "created  invents-commit-message" in capsys.readouterr().out

    assert main(["review", DOER, "--collection", "dsh", "--reply-file", str(reply)]) == 0
    assert "nothing new to review" in capsys.readouterr().out

    reply.write_text("{}")
    argv = ["review", DOER, "--collection", "dsh", "--reply-file", str(reply), "--resample"]
    assert main(argv) == 1
    assert "no pattern written" in capsys.readouterr().out


# --------------------------------------------------------------------------- step 7: sampling


def live_session(session, *signals, day="2026-10-05", model="gemma4", harness="opencode"):
    """A logged live session of the doer, with correction signals appended in order."""
    base = {
        "schema_version": 1,
        "origin": "live",
        "harness": harness,
        "provider": "ollama",
        "model": model,
        "session_id": session,
        "root_session_id": session,
    }
    component = {"kind": "agent", "name": DOER, "source_hash": "h1"}
    events = [
        {
            **base,
            "event_id": f"{session}-0",
            "type": "component_activated",
            "component": component,
            "payload": {},
        },
    ]
    for number, (kind, payload) in enumerate(signals, start=1):
        events.append(
            {
                **base,
                "event_id": f"{session}-{number}",
                "type": kind,
                "component": component,
                "payload": payload,
            }
        )
    directory = paths.raw_dir("dsh") / day
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / f"{session}.jsonl").open("a", encoding="utf-8") as handle:
        for event in events:
            handle.write(json.dumps(event) + "\n")


def test_a_noted_session_comes_before_clean_ones_and_clean_ones_are_capped(doer_collection):
    for number in range(5):
        live_session(f"clean{number}")
    live_session("noted", ("note", {"text": "it guessed the -m message again"}))
    live_session("followed", ("user_turn", {"text": "no, ask me first"}))

    found = review.digest(doer_collection, DOER)

    assert found.evidence["S1"].ref == {"session_id": "noted"}
    assert found.evidence["S1"].source_hash == "h1", "the version the session activated"
    assert "user note: it guessed the -m message again" in found.text
    assert found.evidence["S2"].ref == {"session_id": "followed"}
    assert "user said next" in found.text
    # The eval failures rank between the note and the follow-up.
    assert found.text.index("[S1]") < found.text.index("[E1] task=save") < found.text.index("[S2]")
    clean = [e for e in found.evidence.values() if e.ref.get("session_id", "").startswith("clean")]
    passes = [e for e in found.evidence.values() if e.ref.get("task_id") == "log"]
    assert len(clean) + len(passes) == review.DEFAULT_CLEAN
    assert found.omitted == 3, "the clean evidence past the quota waits"


@pytest.mark.parametrize(
    ("context", "budget"), [(None, 15_000), (131_072, 15_000), (32_768, 7_500), (4_096, 4_000)]
)
def test_the_budget_follows_the_maintainers_context(xdg, plugin_source, context, budget):
    extra = f"context_tokens = {context}\n" if context else ""
    write_manifest(
        xdg,
        "small",
        f'name = "small"\nsources = [{{ path = "{plugin_source}", layout = "claude-plugin" }}]\n'
        '[watch]\nagents = ["datalad/datalad-doer"]\n'
        f'[roles.maintainer]\nmodel = "qwen3:1.7b"\n{extra}',
    )
    assert review.budget_for(collection_mod.load("small")) == budget


def asked_never(_messages):
    raise AssertionError("no model is asked when there is nothing to review")


def test_a_second_review_with_nothing_new_asks_nothing_and_commits_nothing(doer_collection):
    found = review.digest(doer_collection, DOER)
    review.review(doer_collection, DOER, ask=lambda _m: reply_for(found), maintainer="m")
    root = paths.wiki_dir("dsh")
    commits = git_log(root)
    marked = json.loads((root / wiki.WATERMARK).read_text())[DOER]
    assert sorted(marked["eval"]) == sorted(found.shown["eval"])

    with pytest.raises(review.NothingToReview, match="--resample"):
        review.review(doer_collection, DOER, ask=asked_never, maintainer="m")
    assert git_log(root) == commits
    assert review.digest(doer_collection, DOER, resample=True).evidence


def test_a_reviewed_session_that_gains_a_note_is_sampled_again_first(doer_collection):
    live_session("s1")
    found = review.digest(doer_collection, DOER)
    review.review(doer_collection, DOER, ask=lambda _m: reply_for(found), maintainer="m")
    with pytest.raises(review.NothingToReview):
        review.digest(doer_collection, DOER)

    path = paths.raw_dir("dsh") / "2026-10-05" / "s1.jsonl"
    late = json.loads(path.read_text().splitlines()[0])
    late.update(event_id="s1-9", type="note", payload={"text": "wrong remote"})
    with path.open("a") as handle:
        handle.write(json.dumps(late) + "\n")

    again = review.digest(doer_collection, DOER)
    assert list(again.evidence) == ["S1"]
    assert "user note: wrong remote" in again.text


# --------------------------------------------------------------------------- step 7: contract


def test_universal_needs_two_models_or_two_harnesses():
    one = {"E1": EVIDENCE["E1"]}
    claim = good_output(
        create=[{**good_output()["create"][0], "evidence": ["E1"], "universal": True}]
    )
    problems = wiki.validate(claim, component=DOER, evidence=one, existing=[])
    assert len(problems) == 1
    assert "`universal` needs evidence from at least two models" in problems[0]
    assert "opencode/big-pickle under opencode" in problems[0]

    both = good_output(create=[{**good_output()["create"][0], "universal": True}])
    assert wiki.validate(both, component=DOER, evidence=EVIDENCE, existing=[]) == []

    # An update counts the evidence the pattern already has.
    update = {
        "create": [],
        "update": [
            {"slug": "p-one", "evidence": ["E1"], "observation": "Again.", "universal": True}
        ],
        "index": {"p-one": "s"},
        "log": "l",
    }
    known = {"p-one": {"models": ["ollama/qwen3:1.7b"], "harnesses": ["opencode"]}}
    assert wiki.validate(update, component=DOER, evidence=one, existing=known) == []


def test_a_superseded_pattern_leaves_the_index_but_keeps_its_page(xdg):
    wiki.apply("dsh", good_output(), component=DOER, evidence=EVIDENCE, maintainer="m")
    retire = {
        "create": [],
        "update": [
            {
                "slug": "invents-commit-message",
                "evidence": ["E2"],
                "observation": "Fixed in h2.",
                "status": "superseded",
            }
        ],
        "index": {"invents-commit-message": "still listed"},
        "log": "Retired.",
    }
    existing = {s: d.meta for s, d in wiki.patterns("dsh", DOER).items()}
    problems = wiki.validate(retire, component=DOER, evidence=EVIDENCE, existing=existing)
    assert problems == [
        "index: summarises patterns that do not exist or are superseded: invents-commit-message"
    ]

    retire["index"] = {}
    assert wiki.validate(retire, component=DOER, evidence=EVIDENCE, existing=existing) == []
    applied = wiki.apply("dsh", retire, component=DOER, evidence=EVIDENCE, maintainer="m")

    root = paths.wiki_dir("dsh")
    assert applied.superseded == ["invents-commit-message"]
    assert "invents-commit-message" not in (root / "index.md").read_text()
    page = read_frontmatter(root / "patterns" / "invents-commit-message.md")
    assert page.meta["status"] == "superseded"
    assert "Fixed in h2. Superseded." in page.body
    # A superseded pattern needs no index line, and the maintainer no longer sees it.
    existing = {s: d.meta for s, d in wiki.patterns("dsh", DOER).items()}
    empty = {"create": [], "update": [], "index": {}, "log": "Nothing new."}
    assert wiki.validate(empty, component=DOER, evidence=EVIDENCE, existing=existing) == []


def test_a_components_first_pattern_creates_its_page_and_each_review_adds_history(xdg):
    wiki.apply("dsh", good_output(), component=DOER, evidence=EVIDENCE, maintainer="m1")
    page = paths.wiki_dir("dsh") / "components" / "datalad-datalad-doer.md"
    assert page == wiki.component_page("dsh", DOER)
    text = page.read_text()
    assert f"# `{DOER}`" in text
    assert "| [invents-commit-message](../patterns/invents-commit-message.md) | active |" in text
    assert "review by m1: created invents-commit-message" in text

    update = {
        "create": [],
        "update": [{"slug": "invents-commit-message", "evidence": ["E1"], "observation": "x"}],
        "index": {"invents-commit-message": "s"},
        "log": "l",
    }
    wiki.apply("dsh", update, component=DOER, evidence=EVIDENCE, maintainer="m2")
    text = page.read_text()
    assert text.count("| [invents-commit-message]") == 1, "the table is regenerated"
    assert "review by m1" in text and "review by m2: created none; updated invents-commit" in text


# --------------------------------------------------------------------------- step 7: samples


def test_a_persisted_sample_is_applied_against_its_own_evidence(doer_collection, tmp_path, capsys):
    argv = ["sample", DOER, "--collection", "dsh"]
    assert main(argv) == 0
    out = capsys.readouterr().out
    sample_id = out.split()[1]
    directory = review.samples_dir("dsh") / sample_id
    assert (directory / "prompt.md").read_text().startswith(f"# Component under review: {DOER}")
    assert "You maintain an experience wiki" in (directory / "instructions.md").read_text()

    found = review.load_sample(doer_collection, sample_id)
    reply = tmp_path / "reply.json"
    reply.write_text(reply_for(found))
    argv = ["review", DOER, "--collection", "dsh", "--sample", sample_id]
    assert main([*argv, "--reply-file", str(reply)]) == 0
    assert "created  invents-commit-message" in capsys.readouterr().out
    marked = wiki.processed("dsh", DOER)[0]
    assert marked == set(found.shown["eval"])

    # The same sample again is stale: the pattern list it showed has changed.
    with pytest.raises(review.ReviewError, match="is stale"):
        review.load_sample(doer_collection, sample_id)


def test_a_sample_needs_a_reply_and_the_right_component(doer_collection, capsys):
    assert main(["review", DOER, "--collection", "dsh", "--sample", "x"]) == 2
    assert "--sample needs --reply-file" in capsys.readouterr().err


def test_a_unit_the_harness_broke_under_is_not_evidence(doer_collection):
    results = paths.evals_dir("dsh") / RUN / "results.jsonl"
    broken = {
        "run_id": RUN,
        "task_id": "save",
        "model": "opencode/big-pickle",
        "condition": "routed",
        "repeat": 0,
        "outcome": "infra_error",
        "passed": None,
        "reason": "claude produced no session",
        "expected": {"primary": "datalad-doer", "agents": []},
    }
    with results.open("a") as handle:
        handle.write(json.dumps(broken) + "\n")
    assert "claude produced no session" not in review.digest(doer_collection, DOER).text


def test_failures_the_component_took_part_in_come_before_off_failures(doer_collection):
    results = paths.evals_dir("dsh") / RUN / "results.jsonl"
    lines = results.read_text().splitlines(keepends=True)
    off = [
        json.dumps(
            {
                "run_id": RUN,
                "task_id": f"off-{n}",
                "model": "opencode/big-pickle",
                "condition": "off",
                "repeat": 0,
                "outcome": "completed",
                "passed": False,
                "expected": {"primary": "datalad-doer", "agents": []},
            }
        )
        + "\n"
        for n in range(review.DEFAULT_SIGNALS)
    ]
    # Written first, so log order alone would let them fill the whole quota.
    results.write_text("".join(off + lines))

    found = review.digest(doer_collection, DOER)

    assert found.evidence["E1"].ref["condition"] == "injected"
    assert sum(1 for e in found.evidence.values() if e.ref["task_id"] == "save") == 2


def test_a_review_for_one_model_shows_only_its_units(doer_collection):
    evals = paths.evals_dir("dsh") / RUN / "results.jsonl"
    other = {
        "run_id": RUN,
        "task_id": "save",
        "model": "ollama/qwen3:1.7b",
        "condition": "injected",
        "repeat": 0,
        "outcome": "completed",
        "passed": False,
        "verifiers": [{"kind": "command", "passed": False, "detail": "a commit"}],
        "expected": {"primary": "datalad-doer", "agents": []},
    }
    with evals.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(other) + "\n")
    live_session("ses-live", ("note", {"text": "wrong message"}))

    found = review.digest(doer_collection, DOER, model="qwen3:1.7b")

    assert {e.model for e in found.evidence.values()} == {"ollama/qwen3:1.7b"}
    assert all("run_id" in e.ref for e in found.evidence.values()), "the live session ran gemma4"
    assert "restricted to eval units and live sessions run on qwen3:1.7b" in found.text
    everything = review.digest(doer_collection, DOER)
    assert any("run_id" not in e.ref for e in everything.evidence.values())


def test_a_review_for_a_model_with_no_units_is_refused(doer_collection):
    with pytest.raises(review.ReviewError, match="no eval run or live session on gemma4"):
        review.digest(doer_collection, DOER, model="gemma4")


def test_a_review_for_one_model_keeps_that_models_live_sessions(doer_collection):
    live_session("ses-gemma", ("note", {"text": "wrong message"}), model="gemma4")
    live_session("ses-qwen", ("note", {"text": "also wrong"}), model="qwen3:1.7b")

    found = review.digest(doer_collection, DOER, model="gemma4")

    live = [e for e in found.evidence.values() if "run_id" not in e.ref]
    assert [e.ref["session_id"] for e in live] == ["ses-gemma"]
    assert all(e.model.endswith("gemma4") for e in found.evidence.values())


@pytest.mark.parametrize(
    ("recorded", "wanted", "same"),
    [
        ("ollama/qwen3:1.7b", "qwen3:1.7b", True),
        ("ollama/qwen3:1.7b", "OLLAMA/qwen3:1.7b", True),
        ("qwen3:1.7b", "ollama/qwen3:1.7b", True),
        ("openrouter/meta/llama-3", "meta/llama-3", True),
        ("openrouter/meta/llama-3", "llama-3", False),
        ("ollama/qwen3:1.7b", "qwen3:30b-a3b", False),
    ],
)
def test_a_model_is_named_with_or_without_its_provider(recorded, wanted, same):
    assert review._same_model(recorded, wanted) is same


def test_cli_review_refuses_a_model_for_a_stored_sample(doer_collection, capsys):
    code = main(
        [
            "review",
            DOER,
            "--collection",
            "dsh",
            "--sample",
            "s",
            "--reply-file",
            "r",
            "--model",
            "m",
        ]
    )
    assert code == 2
    assert "--sample keeps the evidence it was taken with" in capsys.readouterr().err


def test_cli_sample_takes_a_model(doer_collection, capsys):
    code = main(["sample", DOER, "--collection", "dsh", "--model", "big-pickle"])
    assert code == 0
    assert "sample " in capsys.readouterr().out
