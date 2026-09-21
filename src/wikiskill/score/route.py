"""Routing metrics: did the model reach the component the task expected?

Routing is measured separately from whether the work was any good, because in OpenCode and Claude
Code a skill the model never loads contributes nothing at all. A task that fails because the model
went somewhere else is a routing problem; a task that fails with the right skill loaded is a content
problem. Keeping them apart is what makes a refinement proposal actionable.

Infrastructure outcomes never reach these functions with a verdict: they are counted, and excluded.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any

#: Results with these outcomes are not evidence about a component.
UNSCORED = ("infra_error", "skipped")

#: What `first_activation` reports when the model activated nothing at all.
NONE = "none"


def bare(name: str | None) -> str:
    """The comparable form of a component name: last path segment, lowercased.

    OpenCode reports `preregister` where a manifest says `govern/preregister`; the same component
    must compare equal either way, or every route would read as a miss.
    """
    return (name or "").split("/")[-1].strip().lower()


def same(left: str | None, right: str | None) -> bool:
    return bool(left) and bool(right) and bare(left) == bare(right)


def scored(results: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    return [result for result in results if result.get("outcome") not in UNSCORED]


def activated_names(result: dict[str, Any], kind: str | None = None) -> list[str]:
    """Components the model actually reached.

    A call the harness refused is not one of them. That is the whole of INJECTED: the expected skill
    is denied on purpose, so counting the attempt would report a perfect route@1 for a condition in
    which the route is impossible by construction.
    """
    activations = result.get("activations") or []
    return [
        str(entry.get("name"))
        for entry in activations
        if isinstance(entry, dict)
        and not entry.get("blocked")
        and (kind is None or entry.get("kind") == kind)
    ]


def first_activation(result: dict[str, Any]) -> str:
    """The first component the model activated, or `none`."""
    names = activated_names(result)
    return names[0] if names else NONE


@dataclass
class RouteScore:
    """Routing for one task on one model under one condition, over its repeats."""

    task_id: str
    model: str
    condition: str
    repeats: int = 0
    unscored: int = 0
    expected: str | None = None
    expected_agents: tuple[str, ...] = ()
    first_hits: int = 0
    any_hits: int = 0
    agents_reached: set[str] = field(default_factory=set)
    chosen: Counter = field(default_factory=Counter)

    @property
    def measurable(self) -> bool:
        """Whether this task says anything about routing at all."""
        return bool(self.expected or self.expected_agents)

    @property
    def route_at_1(self) -> float | None:
        """Share of repeats whose *first* activation was the expected component."""
        if not self.expected or not self.repeats:
            return None
        return self.first_hits / self.repeats

    @property
    def route_at_k(self) -> float | None:
        """Whether the expected component was reached in any repeat, as 1.0 or 0.0."""
        if not self.expected or not self.repeats:
            return None
        return 1.0 if self.any_hits else 0.0

    @property
    def capability_at_k(self) -> float | None:
        """Share of the expected agents reached across the repeats."""
        if not self.expected_agents:
            return None
        return len(self.agents_reached) / len(self.expected_agents)

    def as_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "model": self.model,
            "condition": self.condition,
            "repeats": self.repeats,
            "unscored": self.unscored,
            "expected": self.expected,
            "expected_agents": list(self.expected_agents),
            "route@1": self.route_at_1,
            "route@k": self.route_at_k,
            "capability@k": self.capability_at_k,
            "agents_reached": sorted(self.agents_reached),
            "chosen": dict(self.chosen),
        }


def score_group(results: Sequence[dict[str, Any]]) -> RouteScore:
    """Routing for one (task, model, condition) group of repeats."""
    first = results[0]
    expected = (first.get("expected") or {}).get("primary")
    expected_agents = tuple((first.get("expected") or {}).get("agents") or ())
    score = RouteScore(
        task_id=first["task_id"],
        model=first["model"],
        condition=first["condition"],
        expected=expected,
        expected_agents=expected_agents,
    )
    for result in results:
        if result.get("outcome") in UNSCORED:
            score.unscored += 1
            continue
        score.repeats += 1
        chosen = first_activation(result)
        score.chosen[bare(chosen) if chosen != NONE else NONE] += 1
        if expected:
            if same(chosen, expected):
                score.first_hits += 1
            if any(same(name, expected) for name in activated_names(result)):
                score.any_hits += 1
        for agent in expected_agents:
            if any(same(name, agent) for name in activated_names(result, kind="agent")):
                score.agents_reached.add(agent)
    return score


def score_all(results: Iterable[dict[str, Any]]) -> list[RouteScore]:
    """One `RouteScore` per (task, model, condition), in the order the results were produced."""
    groups: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    for result in results:
        key = (result["task_id"], result["model"], result["condition"])
        groups.setdefault(key, []).append(result)
    return [score_group(group) for group in groups.values()]


def confusion(scores: Iterable[RouteScore]) -> dict[str, dict[str, int]]:
    """Expected component → what was activated instead, counted.

    This is the table that says *which* skill is stealing another's triggers, which is what
    `add-collection-graph` turns into a conflict edge.
    """
    matrix: dict[str, dict[str, int]] = {}
    for score in scores:
        if not score.expected:
            continue
        row = matrix.setdefault(bare(score.expected), {})
        for chosen, count in score.chosen.items():
            row[chosen] = row.get(chosen, 0) + count
    return matrix


def aggregate(scores: Sequence[RouteScore]) -> dict[str, Any]:
    """Suite-level routing for one model and condition: means over tasks that measure routing."""
    measurable = [score for score in scores if score.route_at_1 is not None]
    capability = [score for score in scores if score.capability_at_k is not None]
    return {
        "tasks": len(scores),
        "tasks_measuring_route": len(measurable),
        "route@1": _mean([score.route_at_1 for score in measurable]),
        "route@k": _mean([score.route_at_k for score in measurable]),
        "capability@k": _mean([score.capability_at_k for score in capability]),
        "unscored": sum(score.unscored for score in scores),
    }


def _mean(values: Sequence[float | None]) -> float | None:
    present = [value for value in values if value is not None]
    return sum(present) / len(present) if present else None
