"""What a run says once every condition has been scored: routing loss, content value, and drift.

The three conditions are only worth running because of what their differences mean. A skill can
fail two ways that look identical in a pass rate and call for opposite fixes:

- the model never reached it — routing loss, `INJECTED minus ROUTED`, fixed by the description
- it reached it and the text did not help — content value, `INJECTED minus OFF`, fixed by the body

Transfer and regression are the same question asked per task rather than on average: how often did
installing the collection start making a task pass, and how often did it start making one fail. A
suite whose average is flat can still be churning underneath, and the churn is what a maintainer
needs to see.

Model comparisons are reported, never used to gate. The exact McNemar test here answers "could this
difference be a coin flip" on the paired per-task outcomes; with suites of a dozen tasks the answer
is usually yes, and saying so is the point.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any

from .route import UNSCORED, RouteScore, score_group

#: A pass rate's provenance. `verifier` and `route` are not comparable, so a derived measure only
#: ever subtracts like from like.
VERIFIER, ROUTE, UNMEASURED = "verifier", "route", "not measured"


@dataclass(frozen=True)
class Verdict:
    """One task, on one model, under one condition, reduced to a single pass rate."""

    task_id: str
    model: str
    condition: str
    rate: float | None
    basis: str
    repeats: int

    @property
    def passed(self) -> bool | None:
        """The majority outcome over repeats. A tie counts as a failure, not a pass."""
        return None if self.rate is None else self.rate > 0.5


def pass_rate(
    usable: Sequence[dict[str, Any]], score: RouteScore | None
) -> tuple[float | None, str]:
    """A pass rate and what it is based on, verifier first.

    Where a task declares verifiers their verdict *is* the outcome, and routing stays a separate
    dimension rather than standing in for one. A task with no verifiers falls back to `route@1`; a
    task with neither is not measured, which is said rather than reported as zero.
    """
    verdicts = [result["passed"] for result in usable if result.get("passed") is not None]
    if verdicts:
        return sum(1 for verdict in verdicts if verdict) / len(verdicts), VERIFIER
    if score is not None and score.expected:
        return score.route_at_1, ROUTE
    return None, UNMEASURED


def verdicts(results: Iterable[dict[str, Any]]) -> list[Verdict]:
    """One `Verdict` per task, model and condition that produced a scorable repeat."""
    groups: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    for result in results:
        key = (result["task_id"], result["model"], result["condition"])
        groups.setdefault(key, []).append(result)

    found = []
    for (task_id, model, condition), group in groups.items():
        usable = [result for result in group if result.get("outcome") not in UNSCORED]
        rate, basis = pass_rate(usable, score_group(group) if usable else None)
        found.append(
            Verdict(
                task_id=task_id,
                model=model,
                condition=condition,
                rate=rate,
                basis=basis,
                repeats=len(usable),
            )
        )
    return found


def _index(found: Iterable[Verdict]) -> dict[tuple[str, str, str], Verdict]:
    return {(v.task_id, v.model, v.condition): v for v in found}


def _paired(
    found: Sequence[Verdict], model: str, left: str, right: str
) -> list[tuple[Verdict, Verdict]]:
    """Tasks measured the same way under both conditions, for one model.

    A pair whose two halves rest on different bases is dropped: subtracting a verifier pass rate
    from a routing one would produce a number with no meaning.
    """
    table = _index(found)
    tasks = sorted({v.task_id for v in found if v.model == model})
    pairs = []
    for task in tasks:
        a, b = table.get((task, model, left)), table.get((task, model, right))
        if a is None or b is None or a.rate is None or b.rate is None or a.basis != b.basis:
            continue
        pairs.append((a, b))
    return pairs


def difference(found: Sequence[Verdict], model: str, left: str, right: str) -> dict[str, Any]:
    """Mean `left` minus `right` over the tasks both conditions measured, and how many that was."""
    pairs = _paired(found, model, left, right)
    if not pairs:
        return {
            "value": None,
            "tasks": 0,
            "reason": f"no task was measured under both {left} and {right}",
        }
    gaps = [a.rate - b.rate for a, b in pairs]
    return {"value": round(sum(gaps) / len(gaps), 4), "tasks": len(pairs)}


def drift(found: Sequence[Verdict], model: str, before: str, after: str) -> dict[str, Any]:
    """How many tasks changed verdict between two conditions, in each direction."""
    pairs = _paired(found, model, after, before)
    if not pairs:
        return {"transfer_rate": None, "regression_rate": None, "tasks": 0}
    gained = sum(1 for a, b in pairs if a.passed and not b.passed)
    lost = sum(1 for a, b in pairs if b.passed and not a.passed)
    return {
        "transfer_rate": round(gained / len(pairs), 4),
        "regression_rate": round(lost / len(pairs), 4),
        "tasks": len(pairs),
    }


def mcnemar(left: Sequence[bool], right: Sequence[bool]) -> dict[str, Any]:
    """Exact McNemar on paired per-task outcomes. Reported, never used to gate.

    Only the discordant pairs carry information: `b` tasks the left model passed and the right
    failed, `c` the other way. Under the null those `b + c` pairs are coin flips, so the two-sided
    exact p is the binomial tail. With no discordant pairs there is nothing to test and the p is 1.
    """
    if len(left) != len(right):
        raise ValueError("McNemar needs the same tasks on both sides")
    b = sum(1 for x, y in zip(left, right, strict=True) if x and not y)
    c = sum(1 for x, y in zip(left, right, strict=True) if y and not x)
    n = b + c
    if n == 0:
        return {"b": 0, "c": 0, "p_value": 1.0, "tasks": len(left)}
    tail = sum(math.comb(n, i) for i in range(min(b, c) + 1)) / 2**n
    return {"b": b, "c": c, "p_value": round(min(1.0, 2 * tail), 6), "tasks": len(left)}


def comparisons(found: Sequence[Verdict], condition: str) -> list[dict[str, Any]]:
    """Every pair of models, on the tasks both of them measured the same way under one condition."""
    table = _index(found)
    models = sorted({v.model for v in found})
    out = []
    for index, left in enumerate(models):
        for right in models[index + 1 :]:
            tasks = sorted({v.task_id for v in found})
            paired = []
            for task in tasks:
                a, b = table.get((task, left, condition)), table.get((task, right, condition))
                if a is None or b is None or a.passed is None or b.passed is None:
                    continue
                if a.basis != b.basis:
                    continue
                paired.append((a.passed, b.passed))
            if not paired:
                continue
            result = mcnemar([a for a, _ in paired], [b for _, b in paired])
            out.append({"left": left, "right": right, "condition": condition, **result})
    return out
