"""The refinement gate: candidate runs, replay, and the decision only the user makes."""

from __future__ import annotations

import json

import pytest

import test_refine
from test_refine import DOER, PATCH, git, replies
from wikiskill import collection as collection_mod
from wikiskill import gate, paths, rawlog, refine, wiki
from wikiskill.cli import main

#: Shared with the proposal tests.
repo_collection = test_refine.repo_collection
evaluated = test_refine.evaluated

GOOD = {
    **PATCH,
    "patterns": ["invents-commit-message", "no-message-given"],
    "evidence": ["E1", "E2", "E3", "E4"],
}


@pytest.fixture
def proposed(evaluated):
    """A collection with one proposal, p-001, made from six failing units."""
    coll, doer, source = evaluated
    proposal = refine.refine(coll, DOER, ask=replies(json.dumps(GOOD)), proposer="fake")
    assert proposal.directory.name == "p-001"
    return coll, doer, source


def write_run(coll, run_id, *, source_hash, outcomes, proposal=None):
    """A finished run: ``outcomes`` maps (task, model) to that cell's verdicts, one per repeat."""
    directory = paths.evals_dir(coll.name) / run_id
    directory.mkdir(parents=True)
    tasks = sorted({task for task, _ in outcomes})
    (directory / "run.json").write_text(
        json.dumps(
            {
                "run_id": run_id,
                "suite": "doer-suite",
                "suite_hash": "sha256:s",
                "collection": coll.name,
                "tasks": tasks,
                "components": [{"kind": "agent", "name": DOER, "source_hash": source_hash}],
                "proposal": proposal,
            }
        )
    )
    rows = [
        {
            "run_id": run_id,
            "task_id": task,
            "model": model,
            "condition": condition,
            "repeat": repeat,
            "outcome": "completed",
            "passed": verdict,
            "expected": {"primary": "datalad-doer"},
        }
        for (task, model), verdicts in outcomes.items()
        for condition in ("off", "injected")
        for repeat, verdict in enumerate(verdicts)
    ]
    (directory / "results.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    return directory


def meta(coll, proposal="p-001"):
    return gate.load(coll.name, proposal)


QWEN, GEMMA = "ollama/qwen3:1.7b", "ollama/gemma4"


def runs_for(coll, *, after_plain_gemma):
    """Baseline and candidate: motivating case fixed on qwen3; `plain` on gemma4 as given."""
    m = meta(coll)
    base = write_run(
        coll,
        "01BASE",
        source_hash=m["source_hash"],
        outcomes={
            ("save-with-message", QWEN): [False, False, False],
            ("save-with-message", GEMMA): [True, True, True],
            ("plain", QWEN): [True, True, True],
            ("plain", GEMMA): [True, True, True],
        },
    )
    cand = write_run(
        coll,
        "01CAND",
        source_hash=m["candidate_hash"],
        proposal="p-001",
        outcomes={
            ("save-with-message", QWEN): [True, True, True],
            ("save-with-message", GEMMA): [True, True, True],
            ("plain", QWEN): [True, True, True],
            ("plain", GEMMA): after_plain_gemma,
        },
    )
    return base, cand


# --------------------------------------------------------------------------- decide


def test_a_decision_without_replay_is_recorded_as_unreplayed(proposed):
    coll, _, _ = proposed
    patterns_before = {slug: doc.render() for slug, doc in wiki.patterns(coll.name, DOER).items()}

    target = gate.decide(coll.name, "p-001", "reject", note="Too broad.")

    assert meta(coll)["status"] == "rejected"
    text = target.read_text()
    assert "## p-001: reject" in text
    assert "- note: Too broad." in text
    assert "- replay: not run" in text
    assert '"reason": "Make the rule say what to do instead."' in text, "rejected kept in full"
    assert "+- Never use an empty/placeholder `-m` message. If none was given" in text
    after = {slug: doc.render() for slug, doc in wiki.patterns(coll.name, DOER).items()}
    assert after == patterns_before, "a decision changes no pattern"
    assert "## p-001: reject" in refine.context(coll, DOER).prompt, "the next proposer sees it"


def test_a_decision_is_final(proposed):
    coll, _, _ = proposed
    gate.decide(coll.name, "p-001", "withdraw")
    with pytest.raises(gate.GateError, match="already withdrawn"):
        gate.decide(coll.name, "p-001", "accept")


# --------------------------------------------------------------------------- replay


def test_replay_recommends_but_never_accepts(proposed):
    coll, _, _ = proposed
    base, cand = runs_for(coll, after_plain_gemma=[True, True, True])

    result = gate.replay(coll.name, "p-001", base, cand)

    assert result.recommendation == gate.ACCEPT
    assert result.motivating == ["save-with-message"]
    assert result.bank == ["plain"]
    assert result.unreplayable["task t of run R"] == "not a task of suite doer-suite"
    qwen_a, qwen_b = result.motivating_rates[("injected", QWEN)]
    assert (qwen_a.passed, qwen_b.passed) == (0, 3)
    assert ("off", QWEN) not in result.motivating_rates, "OFF never loads the component"
    assert meta(coll)["status"] == "replayed", "only a decision accepts"
    replay_dir = gate.directory(coll.name, "p-001")
    assert (replay_dir / "replay.md").is_file() and (replay_dir / "replay.json").is_file()


def test_a_regression_is_named_even_when_the_net_improves(proposed):
    coll, _, _ = proposed
    base, cand = runs_for(coll, after_plain_gemma=[True, False, False])

    result = gate.replay(coll.name, "p-001", base, cand)

    assert result.recommendation == gate.DO_NOT_ACCEPT
    (fell,) = result.regressions
    assert (fell.task, fell.model, fell.condition) == ("plain", GEMMA, "injected")
    assert "| injected | ollama/gemma4 | plain | 3/3 | 1/3 | yes |" in gate.render(result)


def test_one_lost_repeat_in_three_is_listed_but_within_tolerance(proposed):
    coll, _, _ = proposed
    base, cand = runs_for(coll, after_plain_gemma=[True, True, False])
    result = gate.replay(coll.name, "p-001", base, cand)
    assert len(result.regressions) == 1
    assert result.recommendation == gate.ACCEPT


def test_replay_refuses_runs_that_are_not_what_they_claim(proposed):
    coll, _, _ = proposed
    m = meta(coll)
    wrong = write_run(
        coll, "01WRONG", source_hash="sha256:other", outcomes={("plain", QWEN): [True]}
    )
    cand = write_run(
        coll,
        "01CAND",
        source_hash=m["candidate_hash"],
        outcomes={("plain", QWEN): [True]},
    )
    with pytest.raises(gate.GateError, match="not at p-001's source_hash"):
        gate.replay(coll.name, "p-001", wrong, cand)
    base = write_run(coll, "01BASE", source_hash=m["source_hash"], outcomes={("plain", QWEN): [1]})
    with pytest.raises(gate.GateError, match="neither ran under p-001"):
        gate.replay(coll.name, "p-001", base, base)


def test_live_evidence_is_listed_as_not_replayable(proposed):
    coll, _, _ = proposed
    document = wiki.patterns(coll.name, DOER)["no-message-given"]
    document.meta["evidence"].append({"session_id": "ses_live"})
    path = wiki.wiki_root(coll.name) / wiki.PATTERNS / "no-message-given.md"
    path.write_text(document.render())
    base, cand = runs_for(coll, after_plain_gemma=[True, True, True])

    result = gate.replay(coll.name, "p-001", base, cand)

    assert "a live session" in result.unreplayable["session ses_live"]


def test_the_impact_entry_carries_the_replay(proposed):
    coll, _, _ = proposed
    base, cand = runs_for(coll, after_plain_gemma=[True, False, False])
    gate.replay(coll.name, "p-001", base, cand)
    text = gate.decide(coll.name, "p-001", "accept", note="Worth it.").read_text()
    assert "- replay: recommendation do not accept" in text
    assert "- fell: plain on ollama/gemma4 (injected): 3/3 -> 1/3" in text
    assert "### Proposal" not in text, "an accepted proposal is its diff"
    assert meta(coll)["status"] == "accepted"


# --------------------------------------------------------------------------- candidate runs


def test_a_candidate_runs_from_a_copy_and_the_source_is_untouched(proposed, tmp_path):
    coll, doer, source = proposed
    before = doer.read_bytes()

    candidate = gate.candidate_collection(coll, "p-001", tmp_path / "run")

    (component,) = [c for c in candidate.discover() if c.name == DOER]
    assert component.path.is_relative_to(tmp_path / "run" / "candidate-source")
    assert rawlog.file_hash(component.path) == meta(coll)["candidate_hash"]
    assert not (tmp_path / "run" / "candidate-source" / ".git").exists()
    assert doer.read_bytes() == before
    assert git(source, "status", "--porcelain") == ""


def test_a_candidate_is_refused_once_the_source_moved_on(proposed, tmp_path):
    coll, doer, _ = proposed
    doer.write_text(doer.read_text() + "- New rule.\n")
    with pytest.raises(gate.GateError, match="has changed since p-001"):
        gate.candidate_collection(coll, "p-001", tmp_path / "run")


# --------------------------------------------------------------------------- apply


def test_apply_without_a_branch_writes_nothing(proposed, capsys):
    _, _, source = proposed
    assert main(["proposal", "apply", "p-001", "--collection", "dsh"]) == 0
    assert "git -C" in capsys.readouterr().out
    assert git(source, "status", "--porcelain") == ""
    assert "wikiskill/" not in git(source, "branch", "--list")


def test_apply_on_a_branch_commits_there_and_returns(proposed):
    coll, doer, source = proposed
    start = git(source, "symbolic-ref", "--short", "HEAD").strip()
    git(source, "config", "user.name", "t")
    git(source, "config", "user.email", "t@t")

    name = gate.apply(coll.name, "p-001", branch=True)

    assert name == f"wikiskill/{DOER}/p-001"
    assert git(source, "symbolic-ref", "--short", "HEAD").strip() == start
    assert git(source, "status", "--porcelain") == ""
    assert "If none was given" in git(source, "show", f"{name}:datalad/agents/datalad-doer.md")
    assert "If none was given" not in doer.read_text()


def test_apply_on_a_branch_refuses_a_dirty_worktree(proposed):
    coll, _, source = proposed
    (source / "scratch.txt").write_text("x")
    with pytest.raises(gate.GateError, match="uncommitted changes"):
        gate.apply(coll.name, "p-001", branch=True)
    assert "wikiskill/" not in git(source, "branch", "--list")


# --------------------------------------------------------------------------- cli


def test_cli_lists_replays_and_decides(proposed, capsys):
    coll, _, _ = proposed
    base, cand = runs_for(coll, after_plain_gemma=[True, True, True])
    collection = ["--collection", "dsh"]

    assert main(["proposal", "replay", "p-001", str(base), str(cand), *collection]) == 0
    assert main(["proposal", "list", *collection]) == 0
    assert "p-001  replayed   datalad/datalad-doer  recommends accept" in capsys.readouterr().out
    assert main(["proposal", "decide", "p-001", "reject", "--note", "no", *collection]) == 0
    assert main(["proposal", "decide", "p-001", "accept", *collection]) == 1
    assert "already rejected" in capsys.readouterr().err


def test_compare_record_goes_through_the_gate(proposed, capsys):
    coll, _, _ = proposed
    runs_for(coll, after_plain_gemma=[True, True, True])
    args = ["compare", "01BASE", "01CAND", "--collection", "dsh", "--record", "accept"]
    assert main([*args, "--proposal", "p-001", "--note", "ok"]) == 0
    assert "replayed p-001: recommendation accept" in capsys.readouterr().out
    assert meta(coll)["status"] == "accepted"
    text = (paths.wiki_dir("dsh") / "skill-impact.md").read_text()
    assert "## p-001: accept" in text and "- note: ok" in text


def test_an_unknown_proposal_is_an_error(repo_collection, capsys):
    assert main(["proposal", "show", "p-404", "--collection", "dsh"]) == 1
    assert "no proposal 'p-404'" in capsys.readouterr().err


def test_eval_proposal_needs_a_collection(tmp_path, capsys):
    suite = tmp_path / "s.yaml"
    suite.write_text(
        "suite: s\ntasks:\n  - id: a\n    prompt: hi\n    split: val\n    verifiers:\n"
        "      - { kind: regex, target: final_text, pattern: 'x' }\n"
    )
    assert main(["eval", "--suite", str(suite), "--models", "x/y", "--proposal", "p-1"]) == 2
    assert "--proposal needs --collection" in capsys.readouterr().err


def test_collection_mod_is_untouched_by_a_candidate(proposed, tmp_path):
    coll, _, _ = proposed
    gate.candidate_collection(coll, "p-001", tmp_path / "run")
    assert collection_mod.load("dsh").sources == coll.sources
