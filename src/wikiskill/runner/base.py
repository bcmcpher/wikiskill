"""What every evaluation backend must provide, and where a run's files live.

A backend drives one harness. The runner above it knows nothing about OpenCode or Claude Code: it
builds the units to run, asks a backend to preflight the model, execute each unit, and normalise the
result into raw events. `add-claude-code-adapter` adds a second backend behind this same interface.

An outcome is classified before anything is scored, so a broken endpoint is never reported as a bad
skill.
"""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .. import paths, rawlog
from ..suite import Suite, Task

#: OFF runs without the collection, ROUTED with normal discovery, INJECTED with the component's
#: text forced into context while self-loading is denied.
OFF, ROUTED, INJECTED = "off", "routed", "injected"
CONDITIONS = (OFF, ROUTED, INJECTED)

#: Every way a unit can end. The first six describe what the model and harness did; `skipped` means
#: it never ran.
OUTCOMES = (
    "completed",
    "tool_call_as_text",
    "step_exhausted",
    "permission_blocked",
    "api_error",
    "infra_error",
    "skipped",
)

#: Outcomes excluded from scores and reported separately with a reason.
INFRA_OUTCOMES = ("infra_error", "skipped")


class RunnerError(Exception):
    """The runner could not set up or carry out a run. Never raised for model behaviour."""


def new_run_id() -> str:
    """A ULID, so a run directory sorts by creation time. Same scheme as an event id."""
    return rawlog.new_event_id()


# --------------------------------------------------------------------------- units


@dataclass(frozen=True)
class Unit:
    """One task, on one model, under one condition, on one repeat — the atom of a run."""

    run_id: str
    suite: str
    task: Task
    model: str
    condition: str
    repeat: int

    @property
    def task_id(self) -> str:
        return self.task.id

    @property
    def slug(self) -> str:
        """A filesystem-safe name, unique within a run."""
        model = self.model.replace("/", "_").replace(":", "-")
        return f"{self.task.id}__{model}__{self.condition}__r{self.repeat}"

    def provenance(self) -> dict[str, Any]:
        """The `eval` block every raw event from this unit carries."""
        return {
            "run_id": self.run_id,
            "suite": self.suite,
            "task_id": self.task.id,
            "condition": self.condition,
            "repeat": self.repeat,
        }


def units_for(
    suite: Suite,
    *,
    run_id: str,
    models: list[str],
    conditions: list[str],
    tasks: list[Task] | None = None,
) -> list[Unit]:
    """Every unit a run covers, ordered model → condition → task → repeat.

    Models are the outer loop because a model is the expensive thing to have loaded: an endpoint
    serving one model at a time finishes a whole model before the next is pulled.
    """
    chosen = list(tasks) if tasks is not None else list(suite.tasks)
    return [
        Unit(
            run_id=run_id,
            suite=suite.name,
            task=task,
            model=model,
            condition=condition,
            repeat=repeat,
        )
        for model in models
        for condition in conditions
        for task in chosen
        for repeat in range(task.repeats)
    ]


# --------------------------------------------------------------------------- run layout


@dataclass(frozen=True)
class RunLayout:
    """Where a run writes. Everything lives under ``<collection>/evals/<run-id>/``."""

    collection: str
    run_id: str
    root: Path

    @classmethod
    def create(cls, collection: str, run_id: str, *, base: Path | None = None) -> RunLayout:
        base_dir = base if base is not None else paths.evals_dir(collection)
        root = base_dir / run_id
        root.mkdir(parents=True, exist_ok=True)
        return cls(collection=collection, run_id=run_id, root=root)

    @property
    def manifest(self) -> Path:
        """`run.json`: versions, models, endpoints without keys, and the config actually loaded."""
        return self.root / "run.json"

    @property
    def results(self) -> Path:
        return self.root / "results.jsonl"

    @property
    def report_json(self) -> Path:
        return self.root / "report.json"

    @property
    def report_md(self) -> Path:
        return self.root / "report.md"

    def unit_dir(self, unit: Unit) -> Path:
        directory = self.root / "units" / unit.slug
        directory.mkdir(parents=True, exist_ok=True)
        return directory

    def write_manifest(self, manifest: dict[str, Any]) -> Path:
        self.manifest.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        return self.manifest

    def append_result(self, result: dict[str, Any]) -> None:
        with self.results.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(result, ensure_ascii=False, separators=(",", ":")) + "\n")
            handle.flush()

    def read_results(self) -> list[dict[str, Any]]:
        if not self.results.is_file():
            return []
        with self.results.open(encoding="utf-8") as handle:
            return [json.loads(line) for line in handle if line.strip()]


# --------------------------------------------------------------------------- results


@dataclass(frozen=True)
class PreflightResult:
    """Whether a model may be used, and why not when it may not."""

    model: str
    ok: bool
    problems: tuple[str, ...] = ()
    details: dict[str, Any] = field(default_factory=dict)

    @property
    def reason(self) -> str:
        return "; ".join(self.problems)

    def as_dict(self) -> dict[str, Any]:
        return {
            "model": self.model,
            "ok": self.ok,
            "problems": list(self.problems),
            "details": self.details,
        }


@dataclass
class Trajectory:
    """What one executed unit produced, before it is scored.

    `sessions` holds the root session and every child session the harness exported, in the harness's
    own shape. `normalize` turns them into raw events; nothing else reads them.
    """

    unit: Unit
    outcome: str
    sessions: list[dict[str, Any]] = field(default_factory=list)
    session_id: str | None = None
    duration_ms: int = 0
    exit_code: int | None = None
    tokens: dict[str, int] = field(default_factory=dict)
    error: str | None = None
    reason: str | None = None
    final_text: str = ""
    #: Every text part of every session, joined — what a `regex` verifier with `target: transcript`
    #: matches against.
    transcript: str = ""
    workdir: Path | None = None
    #: Components the model activated, in order, as ``{"kind": ..., "name": ...}``, with
    #: ``"blocked": True`` on a call the harness refused.
    activations: list[dict[str, Any]] = field(default_factory=list)
    #: One entry per verifier the task declared, in declaration order. Empty when it declared none.
    verifiers: list[dict[str, Any]] = field(default_factory=list)
    #: Whether every verifier passed. `None` when the task declares no verifiers, so "nothing was
    #: checked" is never reported as "everything passed".
    passed: bool | None = None

    @property
    def scored(self) -> bool:
        return self.outcome not in INFRA_OUTCOMES

    def as_result(self) -> dict[str, Any]:
        """One line of `results.jsonl` — everything scoring and the report need, no trajectories."""
        return {
            "run_id": self.unit.run_id,
            "suite": self.unit.suite,
            "task_id": self.unit.task_id,
            "model": self.unit.model,
            "condition": self.unit.condition,
            "repeat": self.unit.repeat,
            "outcome": self.outcome,
            "reason": self.reason,
            "error": self.error,
            "duration_ms": self.duration_ms,
            "exit_code": self.exit_code,
            "tokens": self.tokens,
            "session_id": self.session_id,
            "activations": self.activations,
            "verifiers": self.verifiers,
            "passed": self.passed,
            "expected": {
                "primary": self.unit.task.expect.primary,
                "agents": list(self.unit.task.expect.agents),
            },
        }


def skipped(unit: Unit, reason: str) -> Trajectory:
    """A unit that never ran, with the reason it did not. Never counted as a failure."""
    return Trajectory(unit=unit, outcome="skipped", reason=reason)


# --------------------------------------------------------------------------- backend


class Backend(ABC):
    """One harness's implementation of an evaluation run."""

    #: `harness` as it appears in raw events.
    harness: str = ""

    @abstractmethod
    def version(self) -> str:
        """The harness version, recorded in every event and in the run manifest."""

    @abstractmethod
    def preflight(self, model: str) -> PreflightResult:
        """Check one model's endpoint before any task runs on it."""

    @abstractmethod
    def prepare(self, unit: Unit) -> Path:
        """Build the unit's isolated environment and return its working directory."""

    @abstractmethod
    def execute(self, unit: Unit) -> Trajectory:
        """Run the unit to completion and classify how it ended."""

    @abstractmethod
    def normalize(self, trajectory: Trajectory) -> list[dict[str, Any]]:
        """Turn a trajectory into raw events carrying `origin: eval` and the unit's provenance."""
