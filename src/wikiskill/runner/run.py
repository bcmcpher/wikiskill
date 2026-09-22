"""Driving a whole evaluation: preflight, then every unit, then the report.

The order is the point. A model is preflighted once, before any of its tasks run, so an endpoint
that cannot drive a skill costs one HTTP round trip rather than a suite's worth of wall time, and
produces one actionable message rather than a page of zeroes. Tasks whose `requires` are unmet are
skipped with the capability they wanted, and neither skips nor infrastructure failures are scored.

Nothing here runs in the calling agent's session: this module is reached through `wikiskill eval`,
which the harness command launches as its own process.
"""

from __future__ import annotations

import json
import os
import shutil
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .. import __version__, paths, rawlog
from ..collection import Collection, Role
from ..rubric import Rubric, RubricError
from ..rubric import load as load_rubric
from ..score import judge as judge_mod
from ..score import verify
from ..suite import Suite, Task
from .base import (
    INJECTED,
    OFF,
    ROUTED,
    Backend,
    PreflightResult,
    RunLayout,
    Trajectory,
    Unit,
    new_run_id,
    skipped,
    units_for,
)
from .preflight import Endpoint


@dataclass
class RunResult:
    """Everything a finished run produced, in memory as well as on disk."""

    layout: RunLayout
    suite: Suite
    models: list[str]
    conditions: list[str]
    preflight: dict[str, PreflightResult] = field(default_factory=dict)
    results: list[dict[str, Any]] = field(default_factory=list)
    events_written: int = 0
    #: Units run at once against one endpoint. Recorded because it changes what a wall time means.
    workers: int = 1

    @property
    def run_id(self) -> str:
        return self.layout.run_id

    def counts(self) -> dict[str, int]:
        tally: dict[str, int] = {}
        for result in self.results:
            tally[result["outcome"]] = tally.get(result["outcome"], 0) + 1
        return tally


@dataclass
class Panel:
    """The judge a run consults, and the rubrics it has already read.

    Built once per run: a rubric is read from disk, the judge's endpoint is resolved from the
    collection's `roles.judge`, and a judge that is also under test is refused before any unit runs
    rather than after the whole matrix has been graded by a model grading itself.
    """

    endpoint: Any
    model: str
    suite_root: Path
    models_under_test: tuple[str, ...]
    _cache: dict[str, Rubric | str] = field(default_factory=dict)

    def rubric(self, reference: str) -> Rubric | str:
        """The loaded rubric, or the reason it could not be loaded."""
        if reference not in self._cache:
            try:
                self._cache[reference] = load_rubric(self.suite_root / reference)
            except RubricError as exc:
                self._cache[reference] = "; ".join(exc.problems)
        return self._cache[reference]


def panel_for(
    collection: Collection | None, suite: Suite, models: list[str]
) -> tuple[Panel | None, str | None]:
    """The run's judge, or the reason it has none. A missing judge is stated, never assumed."""
    if not any(task.rubric for task in suite.tasks):
        return None, None
    if collection is None:
        return None, "no collection, so no `roles.judge` to grade with"
    role: Role | None = collection.roles.get("judge")
    if role is None:
        return None, f"collection {collection.name!r} declares no `roles.judge`"
    if not role.base_url:
        return None, "`roles.judge` has no `base_url`, so there is nothing to ask"

    key = os.environ.get(role.api_key_env) if role.api_key_env else None
    panel = Panel(
        endpoint=Endpoint(role.base_url, key),
        model=role.model,
        suite_root=suite.root,
        models_under_test=tuple(models),
    )
    judge_mod.refuse_self_judging(role.model, models)
    return panel, None


def missing_capabilities(task: Task) -> list[str]:
    """Required capabilities the environment does not provide.

    A capability is the name of a program the task needs on `PATH`. Anything more elaborate belongs
    to the task's own verifiers, not to a gate that decides whether it runs at all.
    """
    return [name for name in task.requires if shutil.which(name) is None]


def run_suite(
    suite: Suite,
    backend: Backend,
    *,
    collection: Collection | None,
    models: list[str],
    conditions: list[str] | None = None,
    tasks: list[Task] | None = None,
    layout: RunLayout | None = None,
    run_id: str | None = None,
    workers: int = 1,
    on_event=None,
) -> RunResult:
    """Run a suite and write `run.json`, `results.jsonl`, and the raw events, then return the run.

    `on_event` is called with a short progress line per unit, so a caller can report progress
    without this module knowing anything about how it prints.

    `workers` is a limit per endpoint, not per run, which is why it is applied inside a model rather
    than across the whole unit list: every unit of one model shares one endpoint, and the default of
    one is what Ollama serves. Models still run one after another, so an endpoint holding a single
    model in memory is never asked to hold two.
    """
    run_id = run_id or new_run_id()
    collection_name = collection.name if collection else suite.name
    where = layout if layout is not None else RunLayout.create(collection_name, run_id)
    conditions = list(conditions or [OFF, ROUTED])
    needs_collection = [name for name in (ROUTED, INJECTED) if name in conditions]
    if collection is None and needs_collection:
        raise ValueError(
            f"the {', '.join(name.upper() for name in needs_collection)} condition needs a "
            "collection; pass --collection or drop it"
        )

    report = on_event or (lambda _line: None)
    panel, no_judge = panel_for(collection, suite, models)
    started = time.time()
    run = RunResult(
        layout=where,
        suite=suite,
        models=list(models),
        conditions=conditions,
        workers=max(1, workers),
    )

    if no_judge:
        report(f"no rubric judge: {no_judge}")

    for model in models:
        report(f"preflight {model}")
        run.preflight[model] = backend.preflight(model)
        if not run.preflight[model].ok:
            report(f"  skipped: {run.preflight[model].reason}")

    raw_root = paths.raw_dir(collection_name)
    units = units_for(suite, run_id=run_id, models=models, conditions=conditions, tasks=tasks)

    # Recorded before anything runs, so a run that skipped every model still documents what the
    # model would have been given.
    proofs: dict[str, Any] = {}
    for condition in conditions:
        first = next((unit for unit in units if unit.condition == condition), None)
        if first is not None:
            report(f"isolation {condition}")
            proofs[condition] = _isolation_proof(backend, first)

    keeping = threading.Lock()

    def record(trajectory: Trajectory) -> None:
        # One lock for the whole hand-off: `results.jsonl` and the raw log are both append-only
        # files, and a half-written line is worse than a slow one.
        with keeping:
            result = trajectory.as_result()
            run.results.append(result)
            where.append_result(result)
            run.events_written += _write_events(backend, trajectory, raw_root)

    for model in models:
        mine = [unit for unit in units if unit.model == model]
        if not mine:
            continue
        lanes = max(1, min(run.workers, len(mine)))
        if lanes == 1:
            for unit in mine:
                record(_run_unit(unit, backend, run, report, panel=panel, no_judge=no_judge))
            continue
        report(f"{model}: {lanes} workers")
        with ThreadPoolExecutor(max_workers=lanes) as pool:
            # `map` yields in submission order, so `results.jsonl` reads the same however many
            # lanes ran: a report should not depend on which unit happened to finish first.
            for trajectory in pool.map(
                lambda u: _run_unit(u, backend, run, report, panel=panel, no_judge=no_judge),
                mine,
            ):
                record(trajectory)

    where.write_manifest(
        _manifest(
            run,
            backend=backend,
            collection=collection,
            proofs=proofs,
            duration_s=round(time.time() - started, 1),
        )
    )
    return run


def _run_unit(
    unit: Unit,
    backend: Backend,
    run: RunResult,
    report,
    *,
    panel: Panel | None = None,
    no_judge: str | None = None,
) -> Trajectory:
    preflight = run.preflight.get(unit.model)
    if preflight is not None and not preflight.ok:
        return skipped(unit, f"preflight failed for {unit.model}: {preflight.reason}")

    absent = missing_capabilities(unit.task)
    if absent:
        return skipped(unit, f"environment lacks {', '.join(absent)}")

    if unit.condition == INJECTED and not unit.task.expect:
        # INJECTED forces one component's text into context. A task that names no component has
        # nothing to force, and its INJECTED number would be a second OFF wearing a label.
        return skipped(unit, "INJECTED needs an expected skill or agent, and this task names none")

    report(f"{unit.condition:7} {unit.model}  {unit.task.id} (repeat {unit.repeat})")
    trajectory = backend.execute(unit)
    _verify(trajectory, report)
    _judge(trajectory, panel, no_judge, report)
    report(f"  {trajectory.outcome}" + (f": {trajectory.error}" if trajectory.error else ""))
    return trajectory


def _verify(trajectory: Trajectory, report) -> None:
    """Run the task's verifiers in the workdir the session left behind.

    Only a unit that actually ran is verified. An `infra_error` or a `skipped` unit produced no work
    to check, and checking it anyway would turn a harness failure into a model failure — the one
    thing the outcome classes exist to prevent.

    A verifier that cannot be carried out is itself infrastructure, so it demotes the unit rather
    than failing it: the model is not responsible for a check that never ran.
    """
    task = trajectory.unit.task
    if not trajectory.scored or not task.verifiers:
        return
    try:
        results, passed = verify.verify_task(
            task,
            workdir=trajectory.workdir,
            final_text=trajectory.final_text,
            transcript=trajectory.transcript,
        )
    except verify.VerifierError as exc:
        reason = f"verifier could not run: {exc}"
        trajectory.outcome = "infra_error"
        trajectory.error = str(exc)
        trajectory.reason = reason
        return

    trajectory.verifiers = [result.as_dict() for result in results]
    trajectory.passed = passed
    kept = sum(1 for result in results if result.passed)
    report(f"  verifiers {kept}/{len(results)} passed")


def _judge(trajectory: Trajectory, panel: Panel | None, no_judge: str | None, report) -> None:
    """Score the task's rubric, last and least authoritatively.

    A judge never touches `passed`. It runs after the verifiers so that its dimensions are read
    beside a pass rate that was already decided deterministically, and a judge that cannot be
    reached is recorded as an absent opinion rather than a failed unit — the model under test is not
    responsible for the grader being down.
    """
    reference = trajectory.unit.task.rubric
    if not reference or not trajectory.scored:
        return
    if panel is None:
        trajectory.rubric = {"rubric": reference, "error": no_judge or "no judge configured"}
        return

    rubric = panel.rubric(reference)
    if isinstance(rubric, str):
        trajectory.rubric = {"rubric": reference, "error": f"rubric did not load: {rubric}"}
        report(f"  rubric {reference}: did not load")
        return

    try:
        judgement = judge_mod.judge_task(
            rubric,
            endpoint=panel.endpoint,
            model=panel.model,
            final_text=trajectory.final_text,
            workdir=trajectory.workdir,
            models_under_test=panel.models_under_test,
        )
    except judge_mod.JudgeError as exc:
        trajectory.rubric = {"rubric": rubric.id, "error": str(exc)}
        report(f"  rubric {rubric.id}: {exc}")
        return

    trajectory.rubric = judgement.as_dict()
    scored = len(judgement.consensus)
    report(f"  rubric {rubric.id}: {scored}/{len(rubric.dimensions)} dimensions scored")


def _write_events(backend: Backend, trajectory: Trajectory, raw_root: Path) -> int:
    """Append a trajectory's events to the collection's raw log, grouped by root session."""
    if not trajectory.sessions:
        return 0
    events = backend.normalize(trajectory)
    written = 0
    for event in events:
        path = rawlog.session_log_path(raw_root, event["ts"], event["root_session_id"])
        rawlog.RawLogWriter(path).append(event)
        written += 1
    return written


def _isolation_proof(backend: Backend, unit: Unit) -> Any:
    prove = getattr(backend, "isolation_proof", None)
    return prove(unit) if callable(prove) else None


def _manifest(
    run: RunResult,
    *,
    backend: Backend,
    collection: Collection | None,
    proofs: dict[str, Any],
    duration_s: float,
) -> dict[str, Any]:
    """`run.json`: what ran, under what, and with which versions. Never an API key."""
    return {
        "run_id": run.run_id,
        "suite": run.suite.name,
        "suite_path": str(run.suite.path) if run.suite.path else None,
        "collection": collection.name if collection else None,
        "harness": backend.harness,
        "harness_version": backend.version(),
        "wikiskill_version": __version__,
        "models": run.models,
        "conditions": run.conditions,
        "tasks": [task.id for task in run.suite.tasks],
        "env": {task.id: dict(task.env) for task in run.suite.tasks if task.env},
        "components": _component_versions(collection),
        "preflight": {model: result.as_dict() for model, result in run.preflight.items()},
        "isolation": proofs,
        "workers": run.workers,
        "duration_s": duration_s,
        "outcomes": run.counts(),
        "events_written": run.events_written,
    }


def _component_versions(collection: Collection | None) -> list[dict[str, Any]]:
    """Every component under test, with the hash of the text that ran, so a result is repeatable."""
    if collection is None:
        return []
    return [
        {
            "kind": component.kind,
            "name": component.name,
            "source_hash": rawlog.file_hash(component.path),
        }
        for component in collection.watched()
    ]


def load_results(layout: RunLayout) -> list[dict[str, Any]]:
    """Read a finished run's results back, for scoring a run that was produced earlier."""
    return layout.read_results()


def load_manifest(layout: RunLayout) -> dict[str, Any]:
    if not layout.manifest.is_file():
        return {}
    return json.loads(layout.manifest.read_text(encoding="utf-8"))
