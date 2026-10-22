"""The run loop: what happens to a unit between `execute` and `results.jsonl`.

This is the one place in the suite with a test double. Everything else here reads recorded
fixtures, but `run_suite`'s job is orchestration — preflight, skips, verifiers, the result line —
and a recorded OpenCode session cannot exercise a backend that fails preflight or leaves a workdir
in a particular state. The fake stays deliberately dumb: it records what it was asked for and
returns what the test told it to.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path

import pytest

from conftest import write_manifest
from wikiskill import collection as collection_mod
from wikiskill import rawlog
from wikiskill import suite as suite_mod
from wikiskill.runner import run as run_mod
from wikiskill.runner.base import OFF, Backend, PreflightResult, RunLayout, Trajectory

SUITE = """
suite: toy
defaults: { repeats: 1 }
tasks:
  - id: control
    prompt: Rename the variable n to count.
    split: val
    verifiers:
      - { kind: file_exists, path: DONE.md }
"""


class FakeBackend(Backend):
    """A backend that runs nothing and leaves whatever the test asked it to leave behind."""

    harness = "fake"

    def __init__(self, layout: RunLayout, *, writes: str | None = None, ok: bool = True):
        self.layout = layout
        self.writes = writes
        self.ok = ok
        self.executed: list[str] = []

    def version(self) -> str:
        return "0.0.0-test"

    def preflight(self, model: str) -> PreflightResult:
        if self.ok:
            return PreflightResult(model=model, ok=True)
        return PreflightResult(model=model, ok=False, problems=("does not support tools",))

    def prepare(self, unit) -> Path:
        workdir = self.layout.unit_dir(unit) / "work"
        workdir.mkdir(parents=True, exist_ok=True)
        return workdir

    def execute(self, unit) -> Trajectory:
        self.executed.append(unit.task_id)
        workdir = self.prepare(unit)
        if self.writes:
            (workdir / self.writes).write_text("done\n", encoding="utf-8")
        return Trajectory(
            unit=unit, outcome="completed", workdir=workdir, final_text="finished", duration_ms=5
        )

    def normalize(self, trajectory) -> list[dict]:
        return []


@pytest.fixture
def suite(tmp_path):
    path = tmp_path / "suite.yaml"
    path.write_text(SUITE, encoding="utf-8")
    return suite_mod.load(path)


@pytest.fixture
def layout(tmp_path):
    return RunLayout.create("toy", "01JRUN", base=tmp_path / "evals")


def go(suite, backend, layout):
    return run_mod.run_suite(
        suite,
        backend,
        collection=None,
        models=["fake/model"],
        conditions=[OFF],
        layout=layout,
        run_id="01JRUN",
    )


def test_a_passing_verifier_reaches_the_result_line(xdg, suite, layout):
    run = go(suite, FakeBackend(layout, writes="DONE.md"), layout)
    (result,) = run.results

    assert result["outcome"] == "completed"
    assert result["passed"] is True
    assert result["verifiers"] == [
        {"kind": "file_exists", "passed": True, "detail": "DONE.md exists"}
    ]
    assert layout.read_results() == run.results, "and it is on disk, not only in memory"


def test_a_failing_verifier_is_a_failure_not_an_infrastructure_error(xdg, suite, layout):
    run = go(suite, FakeBackend(layout, writes=None), layout)
    (result,) = run.results

    assert result["outcome"] == "completed", "the session itself was fine"
    assert result["passed"] is False


def test_a_verifier_that_cannot_run_demotes_the_unit(xdg, suite, layout, monkeypatch):
    def refuse(*args, **kwargs):
        raise run_mod.verify.VerifierError("`check` timed out after 120s")

    monkeypatch.setattr(run_mod.verify, "verify_task", refuse)

    run = go(suite, FakeBackend(layout, writes="DONE.md"), layout)
    (result,) = run.results

    assert result["outcome"] == "infra_error"
    assert result["passed"] is None, "a check that never ran says nothing about the model"
    assert "timed out" in result["reason"]


def test_a_unit_that_never_ran_is_never_verified(xdg, suite, layout):
    backend = FakeBackend(layout, writes="DONE.md", ok=False)

    run = go(suite, backend, layout)
    (result,) = run.results

    assert backend.executed == [], "preflight failed, so nothing was executed"
    assert result["outcome"] == "skipped"
    assert result["passed"] is None
    assert result["verifiers"] == []


def test_a_task_without_verifiers_gets_no_verdict(xdg, tmp_path, layout):
    path = tmp_path / "routing.yaml"
    path.write_text(
        "suite: toy\ndefaults: { repeats: 1 }\ntasks:\n"
        "  - id: route-only\n    prompt: Set up recording.\n    split: val\n"
        "    expect: { skill: wikiskill-trace }\n",
        encoding="utf-8",
    )
    run = go(suite_mod.load(path), FakeBackend(layout), layout)
    (result,) = run.results

    assert result["passed"] is None
    assert result["verifiers"] == []


# --------------------------------------------------------------------------- workers


THREE = """
suite: toy
defaults: { repeats: 3 }
tasks:
  - id: control
    prompt: Rename the variable n to count.
    split: val
    verifiers:
      - { kind: file_exists, path: DONE.md }
"""


class CountingBackend(FakeBackend):
    """Records how many units were in flight at once, and in what order they finished."""

    def __init__(self, layout: RunLayout, **kwargs):
        super().__init__(layout, **kwargs)
        self.inside = 0
        self.peak = 0
        self.lock = threading.Lock()

    def execute(self, unit) -> Trajectory:
        with self.lock:
            self.inside += 1
            self.peak = max(self.peak, self.inside)
        try:
            time.sleep(0.05)
            return super().execute(unit)
        finally:
            with self.lock:
                self.inside -= 1


@pytest.fixture
def three(tmp_path):
    path = tmp_path / "three.yaml"
    path.write_text(THREE, encoding="utf-8")
    return suite_mod.load(path)


def test_one_worker_by_default(xdg, three, layout):
    backend = CountingBackend(layout, writes="DONE.md")

    go(three, backend, layout)

    assert backend.peak == 1, "an endpoint serving one request at a time is the default"


def test_workers_run_units_of_one_model_at_once(xdg, three, layout):
    backend = CountingBackend(layout, writes="DONE.md")

    run = run_mod.run_suite(
        three,
        backend,
        collection=None,
        models=["fake/model"],
        conditions=[OFF],
        layout=layout,
        run_id="01JRUN",
        workers=3,
    )

    assert backend.peak > 1
    assert len(run.results) == 3
    assert [result["repeat"] for result in run.results] == [0, 1, 2], (
        "results keep submission order however the lanes finished"
    )
    assert run.results == layout.read_results(), "and the file is not interleaved"


def test_the_manifest_records_how_many_lanes_ran(xdg, three, layout):
    run = run_mod.run_suite(
        three,
        CountingBackend(layout, writes="DONE.md"),
        collection=None,
        models=["fake/model"],
        conditions=[OFF],
        layout=layout,
        run_id="01JRUN",
        workers=2,
    )

    assert run_mod.load_manifest(run.layout)["workers"] == 2


def test_a_backend_without_options_or_proofs_records_the_defaults(xdg, three, layout):
    run = run_mod.run_suite(
        three,
        CountingBackend(layout, writes="DONE.md"),
        collection=None,
        models=["fake/model"],
        conditions=[OFF],
        layout=layout,
        run_id="01JRUN",
    )

    manifest = run_mod.load_manifest(run.layout)
    assert manifest["options"] == {}
    assert manifest["isolation"] == {OFF: None}


def test_the_manifest_records_the_suite_hash(xdg, tmp_path, layout):
    path = tmp_path / "three.yaml"
    path.write_text(THREE, encoding="utf-8")
    run = run_mod.run_suite(
        suite_mod.load(path),
        CountingBackend(layout, writes="DONE.md"),
        collection=None,
        models=["fake/model"],
        conditions=[OFF],
        layout=layout,
        run_id="01JRUN",
    )

    assert run_mod.load_manifest(run.layout)["suite_hash"] == rawlog.content_hash(path.read_bytes())


def test_eval_repeats_overrides_the_suites_and_keeps_its_hash(xdg, tmp_path, monkeypatch):
    from wikiskill.cli import eval as eval_cli
    from wikiskill.cli import main

    path = tmp_path / "suite.yaml"
    path.write_text(SUITE, encoding="utf-8")
    made: list[FakeBackend] = []

    def fake(args, coll, endpoint, layout, root, *, withheld=()):
        made.append(FakeBackend(layout, writes="DONE.md"))
        return made[0]

    monkeypatch.setattr(eval_cli, "_eval_backend", fake)
    code = main(
        [
            "eval",
            "--suite",
            str(path),
            "--models",
            "fake/model",
            "--condition",
            "off",
            "--repeats",
            "3",
        ]
    )

    assert code == 0
    (backend,) = made
    manifest = run_mod.load_manifest(backend.layout)
    assert sorted(backend.executed) == ["control"] * 3, "the suite says 1; the flag says 3"
    assert manifest["repeats"] == {"control": 3}
    assert manifest["suite_hash"] == rawlog.content_hash(path.read_bytes())


def test_eval_refuses_fewer_than_one_repeat(xdg, tmp_path, capsys):
    from wikiskill.cli import main

    path = tmp_path / "suite.yaml"
    path.write_text(SUITE, encoding="utf-8")

    assert main(["eval", "--suite", str(path), "--models", "fake/model", "--repeats", "0"]) == 2
    assert "--repeats must be at least 1" in capsys.readouterr().err


# --------------------------------------------------------------------------- injected


MANIFEST = """
name = "toy"
sources = [{{ path = "{source}", layout = "opencode" }}]

[watch]
skills = ["*"]
agents = ["*"]
commands = []
"""


@pytest.fixture
def collection(xdg, opencode_source):
    write_manifest(xdg, "toy", MANIFEST.format(source=opencode_source))
    return collection_mod.load("toy")


def test_injected_skips_a_task_that_names_no_component(xdg, suite, layout, collection):
    """The toy control task is judged by a verifier alone, so there is nothing to inject."""
    run = run_mod.run_suite(
        suite,
        FakeBackend(layout, writes="DONE.md"),
        collection=collection,
        models=["fake/model"],
        conditions=[run_mod.INJECTED],
        layout=layout,
        run_id="01JRUN",
    )
    (result,) = run.results

    assert result["outcome"] == "skipped"
    assert "names none" in result["reason"]


def test_injected_without_a_collection_is_refused_by_name(xdg, suite, layout):
    with pytest.raises(ValueError) as caught:
        run_mod.run_suite(
            suite,
            FakeBackend(layout),
            collection=None,
            models=["fake/model"],
            conditions=[run_mod.INJECTED],
            layout=layout,
            run_id="01JRUN",
        )

    assert "INJECTED condition needs a collection" in str(caught.value)


def test_the_manifest_records_each_tasks_env(xdg, tmp_path, layout):
    path = tmp_path / "env.yaml"
    path.write_text(
        THREE.replace("defaults: { repeats: 3 }", 'defaults: { repeats: 1, env: { A: "1" } }'),
        encoding="utf-8",
    )
    run = run_mod.run_suite(
        suite_mod.load(path),
        CountingBackend(layout, writes="DONE.md"),
        collection=None,
        models=["fake/model"],
        conditions=[OFF],
        layout=layout,
        run_id="01JRUN",
    )

    assert run_mod.load_manifest(run.layout)["env"] == {"control": {"A": "1"}}


def test_a_requirement_is_looked_up_on_the_tasks_own_path(tmp_path, monkeypatch):
    tool = tmp_path / "venv" / "bin" / "sometool"
    tool.parent.mkdir(parents=True)
    tool.write_text("#!/bin/sh\n", encoding="utf-8")
    tool.chmod(0o755)
    monkeypatch.setenv("PATH", "/usr/bin:/bin")
    bare = suite_mod.Task(id="t", prompt="p", split="val", requires=("sometool",))
    scoped = suite_mod.Task(
        id="t",
        prompt="p",
        split="val",
        requires=("sometool",),
        env=(("PATH", f"{tool.parent}:$PATH"),),
    )

    assert run_mod.missing_capabilities(bare) == ["sometool"]
    assert run_mod.missing_capabilities(scoped) == []


def test_the_requires_check_does_not_see_a_secret(tmp_path, monkeypatch):
    tool = tmp_path / "bin" / "sometool"
    tool.parent.mkdir(parents=True)
    tool.write_text("#!/bin/sh\n", encoding="utf-8")
    tool.chmod(0o755)
    monkeypatch.setenv("PATH", str(tool.parent))
    task = suite_mod.Task(id="t", prompt="p", split="val", requires=("sometool",))

    assert run_mod.missing_capabilities(task) == []
    # Contrived, but it is the one variable the check reads: withheld, it is not consulted.
    withheld = suite_mod.Task(
        id="t", prompt="p", split="val", requires=("sometool",), secrets=("PATH",)
    )
    assert run_mod.missing_capabilities(withheld) == ["sometool"]


# --------------------------------------------------------------------------- secrets

#: Not a credential: a fake value only these tests set.
FAKE_SECRET = "fake-grader-value-0123456789"

SECRET_SUITE = """
suite: graded
defaults: { repeats: 1, secrets: [FAKE_GRADER_TOKEN] }
tasks:
  - id: echoes
    prompt: Rename the variable n to count.
    split: val
    verifiers:
      - { kind: command, run: 'echo "token is $FAKE_GRADER_TOKEN"' }
"""


@pytest.fixture
def secret_suite(tmp_path):
    path = tmp_path / "graded.yaml"
    path.write_text(SECRET_SUITE, encoding="utf-8")
    return suite_mod.load(path)


def files_holding(root: Path, value: str) -> list[Path]:
    return [
        path
        for path in root.rglob("*")
        if path.is_file() and value in path.read_text(encoding="utf-8", errors="replace")
    ]


def test_a_missing_secret_refuses_the_run_before_any_unit(xdg, secret_suite, layout, monkeypatch):
    monkeypatch.delenv("FAKE_GRADER_TOKEN", raising=False)
    backend = FakeBackend(layout)

    with pytest.raises(ValueError, match="not set on this host: FAKE_GRADER_TOKEN"):
        go(secret_suite, backend, layout)

    assert backend.executed == []
    assert list(layout.root.iterdir()) == [], "no unit directory, and no run.json"


def test_a_secret_too_short_to_redact_is_refused(xdg, secret_suite, layout, monkeypatch):
    monkeypatch.setenv("FAKE_GRADER_TOKEN", "short")

    with pytest.raises(ValueError, match=r"shorter than 8 characters.*FAKE_GRADER_TOKEN"):
        go(secret_suite, FakeBackend(layout), layout)


def test_eval_names_a_missing_secret_and_makes_no_run_directory(xdg, tmp_path, monkeypatch, capsys):
    from wikiskill.cli import main

    monkeypatch.delenv("FAKE_GRADER_TOKEN", raising=False)
    path = tmp_path / "graded.yaml"
    path.write_text(SECRET_SUITE, encoding="utf-8")

    code = main(["eval", "--suite", str(path), "--models", "fake/model", "--condition", "off"])

    assert code != 0
    assert "FAKE_GRADER_TOKEN" in capsys.readouterr().err
    assert not any(xdg["data"].rglob("evals")), "refused before a run directory exists"


def test_run_json_names_the_secrets_and_no_file_holds_a_value(
    xdg, secret_suite, layout, monkeypatch
):
    monkeypatch.setenv("FAKE_GRADER_TOKEN", FAKE_SECRET)

    run = go(secret_suite, FakeBackend(layout), layout)

    (result,) = run.results
    assert result["passed"] is True
    assert result["verifiers"][0]["output"] == "token is [REDACTED:env_value]"
    assert run_mod.load_manifest(layout)["secrets"] == {"echoes": ["FAKE_GRADER_TOKEN"]}
    assert files_holding(layout.root, FAKE_SECRET) == []
    assert files_holding(xdg["data"], FAKE_SECRET) == [], "nor the raw event log"


def test_a_run_without_secrets_records_none(xdg, suite, layout):
    go(suite, FakeBackend(layout, writes="DONE.md"), layout)
    assert run_mod.load_manifest(layout)["secrets"] == {}
