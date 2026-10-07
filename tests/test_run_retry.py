"""Repairing units the harness lost: `eval --retries` inside a run, and `eval --fill` after one.

The backend is scripted, as in `test_run.py`: each call to `execute` takes the next ending from a
list, so a test can say "crash, then complete" and check what the run kept of both.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from wikiskill import suite as suite_mod
from wikiskill.runner import run as run_mod
from wikiskill.runner.base import OFF, Backend, PreflightResult, RunLayout, Trajectory

SUITE = """
suite: toy
defaults: { repeats: 2 }
tasks:
  - id: control
    prompt: Rename the variable n to count.
    split: val
    verifiers:
      - { kind: file_exists, path: DONE.md }
"""


class ScriptedBackend(Backend):
    """Ends each unit as the script says: `ok`, `fail`, `crash` (transient) or `timeout`."""

    harness = "fake"

    def __init__(self, layout: RunLayout, script: list[str], *, version: str = "0.0.0-test"):
        self.layout = layout
        self.script = list(script)
        self._version = version
        self.executed: list[str] = []

    def version(self) -> str:
        return self._version

    def preflight(self, model: str) -> PreflightResult:
        return PreflightResult(model=model, ok=True)

    def prepare(self, unit) -> Path:
        workdir = self.layout.unit_dir(unit) / "work"
        workdir.mkdir(parents=True, exist_ok=True)
        return workdir

    def execute(self, unit) -> Trajectory:
        ending = self.script.pop(0)
        self.executed.append(f"{unit.slug}:{ending}")
        workdir = self.prepare(unit)
        if ending == "crash":
            return Trajectory(
                unit=unit,
                outcome="infra_error",
                error="opencode produced no session (exit -5)",
                reason="opencode produced no session (exit -5)",
                duration_ms=7,
                workdir=workdir,
                transient=True,
            )
        if ending == "timeout":
            return Trajectory(
                unit=unit, outcome="infra_error", error="timed out after 600s", workdir=workdir
            )
        if ending == "ok":
            (workdir / "DONE.md").write_text("done\n", encoding="utf-8")
        return Trajectory(unit=unit, outcome="completed", workdir=workdir, duration_ms=5)

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


def go(suite, backend, layout, *, retries=1):
    return run_mod.run_suite(
        suite,
        backend,
        collection=None,
        models=["fake/model"],
        conditions=[OFF],
        layout=layout,
        run_id="01JRUN",
        retries=retries,
    )


def fill(suite, backend, layout, *, retries=1):
    manifest = run_mod.load_manifest(layout)
    assert run_mod.fill_refusal(manifest, suite, backend, None) is None
    return run_mod.fill_run(
        suite, backend, collection=None, layout=layout, manifest=manifest, retries=retries
    )


# --------------------------------------------------------------------------- retries


def test_a_crashed_unit_runs_again_and_keeps_its_first_attempt(xdg, suite, layout):
    backend = ScriptedBackend(layout, ["crash", "ok", "ok"])

    run = go(suite, backend, layout)
    first, second = run.results

    assert first["outcome"] == "completed"
    assert first["passed"] is True
    assert first["attempts"] == 2
    (earlier,) = first["retried"]
    assert earlier["outcome"] == "infra_error"
    assert "no session" in earlier["error"]
    assert (layout.root / earlier["kept"]).is_dir(), "the crashed attempt's files are kept"
    assert "attempts" not in second, "a unit that ran once reads as it always did"
    assert run_mod.load_manifest(layout)["retries"] == 1


def test_a_unit_that_crashes_on_every_attempt_stays_an_infrastructure_error(xdg, suite, layout):
    backend = ScriptedBackend(layout, ["crash", "crash", "ok"])

    first, _ = go(suite, backend, layout).results

    assert first["outcome"] == "infra_error"
    assert first["transient"] is True
    assert first["attempts"] == 2
    assert len(backend.executed) == 3, "one retry, then the next unit"


@pytest.mark.parametrize("ending", ["timeout", "fail"])
def test_a_timeout_or_a_failure_is_never_run_again(xdg, suite, layout, ending):
    backend = ScriptedBackend(layout, [ending, "ok"])

    first, _ = go(suite, backend, layout).results

    assert len(backend.executed) == 2
    assert "attempts" not in first
    assert "transient" not in first


def test_no_retries_runs_every_unit_once(xdg, suite, layout):
    backend = ScriptedBackend(layout, ["crash", "ok"])

    first, _ = go(suite, backend, layout, retries=0).results

    assert first["outcome"] == "infra_error"
    assert len(backend.executed) == 2


# --------------------------------------------------------------------------- fill


def test_fill_reruns_only_the_unscored_unit_and_keeps_what_it_replaced(xdg, suite, layout):
    go(suite, ScriptedBackend(layout, ["crash", "fail"]), layout, retries=0)
    before = layout.read_results()

    backend = ScriptedBackend(layout, ["ok"])
    run, filled = fill(suite, backend, layout)
    after = layout.read_results()

    assert filled == ["control__fake_model__off__r0"]
    assert backend.executed == ["control__fake_model__off__r0:ok"], "the failed unit is not rerun"
    assert len(after) == 2, "still one line per unit"
    assert after[0]["outcome"] == "completed"
    assert after[0]["attempts"] == 2
    assert after[0]["retried"][0]["outcome"] == "infra_error"
    assert after[1] == before[1], "the scored unit is untouched"
    assert run.results == after

    (superseded,) = [json.loads(line) for line in layout.superseded.read_text().splitlines()]
    assert superseded["outcome"] == "infra_error"
    assert "superseded_at" in superseded

    manifest = run_mod.load_manifest(layout)
    (entry,) = manifest["fills"]
    assert entry["units"] == filled
    assert entry["outcomes"] == {"before": {"infra_error": 1}, "after": {"completed": 1}}
    assert manifest["outcomes"] == {"completed": 2}


def test_fill_with_nothing_to_fill_writes_nothing(xdg, suite, layout):
    go(suite, ScriptedBackend(layout, ["ok", "fail"]), layout)
    before = layout.results.read_text()

    _, filled = fill(suite, ScriptedBackend(layout, []), layout)

    assert filled == []
    assert layout.results.read_text() == before
    assert not layout.superseded.exists()
    assert "fills" not in run_mod.load_manifest(layout)


def test_a_unit_still_lost_after_a_fill_says_so(xdg, suite, layout):
    go(suite, ScriptedBackend(layout, ["crash", "ok"]), layout, retries=0)

    fill(suite, ScriptedBackend(layout, ["crash", "crash"]), layout)
    (first, _) = layout.read_results()

    assert first["outcome"] == "infra_error"
    assert first["attempts"] == 3, "the run's attempt, then the fill's two"


def test_fill_is_refused_once_the_suite_has_changed(xdg, suite, layout):
    go(suite, ScriptedBackend(layout, ["crash", "ok"]), layout, retries=0)
    suite.path.write_text(SUITE.replace("count", "total"), encoding="utf-8")
    edited = suite_mod.load(suite.path)

    problem = run_mod.fill_refusal(
        run_mod.load_manifest(layout), edited, ScriptedBackend(layout, []), None
    )

    assert problem is not None
    assert "01JRUN ran sha256:" in problem


def test_fill_is_refused_under_another_harness_version(xdg, suite, layout):
    go(suite, ScriptedBackend(layout, ["crash", "ok"]), layout, retries=0)

    problem = run_mod.fill_refusal(
        run_mod.load_manifest(layout), suite, ScriptedBackend(layout, [], version="0.0.1"), None
    )

    assert problem == "01JRUN ran under fake 0.0.0-test; fake 0.0.1 is here"


def test_a_run_without_its_manifest_cannot_be_filled():
    assert "no run.json" in (run_mod.unfillable({}) or "")
    assert "preflight-only" in (run_mod.unfillable({"preflight_only": True}) or "")
