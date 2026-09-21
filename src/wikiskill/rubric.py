"""Rubrics: the dimensions a judge scores, held as data like the suites they belong to.

A rubric never decides pass or fail. Verifiers do that, deterministically, and a judge that could
overturn them would make a run's headline number depend on a model's mood. What a rubric adds is the
dimensions a verifier cannot express — whether a record is *complete*, whether provenance is
*reachable* — reported beside the pass rate and never folded into it.

Each dimension carries named anchors in the order they were written, worst first. The order is the
scale: nothing here assumes `none`/`partial`/`complete`, because a binary dimension writes
`fail`/`pass` and a rubric is free to write neither.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

#: How many judges a rubric may ask for. Three when a dimension is contestable enough to want a
#: majority; one otherwise, because three judges cost three times as much to learn the same thing.
JUDGE_COUNTS = (1, 3)


class RubricError(Exception):
    """A rubric file is missing, unparseable, or invalid. Carries every problem found."""

    def __init__(self, path: Path | None, problems: Sequence[str]) -> None:
        self.path = path
        self.problems = list(problems)
        where = f"{path}: " if path else ""
        joined = "\n  - ".join(self.problems)
        super().__init__(f"{where}invalid rubric\n  - {joined}")


@dataclass(frozen=True)
class Dimension:
    """One thing a judge scores, and the anchors it scores against."""

    id: str
    anchors: tuple[tuple[str, str], ...]
    evidence: str = ""
    kind: str = "scale"
    stamped: tuple[str, ...] = ()

    @property
    def levels(self) -> tuple[str, ...]:
        """Anchor names in declaration order, which is the scale from worst to best."""
        return tuple(name for name, _ in self.anchors)

    def rank(self, level: str | None) -> int | None:
        levels = self.levels
        return levels.index(level) if level in levels else None


@dataclass(frozen=True)
class Rubric:
    """A loaded, validated rubric."""

    id: str
    dimensions: tuple[Dimension, ...]
    judges: int = 1
    notes: tuple[str, ...] = ()
    path: Path | None = None

    def dimension(self, dimension_id: str) -> Dimension:
        for dimension in self.dimensions:
            if dimension.id == dimension_id:
                return dimension
        raise KeyError(dimension_id)


def _dimension(raw: Any, index: int, problems: list[str]) -> Dimension | None:
    where = f"dimensions/{index}"
    if not isinstance(raw, dict):
        problems.append(f"{where}: must be a mapping")
        return None
    dimension_id = raw.get("id")
    if not isinstance(dimension_id, str) or not dimension_id.strip():
        problems.append(f"{where}: needs an `id`")
        return None
    anchors = raw.get("anchors")
    if not isinstance(anchors, dict) or len(anchors) < 2:
        problems.append(
            f"{where}: dimension {dimension_id!r} needs at least two `anchors`, since a scale with "
            "one level says nothing"
        )
        return None
    kind = raw.get("type") or "scale"
    if kind not in ("scale", "binary"):
        problems.append(f"{where}: unknown dimension type {kind!r}; expected scale or binary")
    return Dimension(
        id=dimension_id,
        anchors=tuple((str(name), str(text).strip()) for name, text in anchors.items()),
        evidence=str(raw.get("evidence") or "").strip(),
        kind=str(kind),
        stamped=tuple(str(letter) for letter in raw.get("stamped") or ()),
    )


def parse(document: Any, *, path: Path | None = None) -> Rubric:
    """Validate an already-parsed rubric document and build a `Rubric`."""
    problems: list[str] = []
    if not isinstance(document, dict):
        raise RubricError(path, ["expected a mapping at the top level"])

    rubric_id = document.get("id")
    if not isinstance(rubric_id, str) or not rubric_id.strip():
        problems.append("`id` is required")

    raw_dimensions = document.get("dimensions")
    dimensions: list[Dimension] = []
    if not isinstance(raw_dimensions, list) or not raw_dimensions:
        problems.append("`dimensions` must be a non-empty list")
    else:
        for index, raw in enumerate(raw_dimensions):
            built = _dimension(raw, index, problems)
            if built is not None:
                dimensions.append(built)

    seen: set[str] = set()
    for dimension in dimensions:
        if dimension.id in seen:
            problems.append(f"duplicate dimension id {dimension.id!r}")
        seen.add(dimension.id)

    judges = document.get("judges", 1)
    if judges not in JUDGE_COUNTS:
        problems.append(
            f"`judges` is {judges!r}; expected one of {', '.join(str(n) for n in JUDGE_COUNTS)}"
        )

    if problems:
        raise RubricError(path, problems)

    notes = document.get("notes") or ()
    return Rubric(
        id=str(rubric_id),
        dimensions=tuple(dimensions),
        judges=int(judges),
        notes=tuple(str(note).strip() for note in notes),
        path=path,
    )


def load(path: str | Path) -> Rubric:
    """Read and validate a rubric file. YAML and JSON are both accepted."""
    file_path = Path(path).expanduser()
    try:
        text = file_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise RubricError(file_path, [f"cannot read rubric file: {exc.strerror or exc}"]) from exc
    try:
        document = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise RubricError(file_path, [f"not valid YAML: {exc}"]) from exc
    return parse(document, path=file_path.resolve())


def check(paths_in: Iterable[str | Path]) -> list[tuple[Path, list[str]]]:
    """Validate several rubric files. Returns ``(path, problems)`` for the ones that failed."""
    failures = []
    for raw in paths_in:
        try:
            load(raw)
        except RubricError as exc:
            failures.append((exc.path or Path(raw), exc.problems))
    return failures
