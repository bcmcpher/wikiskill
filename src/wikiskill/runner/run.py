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
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .. import __version__, paths, rawlog, sources
from ..collection import Collection, Role
from ..rubric import Rubric, RubricError
from ..rubric import load as load_rubric
from ..score import judge as judge_mod
from ..score import verify
from ..suite import Suite, Task
from .base import (
    INFRA_OUTCOMES,
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

#: One rerun of a unit the harness lost. A second crash on the same unit is more likely the unit
#: than chance, and is better reported than retried.
DEFAULT_RETRIES = 1


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
    #: What went wrong around the run without touching its results, such as a snapshot not kept.
    warnings: list[str] = field(default_factory=list)
    #: Each watched component and the hash of its text, read before the first unit runs.
    components: list[dict[str, Any]] = field(default_factory=list)
    #: How many times a unit that crashed the harness is run again (`eval --retries`).
    retries: int = DEFAULT_RETRIES

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
    #: the judge model, or every model of a panel
    models: tuple[str, ...]
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
    collection: Collection | None,
    suite: Suite,
    models: list[str],
    tasks: list[Task] | None = None,
) -> tuple[Panel | None, str | None]:
    """The run's judge, or the reason it has none. A missing judge is stated, never assumed.

    Only the tasks the run will run are checked: a rubric on a task left out never asks the panel.
    """
    chosen = suite.tasks if tasks is None else tasks
    if not any(task.rubric for task in chosen):
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
        models=role.panel,
        suite_root=suite.root,
        models_under_test=tuple(models),
    )
    for member in role.panel:
        judge_mod.refuse_self_judging(member, models)
    # A rubric whose judges the panel cannot fill is refused now, not after every unit has run.
    for reference in sorted({task.rubric for task in chosen if task.rubric}):
        rubric = panel.rubric(reference)
        if not isinstance(rubric, str):
            judge_mod.panel_slots(rubric.judges, role.panel)
    return panel, None


def missing_capabilities(task: Task) -> list[str]:
    """Required capabilities the environment does not provide.

    A capability is the name of a program the task needs on `PATH` — the task's own `PATH` when its
    `env` sets one. Anything more elaborate belongs to the task's own verifiers, not to a gate that
    decides whether it runs at all.
    """
    path = task.resolved_env().get("PATH")
    return [name for name in task.requires if shutil.which(name, path=path) is None]


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
    proposal: str | None = None,
    retries: int = DEFAULT_RETRIES,
) -> RunResult:
    """Run a suite and write `run.json`, `results.jsonl`, and the raw events, then return the run.

    `on_event` is called with a short progress line per unit, so a caller can report progress
    without this module knowing anything about how it prints.

    `workers` is a limit per endpoint, not per run, which is why it is applied inside a model rather
    than across the whole unit list: every unit of one model shares one endpoint, and the default of
    one is what Ollama serves. Models still run one after another, so an endpoint holding a single
    model in memory is never asked to hold two.

    `proposal` names the refinement proposal whose candidate the collection carries, for `run.json`.

    `retries` is how many times a unit is run again when the harness lost it
    (`Trajectory.transient`); no other outcome is ever rerun.
    """
    run_id = run_id or new_run_id()
    collection_name = collection.name if collection else suite.name
    # A judge panel that cannot grade the run refuses it before a run directory exists.
    panel, no_judge = panel_for(collection, suite, models, tasks)
    where = layout if layout is not None else RunLayout.create(collection_name, run_id)
    conditions = list(conditions or [OFF, ROUTED])
    needs_collection = [name for name in (ROUTED, INJECTED) if name in conditions]
    if collection is None and needs_collection:
        raise ValueError(
            f"the {', '.join(name.upper() for name in needs_collection)} condition needs a "
            "collection; pass --collection or drop it"
        )

    report = on_event or (lambda _line: None)
    started = time.time()
    run = RunResult(
        layout=where,
        suite=suite,
        models=list(models),
        conditions=conditions,
        workers=max(1, workers),
        retries=max(0, retries),
    )

    if no_judge:
        report(f"no rubric judge: {no_judge}")

    # Read before any unit runs, so the recorded version is the text that ran, even if the file is
    # edited while the run is under way.
    run.components = _component_versions(collection, run.warnings)

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
            proofs[condition] = backend.isolation_proof(first)

    keeping = threading.Lock()

    def record(trajectory: Trajectory) -> None:
        # One lock for the whole hand-off: `results.jsonl` and the raw log are both append-only
        # files, and a half-written line is worse than a slow one.
        with keeping:
            result = trajectory.as_result()
            run.results.append(result)
            where.append_result(result)
            run.events_written += _write_events(backend, trajectory, raw_root)
            trajectory.events = None

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
            proposal=proposal,
        )
    )
    for warning in run.warnings:
        report(f"warning: {warning}")
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
    trajectory = _execute(unit, backend, run, report)
    _verify(trajectory, report)
    _judge(trajectory, panel, no_judge, report, backend)
    report(f"  {trajectory.outcome}" + (f": {trajectory.error}" if trajectory.error else ""))
    return trajectory


def _execute(unit: Unit, backend: Backend, run: RunResult, report) -> Trajectory:
    """Execute a unit, and again, up to `run.retries` times, while the harness loses it.

    Only an `infra_error` the backend marked transient is rerun: a crash, a failed launch, a session
    that could not be read back. A timeout would usually time out again, and a unit that ran is
    never rerun, pass or fail — rerunning failures until they pass would inflate every rate. Each
    earlier attempt's directory is moved aside and kept, and its error recorded on the result.
    """
    earlier: list[dict[str, Any]] = []
    while True:
        trajectory = backend.execute(unit)
        lost = trajectory.outcome == "infra_error" and trajectory.transient
        if not lost or len(earlier) >= run.retries:
            break
        aside = run.layout.attempt_dir(unit)
        earlier.append(_attempt(trajectory.as_result(), aside, run.layout))
        report(f"  infra_error, running it again: {trajectory.error}")
    trajectory.attempts = len(earlier) + 1
    trajectory.retried = earlier
    return trajectory


def _attempt(result: dict[str, Any], aside: Path | None, layout: RunLayout) -> dict[str, Any]:
    """What an earlier attempt left on the record: how it ended, and where its files are."""
    return {
        "outcome": result.get("outcome"),
        "error": result.get("error") or result.get("reason"),
        "duration_ms": result.get("duration_ms"),
        "kept": str(aside.relative_to(layout.root)) if aside is not None else None,
    }


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


def _judge(
    trajectory: Trajectory,
    panel: Panel | None,
    no_judge: str | None,
    report,
    backend: Backend | None = None,
) -> None:
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

    handoffs = None
    if "delegations" in rubric.shows:
        # Judging a handoff without the handoff would score missing evidence as no delegation.
        events, problem = _events(backend, trajectory)
        if events is None:
            trajectory.rubric = {
                "rubric": rubric.id,
                "error": f"the rubric shows delegations, but {problem}",
            }
            report(f"  rubric {rubric.id}: delegations unknown, not judged")
            return
        handoffs = judge_mod.delegations(events)
    try:
        judgement = judge_mod.judge_task(
            rubric,
            endpoint=panel.endpoint,
            model=panel.models,
            handoffs=handoffs,
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


def _events(
    backend: Backend | None, trajectory: Trajectory
) -> tuple[list[dict[str, Any]] | None, str | None]:
    """A unit's normalized events, made once and kept for the raw log, or why there are none."""
    if trajectory.events is not None:
        return trajectory.events, None
    if backend is None:
        return None, "no harness was given to read the unit's sessions"
    if not trajectory.sessions:
        return None, "the unit's sessions were not captured"
    try:
        trajectory.events = backend.normalize(trajectory)
    except Exception as exc:
        return None, f"the unit's sessions could not be read: {exc}"
    return trajectory.events, None


def _write_events(backend: Backend, trajectory: Trajectory, raw_root: Path) -> int:
    """Append a trajectory's events to the collection's raw log, grouped by root session."""
    if not trajectory.sessions:
        return 0
    events = trajectory.events if trajectory.events is not None else backend.normalize(trajectory)
    written = 0
    for event in events:
        path = rawlog.session_log_path(raw_root, event["ts"], event["root_session_id"])
        rawlog.RawLogWriter(path).append(event)
        written += 1
    return written


def _manifest(
    run: RunResult,
    *,
    backend: Backend,
    collection: Collection | None,
    proofs: dict[str, Any],
    duration_s: float,
    proposal: str | None = None,
) -> dict[str, Any]:
    """`run.json`: what ran, under what, and with which versions. Never an API key."""
    return {
        "run_id": run.run_id,
        "suite": run.suite.name,
        "suite_path": str(run.suite.path) if run.suite.path else None,
        # The suite file only: verifiers, setup and prompts. Fixtures and rubrics it names are not
        # folded in.
        "suite_hash": rawlog.content_hash(run.suite.path.read_bytes()) if run.suite.path else None,
        "collection": collection.name if collection else None,
        "harness": backend.harness,
        "harness_version": backend.version(),
        "wikiskill_version": __version__,
        "models": run.models,
        "conditions": run.conditions,
        "tasks": [task.id for task in run.suite.tasks],
        # As run: `eval --repeats` changes these without changing the suite file or its hash.
        "repeats": {task.id: task.repeats for task in run.suite.tasks},
        "env": {task.id: dict(task.env) for task in run.suite.tasks if task.env},
        "setup": {task.id: list(task.setup) for task in run.suite.tasks if task.setup},
        "components": run.components,
        # A candidate run evaluates a proposal from a copy of its source; a baseline names none.
        "proposal": proposal,
        "preflight": {model: result.as_dict() for model, result in run.preflight.items()},
        "isolation": proofs,
        # A model's output cap and thinking setting change what it does as much as its weights do.
        "options": backend.run_options(),
        "workers": run.workers,
        "retries": run.retries,
        "duration_s": duration_s,
        "outcomes": run.counts(),
        "events_written": run.events_written,
        "warnings": run.warnings,
    }


def _component_versions(
    collection: Collection | None, warnings: list[str] | None = None
) -> list[dict[str, Any]]:
    """Every component under test, with the hash of the text that ran, so a result is repeatable.

    The text itself is kept as a source snapshot, so the version can be shown after the file moves
    on. A snapshot that cannot be stored is a warning: the run's results do not depend on it.
    """
    if collection is None:
        return []
    found = []
    for component in collection.watched():
        data = rawlog.read_bytes(component.path)
        if data is not None:
            try:
                sources.store(collection.name, data)
            except sources.SnapshotError as exc:
                if warnings is not None and str(exc) not in warnings:
                    warnings.append(str(exc))
        found.append(
            {
                "kind": component.kind,
                "name": component.name,
                "source_hash": rawlog.content_hash(data) if data is not None else None,
            }
        )
    return found


def load_manifest(layout: RunLayout) -> dict[str, Any]:
    if not layout.manifest.is_file():
        return {}
    return json.loads(layout.manifest.read_text(encoding="utf-8"))


# --------------------------------------------------------------------------- fill


def unfilled(results: list[dict[str, Any]]) -> list[int]:
    """Where in `results.jsonl` the units without a score are: `infra_error` and `skipped`."""
    return [i for i, result in enumerate(results) if result.get("outcome") in INFRA_OUTCOMES]


def fill_refusal(
    manifest: dict[str, Any],
    suite: Suite,
    backend: Backend,
    collection: Collection | None,
) -> str | None:
    """Why a run cannot be filled with what is installed now, or None when it can.

    A filled unit has to be the unit the run would have produced: the same suite file, harness,
    component text and model options. Anything else would make one run of two experiments.
    """
    return unfillable(manifest) or _changed_since(manifest, suite, backend, collection)


def unfillable(manifest: dict[str, Any]) -> str | None:
    """Why a run's own record rules out a fill, before anything is loaded for it."""
    if not manifest:
        return (
            "the run has no run.json, which is written when a run ends; a run killed before then "
            "cannot be filled"
        )
    if manifest.get("preflight_only"):
        return "the run was --preflight-only and has no units"
    if not manifest.get("suite_path"):
        return "the run's run.json names no suite file"
    return None


def _changed_since(
    manifest: dict[str, Any],
    suite: Suite,
    backend: Backend,
    collection: Collection | None,
) -> str | None:
    """The first thing that differs between the run as recorded and what would run now."""
    run_id = manifest.get("run_id")
    current = rawlog.content_hash(suite.path.read_bytes()) if suite.path else None
    recorded = manifest.get("harness"), manifest.get("harness_version")
    installed = backend.harness, backend.version()
    before = {
        (c["kind"], c["name"]): c.get("source_hash") for c in manifest.get("components") or []
    }
    now = {(c["kind"], c["name"]): c.get("source_hash") for c in _component_versions(collection)}
    components = sorted(
        f"{kind} {name}"
        for kind, name in before.keys() | now.keys()
        if before.get((kind, name)) != now.get((kind, name))
    )
    options, wanted = manifest.get("options") or {}, backend.run_options()
    differ = sorted(k for k in options.keys() | wanted.keys() if options.get(k) != wanted.get(k))
    problems = [
        (
            current != manifest.get("suite_hash"),
            f"{suite.path} is {current} now, but {run_id} ran {manifest.get('suite_hash')}",
        ),
        (
            recorded != installed,
            f"{run_id} ran under {' '.join(map(str, recorded))}; {' '.join(installed)} is here",
        ),
        (bool(components), f"changed since {run_id}: {', '.join(components)}"),
        (bool(differ), f"run options differ from {run_id}'s: {', '.join(differ)}"),
    ]
    return next((message for failed, message in problems if failed), None)


def fill_run(
    suite: Suite,
    backend: Backend,
    *,
    collection: Collection | None,
    layout: RunLayout,
    manifest: dict[str, Any],
    retries: int = DEFAULT_RETRIES,
    on_event=None,
) -> tuple[RunResult, list[str]]:
    """Run again every unit of a finished run that has no score, and write them into that run.

    The caller checks `fill_refusal` first. Units run one at a time, in the order of
    `results.jsonl`, under the run's own models for the judge panel's sake. `results.jsonl` keeps
    one line per unit in its order; each line replaced goes to `results.superseded.jsonl`, and the
    fill is listed in `run.json` under `fills`. A unit that is still unscored afterwards keeps its
    new line, so a fill never makes a run look more complete than it is.

    Returns the run, with every result, and the slugs of the units it ran.
    """
    report = on_event or (lambda _line: None)
    started = time.time()
    results = layout.read_results()
    run = RunResult(
        layout=layout,
        suite=suite,
        models=list(manifest.get("models") or []),
        conditions=list(manifest.get("conditions") or []),
        workers=1,
        retries=max(0, retries),
        results=results,
    )
    todo = unfilled(results)
    if not todo:
        return run, []

    tasks = {task.id: task for task in suite.tasks}
    missing = sorted({results[i]["task_id"] for i in todo} - tasks.keys())
    if missing:
        raise ValueError(f"no such task(s) in {suite.name}: {', '.join(missing)}")
    units = [
        Unit(
            run_id=layout.run_id,
            suite=suite.name,
            task=tasks[results[i]["task_id"]],
            model=results[i]["model"],
            condition=results[i]["condition"],
            repeat=results[i]["repeat"],
        )
        for i in todo
    ]
    needed = list(dict.fromkeys(unit.task for unit in units))
    panel, no_judge = panel_for(collection, suite, run.models, needed)
    if no_judge:
        report(f"no rubric judge: {no_judge}")
    for model in dict.fromkeys(unit.model for unit in units):
        report(f"preflight {model}")
        run.preflight[model] = backend.preflight(model)
        if not run.preflight[model].ok:
            report(f"  skipped: {run.preflight[model].reason}")

    raw_root = paths.raw_dir(manifest.get("collection") or suite.name)
    at = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    superseded = []
    for i, unit in zip(todo, units, strict=True):
        prior = results[i]
        aside = layout.attempt_dir(unit)
        trajectory = _run_unit(unit, backend, run, report, panel=panel, no_judge=no_judge)
        trajectory.retried = [
            *(prior.get("retried") or []),
            _attempt(prior, aside, layout),
            *trajectory.retried,
        ]
        trajectory.attempts = int(prior.get("attempts") or 1) + trajectory.attempts
        results[i] = trajectory.as_result()
        superseded.append({**prior, "superseded_at": at})
        run.events_written += _write_events(backend, trajectory, raw_root)
        trajectory.events = None
    layout.replace_results(results, superseded)

    fills = list(manifest.get("fills") or [])
    fills.append(
        {
            "at": at,
            "units": [unit.slug for unit in units],
            "outcomes": {
                "before": _tally(superseded),
                "after": _tally([results[i] for i in todo]),
            },
            "harness_version": backend.version(),
            "wikiskill_version": __version__,
            "retries": run.retries,
            "duration_s": round(time.time() - started, 1),
            "preflight": {model: result.as_dict() for model, result in run.preflight.items()},
        }
    )
    layout.write_manifest(
        {
            **manifest,
            "fills": fills,
            "outcomes": run.counts(),
            "events_written": int(manifest.get("events_written") or 0) + run.events_written,
            "warnings": [*(manifest.get("warnings") or []), *run.warnings],
        }
    )
    return run, [unit.slug for unit in units]


def _tally(results: list[dict[str, Any]]) -> dict[str, int]:
    tally: dict[str, int] = {}
    for result in results:
        tally[result["outcome"]] = tally.get(result["outcome"], 0) + 1
    return tally
