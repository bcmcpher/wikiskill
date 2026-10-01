"""Pool runs of one suite from several machines into one table per model and condition.

A workshop runs the same suite on a dozen laptops, each with whatever models it can serve. No single
run says much — one repeat of three tasks is three coin flips — but the same suite, the same
components and the same verifiers pooled across machines is a sample worth an interval. So this
refuses runs whose suite content or component versions differ, rather than averaging two different
experiments into one number.

A unit counts as passed the way a report counts it: its verifiers' verdict where the task declares
any, and otherwise whether its first activation was the expected component. A task always uses the
same basis on every model, so models remain comparable on one suite. A route is only possible under
ROUTED — OFF installs nothing and INJECTED denies the skill — so a route-scored unit counts there
alone, rather than adding a failure by construction to the other two.

Units that did not run (`skipped`, `infra_error`) are not failures and are not in the denominator;
they are counted beside it, because a model that times out on half its units is not one that
passed the other half cleanly.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import rawlog
from .compare import CompareError, LoadedRun, Rate, wilson
from .runner.base import ROUTED
from .score.route import UNSCORED, first_activation, same


class LeaderboardError(CompareError):
    """Runs that cannot be pooled."""


@dataclass
class Cell:
    """One model under one condition, pooled over every run that ran it."""

    model: str
    condition: str
    passed: int = 0
    total: int = 0
    not_run: int = 0
    runs: set[str] = field(default_factory=set)
    contexts: set[int] = field(default_factory=set)

    @property
    def rate(self) -> Rate:
        return Rate(passed=self.passed, total=self.total)

    def as_dict(self) -> dict[str, Any]:
        return {
            "model": self.model,
            "condition": self.condition,
            **self.rate.as_dict(),
            "not_run": self.not_run,
            "runs": sorted(self.runs),
            "context_tokens": sorted(self.contexts),
        }


@dataclass
class Leaderboard:
    suite: str | None
    suite_hash: str | None
    runs: list[LoadedRun]
    components: dict[str, str | None]
    #: (model, condition) → pooled cell
    cells: dict[tuple[str, str], Cell] = field(default_factory=dict)
    #: (task, model, condition) → pooled rate
    matrix: dict[tuple[str, str, str], Rate] = field(default_factory=dict)
    #: task → how its units are judged: `verifier` or `route`
    bases: dict[str, str] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    @property
    def conditions(self) -> list[str]:
        return sorted({condition for _, condition in self.cells})

    def ranked(self, condition: str) -> list[tuple[Cell, bool]]:
        """Cells best first, each with whether its interval is clear of the leader's.

        Rank follows the point estimate, but a place in the table is not a finding: a model whose
        interval overlaps the leader's is not shown to be worse, and the table says so.
        """
        cells = [c for (_, cond), c in self.cells.items() if cond == condition and c.total]
        cells.sort(key=lambda c: (-(c.rate.rate or 0.0), -c.total, c.model))
        if not cells:
            return []
        leader = cells[0].rate.interval
        ranked = []
        for cell in cells:
            interval = cell.rate.interval
            clear = bool(leader and interval and interval[1] < leader[0])
            ranked.append((cell, clear))
        return ranked

    def as_dict(self) -> dict[str, Any]:
        return {
            "suite": self.suite,
            "suite_hash": self.suite_hash,
            "runs": [
                {
                    "run_id": run.run_id,
                    "harness_version": run.manifest.get("harness_version"),
                    "wikiskill_version": run.manifest.get("wikiskill_version"),
                    "models": run.manifest.get("models", []),
                    "conditions": run.manifest.get("conditions", []),
                }
                for run in self.runs
            ],
            "components": self.components,
            "bases": self.bases,
            "ranking": {
                condition: [
                    {**cell.as_dict(), "clear_of_leader": clear}
                    for cell, clear in self.ranked(condition)
                ]
                for condition in self.conditions
            },
            "matrix": [
                {"task_id": task, "model": model, "condition": condition, **rate.as_dict()}
                for (task, model, condition), rate in sorted(self.matrix.items())
            ],
            "warnings": self.warnings,
        }


# --------------------------------------------------------------------------- pooling


def pool(runs: list[LoadedRun]) -> Leaderboard:
    """Pool runs of one suite, refusing any that measured something else."""
    if not runs:
        raise LeaderboardError("no runs to pool")
    first = runs[0]
    for run in runs[1:]:
        if run.suite != first.suite:
            raise LeaderboardError(
                f"{run.run_id} ran suite {run.suite!r}, but {first.run_id} ran {first.suite!r}"
            )
        if run.suite_hash != first.suite_hash:
            raise LeaderboardError(
                f"{run.run_id} ran different content of suite {first.suite!r} "
                f"({run.suite_hash or 'no suite_hash'}, against {first.suite_hash or 'none'} in "
                f"{first.run_id}): its prompts or verifiers differ, so its results are another "
                "experiment"
            )
    board = Leaderboard(
        suite=first.suite,
        suite_hash=first.suite_hash,
        runs=list(runs),
        components=_components(runs),
    )
    if not first.suite_hash:
        board.warnings.append("no run recorded a suite_hash, so the suite content is unverified")
    versions = {run.manifest.get("harness_version") for run in runs}
    if len(versions) > 1:
        board.warnings.append(
            "the runs used different harness versions: "
            + ", ".join(sorted(str(v) for v in versions))
        )

    for run in runs:
        contexts = _contexts(run)
        for result in run.results:
            _add(board, run, result, contexts)
    return board


def _components(runs: list[LoadedRun]) -> dict[str, str | None]:
    """Every component under test and its one version, or a refusal naming the runs that differ."""
    seen: dict[str, tuple[str | None, str]] = {}
    for run in runs:
        for name, digest in run.hashes().items():
            if name not in seen:
                seen[name] = (digest, run.run_id)
                continue
            known, where = seen[name]
            if known != digest:
                raise LeaderboardError(
                    f"{name} differs between runs: {_short(known)} in {where}, {_short(digest)} in "
                    f"{run.run_id}. Pool runs of one version; `wikiskill compare` is for two."
                )
    return {name: digest for name, (digest, _) in sorted(seen.items())}


def _contexts(run: LoadedRun) -> dict[str, int]:
    """The context each model was served with in one run, from its preflight."""
    found = {}
    for model, entry in (run.manifest.get("preflight") or {}).items():
        context = ((entry or {}).get("details") or {}).get("context_tokens")
        if isinstance(context, int):
            found[model] = context
    return found


def _add(board: Leaderboard, run: LoadedRun, result: dict[str, Any], contexts: dict) -> None:
    model, condition, task = result["model"], result["condition"], result["task_id"]
    cell = board.cells.setdefault((model, condition), Cell(model=model, condition=condition))
    cell.runs.add(run.run_id)
    if model in contexts:
        cell.contexts.add(contexts[model])
    if result.get("outcome") in UNSCORED:
        cell.not_run += 1
        return
    verdict, basis = unit_verdict(result)
    if verdict is None:
        return
    board.bases.setdefault(task, basis)
    cell.passed += 1 if verdict else 0
    cell.total += 1
    rate = board.matrix.get((task, model, condition), Rate(0, 0))
    board.matrix[(task, model, condition)] = Rate(
        passed=rate.passed + (1 if verdict else 0), total=rate.total + 1
    )


def unit_verdict(result: dict[str, Any]) -> tuple[bool | None, str]:
    """Whether one unit passed, and on what basis; ``None`` when it measures nothing."""
    if result.get("passed") is not None:
        return bool(result["passed"]), "verifier"
    expected = (result.get("expected") or {}).get("primary")
    if not expected or result.get("condition") != ROUTED:
        return None, "route"
    return same(first_activation(result), expected), "route"


def _short(digest: str | None) -> str:
    return (digest or "no hash").removeprefix("sha256:")[:12]


# --------------------------------------------------------------------------- output


def _fmt(rate: Rate) -> str:
    if not rate.total:
        return "-"
    low, high = wilson(rate.passed, rate.total) or (0.0, 0.0)
    return f"{rate.passed}/{rate.total} ({rate.rate:.0%}, {low:.0%}-{high:.0%})"


def ranking_lines(ranking: dict[str, list[dict[str, Any]]]) -> list[str]:
    """The pooled table per condition, from `as_dict()["ranking"]`.

    Shared by the leaderboard and a single run's report, which stores it as data.
    """
    lines: list[str] = []
    for condition, entries in sorted(ranking.items()):
        if not entries:
            continue
        lines += [
            f"### {condition}",
            "",
            "| # | model | passed (95% CI) | not run | runs | context |",
            "|---|---|---|---|---|---|",
        ]
        for place, entry in enumerate(entries, start=1):
            mark = str(place) if place == 1 or entry["clear_of_leader"] else f"{place}≈"
            rate = Rate(passed=entry["passed"], total=entry["total"])
            contexts = ", ".join(f"{c // 1024}k" for c in entry["context_tokens"]) or "-"
            lines.append(
                f"| {mark} | {entry['model']} | {_fmt(rate)} | {entry['not_run']} | "
                f"{len(entry['runs'])} | {contexts} |"
            )
        lines.append("")
    if lines:
        lines += [
            "`≈` marks a model whose interval overlaps the leader's: its place is not a finding.",
            "",
        ]
    return lines


def render(board: Leaderboard) -> str:
    lines = [
        f"# Leaderboard: {board.suite}",
        "",
        f"- suite_hash: `{_short(board.suite_hash)}`",
        f"- runs: {len(board.runs)} ({', '.join(f'`{run.run_id}`' for run in board.runs)})",
    ]
    lines += [f"- `{name}`: `{_short(digest)}`" for name, digest in board.components.items()]
    lines += [
        "",
        (
            "A unit passes on its verifiers, or, for a task with none, when its first activation "
            "is the expected component. Intervals are Wilson 95%. Units that did not run are "
            "counted beside the rate, never in it."
        ),
        "",
    ]
    lines += [f"> warning: {warning}" for warning in board.warnings]
    if board.warnings:
        lines.append("")
    lines += ["## Ranking", "", *ranking_lines(board.as_dict()["ranking"])]
    lines += _matrix_lines(board)
    return "\n".join(lines)


def _matrix_lines(board: Leaderboard) -> list[str]:
    models = sorted({model for _, model, _ in board.matrix})
    tasks = sorted({task for task, _, _ in board.matrix})
    lines = ["## Per task", ""]
    for condition in board.conditions:
        rows = [
            (task, [board.matrix.get((task, model, condition)) for model in models])
            for task in tasks
        ]
        rows = [(task, rates) for task, rates in rows if any(rates)]
        if not rows:
            continue
        lines += [
            f"### {condition}",
            "",
            "| task | basis | " + " | ".join(models) + " |",
            "|---|---|" + "---|" * len(models),
        ]
        for task, rates in rows:
            cells = [f"{r.passed}/{r.total}" if r and r.total else "-" for r in rates]
            lines.append(f"| {task} | {board.bases.get(task, '-')} | " + " | ".join(cells) + " |")
        lines.append("")
    return lines


def write(board: Leaderboard, out: Path) -> tuple[Path, Path]:
    out.mkdir(parents=True, exist_ok=True)
    md, js = out / "leaderboard.md", out / "leaderboard.json"
    md.write_text(render(board), encoding="utf-8")
    js.write_text(json.dumps(board.as_dict(), indent=2) + "\n", encoding="utf-8")
    return md, js


def output_name(runs: list[LoadedRun]) -> str:
    """A stable directory name for one set of runs, whatever order they were given in."""
    digest = rawlog.content_hash("\n".join(sorted(run.run_id for run in runs)).encode())
    return f"{runs[0].suite}-{_short(digest)}"
