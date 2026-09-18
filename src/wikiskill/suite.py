"""Task suites: the declarative fixtures an explicit evaluation runs.

A suite is data. Adding a task changes a YAML file and nothing else, which is why the checks live
here rather than in each caller: the schema covers shape, and this module covers the three things a
schema cannot say — ids are unique within the suite, every task states how it will be judged, and a
prompt never names what it is supposed to route to.

Nothing here executes a task or touches a collection's source tree.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator

from . import paths

#: Used when neither the task nor the suite's `defaults` says otherwise.
DEFAULT_REPEATS = 3
DEFAULT_TIMEOUT_S = 900
DEFAULT_MAX_STEPS = 40

SPLITS = ("train", "val", "test")
VERIFIER_KINDS = ("command", "file_exists", "regex")

_WORD = re.compile(r"[a-z0-9]+")


class SuiteError(Exception):
    """A suite file is missing, unparseable, or invalid. Carries every problem found."""

    def __init__(self, path: Path | None, problems: Sequence[str]) -> None:
        self.path = path
        self.problems = list(problems)
        where = f"{path}: " if path else ""
        joined = "\n  - ".join(self.problems)
        super().__init__(f"{where}invalid task suite\n  - {joined}")


# --------------------------------------------------------------------------- schema


@lru_cache(maxsize=1)
def load_schema() -> dict[str, Any]:
    with paths.suite_schema_path().open(encoding="utf-8") as handle:
        return json.load(handle)


@lru_cache(maxsize=1)
def _validator() -> Draft202012Validator:
    schema = load_schema()
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


def schema_errors(document: Any) -> list[str]:
    """Schema complaints about a whole suite document, outermost path first."""
    problems = []
    for error in sorted(_validator().iter_errors(document), key=lambda e: list(e.absolute_path)):
        location = "/".join(str(part) for part in error.absolute_path) or "<suite>"
        problems.append(f"{location}: {error.message}")
    return problems


# --------------------------------------------------------------------------- model


@dataclass(frozen=True)
class Verifier:
    """One deterministic check. Verifiers decide pass or fail; a rubric only scores dimensions."""

    kind: str
    run: str | None = None
    expect_exit: int = 0
    path: str | None = None
    pattern: str | None = None
    target: str = "final_text"
    negate: bool = False

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> Verifier:
        return cls(
            kind=raw["kind"],
            run=raw.get("run"),
            expect_exit=int(raw.get("expect_exit", 0)),
            path=raw.get("path"),
            pattern=raw.get("pattern"),
            target=raw.get("target", "final_text"),
            negate=bool(raw.get("negate", False)),
        )


@dataclass(frozen=True)
class Route:
    """What a correct run activates. Empty when the task is judged only by verifiers or a rubric."""

    skill: str | None = None
    agent: str | None = None
    command: str | None = None
    agents: tuple[str, ...] = ()

    def __bool__(self) -> bool:
        return bool(self.skill or self.agent or self.command or self.agents)

    def names(self) -> list[str]:
        """Every component this route names, in a stable order."""
        found = [n for n in (self.skill, self.agent, self.command) if n]
        found.extend(self.agents)
        return found

    @property
    def primary(self) -> str | None:
        """The component whose activation `route@1` is measured against."""
        return self.skill or self.command or self.agent

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> Route:
        return cls(
            skill=raw.get("skill"),
            agent=raw.get("agent"),
            command=raw.get("command"),
            agents=tuple(raw.get("agents", ())),
        )


@dataclass(frozen=True)
class Task:
    """One evaluation task, with the suite's defaults already folded in."""

    id: str
    prompt: str
    split: str
    expect: Route = field(default_factory=Route)
    verifiers: tuple[Verifier, ...] = ()
    rubric: str | None = None
    fixtures: str | None = None
    requires: tuple[str, ...] = ()
    guard_deny: tuple[str, ...] = ()
    followups: tuple[str, ...] = ()
    repeats: int = DEFAULT_REPEATS
    timeout_s: int = DEFAULT_TIMEOUT_S
    max_steps: int = DEFAULT_MAX_STEPS

    @property
    def judged(self) -> bool:
        """Whether anything at all decides this task's outcome."""
        return bool(self.expect) or bool(self.verifiers) or self.rubric is not None


@dataclass(frozen=True)
class Suite:
    """A loaded, validated suite."""

    name: str
    tasks: tuple[Task, ...]
    description: str | None = None
    path: Path | None = None

    @property
    def root(self) -> Path:
        """Directory that `fixtures` and `rubric` paths are relative to."""
        return self.path.parent if self.path else Path.cwd()

    def task(self, task_id: str) -> Task:
        for task in self.tasks:
            if task.id == task_id:
                return task
        raise KeyError(task_id)

    def split(self, name: str) -> list[Task]:
        return [t for t in self.tasks if t.split == name]


# --------------------------------------------------------------------------- leak check


def _words(text: str) -> list[str]:
    """Lowercase alphanumeric words. `dataset-release` and `dataset release` read the same."""
    return _WORD.findall(text.lower())


def _mentions(prompt_words: Sequence[str], term: str) -> bool:
    """Whether the prompt contains ``term`` as a whole run of words."""
    needle = _words(term)
    if not needle:
        return False
    span = len(needle)
    return any(
        list(prompt_words[i : i + span]) == needle for i in range(len(prompt_words) - span + 1)
    )


def leak_terms(name: str) -> list[str]:
    """The identifiers a prompt must not contain for an expected route ``name``.

    A component is named `<plugin>/<component>`, and a prompt that says either half has instructed
    the route instead of testing it. The full slug is checked first so the report names the most
    specific match.
    """
    parts = [part for part in name.split("/") if part]
    terms = [name] if len(parts) > 1 else []
    terms.extend(reversed(parts))
    return list(dict.fromkeys(terms))


def prompt_leaks(task: Task) -> list[str]:
    """Expected-route identifiers this task's prompt names, most specific first."""
    prompt_words = _words(task.prompt)
    found: list[str] = []
    for name in task.expect.names():
        for term in leak_terms(name):
            if _mentions(prompt_words, term) and term not in found:
                found.append(term)
    return found


# --------------------------------------------------------------------------- loading


def _as_task(raw: dict[str, Any], defaults: dict[str, Any]) -> Task:
    guard = raw.get("guard") or defaults.get("guard") or {}
    return Task(
        id=raw["id"],
        prompt=raw["prompt"],
        split=raw["split"],
        expect=Route.from_dict(raw.get("expect") or {}),
        verifiers=tuple(Verifier.from_dict(v) for v in raw.get("verifiers", ())),
        rubric=raw.get("rubric"),
        fixtures=raw.get("fixtures"),
        requires=tuple(raw.get("requires") or defaults.get("requires") or ()),
        guard_deny=tuple(guard.get("deny", ())),
        followups=tuple(raw.get("followups", ())),
        repeats=int(raw.get("repeats", defaults.get("repeats", DEFAULT_REPEATS))),
        timeout_s=int(raw.get("timeout_s", defaults.get("timeout_s", DEFAULT_TIMEOUT_S))),
        max_steps=int(raw.get("max_steps", defaults.get("max_steps", DEFAULT_MAX_STEPS))),
    )


def parse(document: Any, *, path: Path | None = None) -> Suite:
    """Validate a already-parsed suite document and build a `Suite`.

    Raises `SuiteError` carrying *every* problem: a contributor fixing a suite should see the whole
    list, not one complaint per run.
    """
    problems = schema_errors(document)
    if problems:
        raise SuiteError(path, problems)

    defaults = document.get("defaults") or {}
    tasks = [_as_task(raw, defaults) for raw in document["tasks"]]

    seen: dict[str, int] = {}
    for index, task in enumerate(tasks):
        first = seen.setdefault(task.id, index)
        if first != index:
            problems.append(
                f"tasks/{index}: duplicate task id {task.id!r}, already used at tasks/{first}"
            )
        if not task.judged:
            problems.append(
                f"tasks/{index}: task {task.id!r} declares no expected outcome: it needs an "
                "`expect` route, a verifier, or a rubric"
            )
        for term in prompt_leaks(task):
            problems.append(
                f"tasks/{index}: task {task.id!r} names {term!r} in its prompt, which is part of "
                "its expected route: the prompt would instruct the route instead of testing it"
            )
    if problems:
        raise SuiteError(path, problems)

    return Suite(
        name=document["suite"],
        tasks=tuple(tasks),
        description=document.get("description"),
        path=path,
    )


def load(path: str | Path) -> Suite:
    """Read and validate a suite file. YAML and JSON are both accepted."""
    file_path = Path(path).expanduser()
    try:
        text = file_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise SuiteError(file_path, [f"cannot read suite file: {exc.strerror or exc}"]) from exc
    try:
        document = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise SuiteError(file_path, [f"not valid YAML: {exc}"]) from exc
    if not isinstance(document, dict):
        raise SuiteError(file_path, ["expected a mapping at the top level"])
    return parse(document, path=file_path.resolve())


def check(paths_in: Iterable[str | Path]) -> list[tuple[Path, list[str]]]:
    """Validate several suite files. Returns ``(path, problems)`` for the ones that failed."""
    failures = []
    for raw in paths_in:
        try:
            load(raw)
        except SuiteError as exc:
            failures.append((exc.path or Path(raw), exc.problems))
    return failures
