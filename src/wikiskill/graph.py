"""The collection graph: which components depend on and get confused with which.

Refining one component can break another. A planner's tightened steps stop handing off to the doer
behind it; a broadened description takes another skill's triggers. The graph records both, so the
refinement gate can name a proposal's neighbours, say which of them a replay covers, and check a
description edit against the components it has been confused with.

- `dependency` edges come from what the collection declares: `delegates_to` frontmatter (weight
  1.0; a plugin name stands for that plugin's agents) and component names in bodies (0.5).
- `conflict` edges come from what eval runs observed: under ROUTED, the share of a task's repeats
  whose first activation was another component, per model. The edge runs from the component the
  task expected to the one that took its trigger.

Co-usage edges are deferred until live logs show components used together.

The graph is stored as `graph.json` in the collection's wiki and rebuilt only on request.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import paths, rawlog, wiki
from .collection import Collection, Component
from .compare import LoadedRun, load_run
from .frontmatter import FrontmatterError
from .frontmatter import read as read_frontmatter
from .runner.base import ROUTED
from .score.route import NONE, bare, same, score_all

DEPENDENCY, CONFLICT = "dependency", "conflict"
DECLARED, MENTIONED = 1.0, 0.5
#: Conflict edges below this rate are kept in the graph but make no neighbour.
MIN_CONFLICT = 0.05
GRAPH = "graph.json"


@dataclass
class Edge:
    kind: str
    source: str
    target: str
    weight: float
    evidence: list[dict[str, Any]] = field(default_factory=list)
    #: conflict only: model → confusion rate
    per_model: dict[str, float] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        found = {
            "kind": self.kind,
            "source": self.source,
            "target": self.target,
            "weight": self.weight,
            "evidence": self.evidence,
        }
        if self.per_model:
            found["per_model"] = self.per_model
        return found

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> Edge:
        return cls(
            kind=raw["kind"],
            source=raw["source"],
            target=raw["target"],
            weight=raw["weight"],
            evidence=list(raw.get("evidence") or []),
            per_model=dict(raw.get("per_model") or {}),
        )


@dataclass(frozen=True)
class Neighbour:
    name: str
    edges: tuple[Edge, ...]

    @property
    def kinds(self) -> tuple[str, ...]:
        return tuple(sorted({edge.kind for edge in self.edges}))

    @property
    def weight(self) -> float:
        return max(edge.weight for edge in self.edges)


@dataclass
class Graph:
    collection: str
    edges: list[Edge] = field(default_factory=list)
    #: delegations that name nothing in the collection, with where they are declared
    unresolved: list[dict[str, Any]] = field(default_factory=list)
    runs: list[str] = field(default_factory=list)
    built: str | None = None

    def neighbours(
        self,
        component: str,
        *,
        min_conflict: float = MIN_CONFLICT,
        min_dependency: float = MENTIONED,
    ) -> list[Neighbour]:
        """Depth-1 neighbours in either direction, above the thresholds, strongest first."""
        found: dict[str, list[Edge]] = {}
        for edge in self.edges:
            floor = min_conflict if edge.kind == CONFLICT else min_dependency
            if edge.weight < floor - 1e-9:
                continue
            if edge.source == component and edge.target != component:
                found.setdefault(edge.target, []).append(edge)
            elif edge.target == component and edge.source != component:
                found.setdefault(edge.source, []).append(edge)
        neighbours = [Neighbour(name, tuple(edges)) for name, edges in found.items()]
        return sorted(neighbours, key=lambda n: (-n.weight, n.name))

    def as_dict(self) -> dict[str, Any]:
        return {
            "collection": self.collection,
            "built": self.built,
            "runs": self.runs,
            "edges": [edge.as_dict() for edge in self.edges],
            "unresolved": self.unresolved,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> Graph:
        return cls(
            collection=raw["collection"],
            edges=[Edge.from_dict(edge) for edge in raw.get("edges") or []],
            unresolved=list(raw.get("unresolved") or []),
            runs=list(raw.get("runs") or []),
            built=raw.get("built"),
        )


# --------------------------------------------------------------------------- storage


def path(collection: str) -> Path:
    return wiki.wiki_root(collection) / GRAPH


def load(collection: str) -> Graph | None:
    """The stored graph, or None when `wikiskill graph build` has not been run."""
    stored = path(collection)
    if not stored.is_file():
        return None
    return Graph.from_dict(json.loads(stored.read_text(encoding="utf-8")))


def write(graph: Graph) -> Path:
    root = wiki.ensure(graph.collection)
    target = root / GRAPH
    target.write_text(json.dumps(graph.as_dict(), indent=2) + "\n", encoding="utf-8")
    counts = {
        kind: sum(1 for e in graph.edges if e.kind == kind) for kind in (DEPENDENCY, CONFLICT)
    }
    wiki.commit(
        root,
        f"graph: {counts[DEPENDENCY]} dependency, {counts[CONFLICT]} conflict edge(s) from "
        f"{len(graph.runs)} run(s)",
    )
    return target


# --------------------------------------------------------------------------- building


def build(collection: Collection, runs: Sequence[str | Path] | None = None) -> Graph:
    """The graph from the collection's sources and its eval runs: every run, or those named.

    Candidate runs (`wikiskill eval --proposal`) are skipped: they test a version never accepted.
    """
    components = collection.discover()
    loaded = [load_run(collection.name, run) for run in runs or _all_runs(collection.name)]
    loaded = [run for run in loaded if not run.manifest.get("proposal")]
    graph = Graph(collection=collection.name, built=rawlog.now_ts())
    graph.runs = sorted(run.run_id for run in loaded)
    dependencies, graph.unresolved = _dependencies(components)
    graph.edges = sorted(
        [*dependencies, *_conflicts(components, loaded)],
        key=lambda e: (e.kind, e.source, e.target),
    )
    return graph


def _all_runs(collection: str) -> list[Path]:
    root = paths.evals_dir(collection)
    if not root.is_dir():
        return []
    return sorted(d for d in root.iterdir() if (d / "run.json").is_file())


def resolve(name: str, components: Sequence[Component]) -> str | None:
    """A component's full name from its full or unique bare name."""
    names = {c.name for c in components}
    if name in names:
        return name
    matches = {c.name for c in components if same(c.name, name)}
    return next(iter(matches)) if len(matches) == 1 else None


def _dependencies(
    components: Sequence[Component],
) -> tuple[list[Edge], list[dict[str, Any]]]:
    edges: dict[tuple[str, str], Edge] = {}
    unresolved: list[dict[str, Any]] = []

    def add(source: str, target: str, weight: float, evidence: dict[str, Any]) -> None:
        if source == target:
            return
        edge = edges.setdefault((source, target), Edge(DEPENDENCY, source, target, weight))
        edge.weight = max(edge.weight, weight)
        if evidence not in edge.evidence:
            edge.evidence.append(evidence)

    for component in components:
        try:
            document = read_frontmatter(component.path)
        except (FrontmatterError, OSError):
            continue
        lines = component.path.read_text(encoding="utf-8").splitlines()
        declared = document.meta.get("delegates_to") or []
        if isinstance(declared, str):
            declared = [declared]
        where = {
            "path": str(component.path),
            "line": _line_of(lines, re.compile(r"^delegates_to\s*:")),
            "via": "delegates_to",
        }
        for entry in declared:
            targets = _delegation_targets(str(entry), components)
            if not targets:
                unresolved.append(
                    {"component": component.name, "delegates_to": str(entry), **where}
                )
            for target in targets:
                add(component.name, target, DECLARED, where)
        body_start = len(lines) - len(document.body.splitlines())
        for other in components:
            if other.name == component.name:
                continue
            line = _mention(lines, body_start, other.name)
            if line is not None:
                evidence = {"path": str(component.path), "line": line, "via": "mention"}
                add(component.name, other.name, MENTIONED, evidence)
    return list(edges.values()), unresolved


def _delegation_targets(entry: str, components: Sequence[Component]) -> list[str]:
    """A plugin's agents, or the one component the entry names."""
    agents = sorted({c.name for c in components if c.kind == "agent" and c.plugin == entry})
    if agents:
        return agents
    named = resolve(entry, components)
    return [named] if named else []


def _line_of(lines: Sequence[str], pattern: re.Pattern[str], start: int = 0) -> int | None:
    for number, line in enumerate(lines[start:], start=start + 1):
        if pattern.search(line):
            return number
    return None


def _mention(lines: Sequence[str], start: int, name: str) -> int | None:
    """The first body line naming ``name``: in full when it has a plugin, else in backticks."""
    patterns = [rf"`{re.escape(bare(name))}`"]
    if "/" in name:
        patterns.append(rf"(?<![\w/-]){re.escape(name)}(?![\w-])")
    return _line_of(lines, re.compile("|".join(patterns)), start)


def _conflicts(components: Sequence[Component], runs: Iterable[LoadedRun]) -> list[Edge]:
    """Under ROUTED: per expected route and model, how often another component went first."""
    repeats: dict[tuple[str, str], int] = {}
    taken: dict[tuple[str, str, str], int] = {}
    evidence: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for run in runs:
        routed = [r for r in run.results if r["condition"] == ROUTED]
        for score in score_all(routed):
            if not score.expected or not score.repeats:
                continue
            expected = resolve(score.expected, components) or bare(score.expected)
            key = (expected, score.model)
            repeats[key] = repeats.get(key, 0) + score.repeats
            for chosen, count in score.chosen.items():
                if chosen == NONE or same(chosen, expected):
                    continue
                target = resolve(chosen, components) or chosen
                taken[(expected, target, score.model)] = (
                    taken.get((expected, target, score.model), 0) + count
                )
                evidence.setdefault((expected, target), []).append(
                    {
                        "run_id": run.run_id,
                        "task_id": score.task_id,
                        "model": score.model,
                        "taken": count,
                        "repeats": score.repeats,
                    }
                )
    edges: dict[tuple[str, str], Edge] = {}
    for expected, target, _ in sorted(taken):
        edge = edges.setdefault(
            (expected, target),
            Edge(CONFLICT, expected, target, 0.0, evidence=evidence[(expected, target)]),
        )
        # Every model that ran the expected route, a model that never confused them at 0.
        for (route, model), total in sorted(repeats.items()):
            if route == expected:
                edge.per_model[model] = round(taken.get((expected, target, model), 0) / total, 4)
        edge.weight = max(edge.per_model.values())
    return list(edges.values())


# --------------------------------------------------------------------------- output


def render(graph: Graph) -> str:
    lines = [
        f"# Collection graph: {graph.collection}",
        "",
        f"- built: {graph.built or '?'}",
        f"- runs read: {', '.join(graph.runs) or 'none'}",
        "",
    ]
    for kind in (DEPENDENCY, CONFLICT):
        edges = [edge for edge in graph.edges if edge.kind == kind]
        lines += [f"## {kind} ({len(edges)})", ""]
        lines += [f"- {_edge_line(edge)}" for edge in edges] or ["- none"]
        lines.append("")
    lines += ["## unresolved delegations", ""]
    lines += [
        f"- {u['component']} delegates_to {u['delegates_to']}: nothing in the collection "
        f"({Path(u['path']).name}:{u['line']})"
        for u in graph.unresolved
    ] or ["- none"]
    return "\n".join(lines)


def _edge_line(edge: Edge) -> str:
    line = f"{edge.source} -> {edge.target}  {edge.weight:.2f}"
    if edge.per_model:
        line += "  (" + ", ".join(f"{m} {r:.2f}" for m, r in sorted(edge.per_model.items())) + ")"
        runs = sorted({e["run_id"] for e in edge.evidence})
        return f"{line}; runs {', '.join(runs)}"
    where = ", ".join(f"{e['via']} {Path(e['path']).name}:{e['line']}" for e in edge.evidence)
    return f"{line}  ({where})"


def render_neighbours(component: str, neighbours: Sequence[Neighbour]) -> str:
    if not neighbours:
        return f"{component} has no neighbours above the thresholds"
    lines = [f"neighbours of {component}:"]
    for neighbour in neighbours:
        directions = ", ".join(
            f"{e.kind} {'->' if e.source == component else '<-'} {e.weight:.2f}"
            for e in neighbour.edges
        )
        lines.append(f"  {neighbour.name}  ({directions})")
    return "\n".join(lines)
