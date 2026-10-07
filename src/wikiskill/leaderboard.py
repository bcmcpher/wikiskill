"""Pool runs of one suite from several machines into one table per model and condition.

A workshop runs the same suite on a dozen laptops, each with whatever models it can serve. No single
run says much — one repeat of three tasks is three coin flips — but the same suite, the same
components and the same verifiers pooled across machines is a sample worth an interval. So this
refuses runs whose suite content or component versions differ, rather than averaging two different
experiments into one number.

Thinking on and off are pooled as two entrants, never one: the same weights reasoning and not
reasoning are different experiments. So are one model's runs under two harnesses, which differ in
system prompt, tools and loop; where a model ran under more than one, a same-model table sets its
harnesses side by side, and that table is where the harness is the thing compared. Runs that capped
a turn's output differently are pooled with a warning.

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
import statistics
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import present, rawlog
from .catalogue import Catalogue
from .compare import CompareError, LoadedRun, Rate
from .runner.base import ROUTED
from .score.route import UNSCORED, first_activation, same


class LeaderboardError(CompareError):
    """Runs that cannot be pooled."""


#: What a run that predates the harness field ran in.
DEFAULT_HARNESS = "opencode"


def harness_of(run: LoadedRun) -> str:
    return run.manifest.get("harness") or DEFAULT_HARNESS


@dataclass
class Cell:
    """One model under one harness and condition, pooled over every run that ran it.

    `model` is the entrant as the ranking names it; `served` is the model alone, which is what the
    same-model table matches harnesses on.
    """

    model: str
    condition: str
    harness: str = DEFAULT_HARNESS
    served: str = ""
    #: the model as the runs named it, with no thinking or harness label: what a catalogue keys on
    base: str = ""
    passed: int = 0
    total: int = 0
    #: units whose first activation was checked against the expected component, under ROUTED
    routed: int = 0
    routed_first: int = 0
    not_run: int = 0
    runs: set[str] = field(default_factory=set)
    contexts: set[int] = field(default_factory=set)
    #: every unit by outcome class, the ones that did not run included
    outcomes: Counter = field(default_factory=Counter)
    #: of units that ran
    durations_ms: list[int] = field(default_factory=list)
    tokens_in: list[int] = field(default_factory=list)
    tokens_out: list[int] = field(default_factory=list)
    #: every token count of the units that ran, summed by kind
    tokens: Counter = field(default_factory=Counter)

    @property
    def rate(self) -> Rate:
        return Rate(passed=self.passed, total=self.total)

    @property
    def route(self) -> Rate:
        return Rate(passed=self.routed_first, total=self.routed)

    def as_dict(self) -> dict[str, Any]:
        return {
            "model": self.model,
            "served": self.served or self.model,
            "harness": self.harness,
            "condition": self.condition,
            **self.rate.as_dict(),
            "route@1": self.route.as_dict(),
            "not_run": self.not_run,
            "runs": sorted(self.runs),
            "context_tokens": sorted(self.contexts),
            "outcomes": dict(sorted(self.outcomes.items())),
            "median_duration_ms": median(self.durations_ms),
            "median_tokens": {"input": median(self.tokens_in), "output": median(self.tokens_out)},
        }


def median(values: list[int]) -> float | None:
    """The median, or None for nothing: one runaway generation would swamp a mean."""
    return statistics.median(values) if values else None


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
    #: (task, model, condition) → the counts of `cells` for one task, which a run's report reads
    task_cells: dict[tuple[str, str, str], Cell] = field(default_factory=dict)
    #: task → how its units are judged: `verifier` or `route`
    bases: dict[str, str] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    #: models that failed preflight, and models that passed it but ran no unit, per run
    preflight: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    catalogue: Catalogue | None = None

    def described(self, cell: Cell) -> dict[str, Any]:
        """A cell's family, size and shape from the catalogue, when there is one."""
        if self.catalogue is None:
            return {}
        info = self.catalogue.get(cell.base or cell.model)
        return info.as_dict() if info else {"family": None, "size_b": None, "shape": None}

    @property
    def models_in_order(self) -> list[str]:
        """Entrants by name, or grouped by family and ordered by size with a catalogue."""
        models = sorted({cell.model for cell in self.cells.values()})
        if self.catalogue is None:
            return models
        base = {cell.model: cell.base or cell.model for cell in self.cells.values()}
        ordered = self.catalogue.order(sorted(set(base.values())))
        return sorted(models, key=lambda m: (ordered.index(base[m]), m))

    @property
    def uncatalogued(self) -> list[str]:
        if self.catalogue is None:
            return []
        return sorted(
            {c.base for c in self.cells.values() if c.base and not self.catalogue.get(c.base)}
        )

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

    @property
    def harnesses(self) -> list[str]:
        return sorted({harness_of(run) for run in self.runs})

    def across_harnesses(self) -> list[dict[str, Any]]:
        """Each model that ran under more than one harness, per condition, harnesses side by side.

        Matched on the served model and its thinking setting, so a row compares one model's weights
        and settings under two harnesses and nothing else that the runs record.
        """
        grouped: dict[tuple[str, str], dict[str, Cell]] = {}
        for cell in self.cells.values():
            grouped.setdefault((cell.served, cell.condition), {})[cell.harness] = cell
        return [
            {
                "model": served,
                "condition": condition,
                "harnesses": {
                    harness: {
                        **cell.rate.as_dict(),
                        "route@1": cell.route.as_dict(),
                        "not_run": cell.not_run,
                    }
                    for harness, cell in sorted(by_harness.items())
                },
            }
            for (served, condition), by_harness in sorted(grouped.items())
            if len(by_harness) > 1
        ]

    def as_dict(self) -> dict[str, Any]:
        return {
            "suite": self.suite,
            "suite_hash": self.suite_hash,
            "harnesses": self.harnesses,
            "runs": [
                {
                    "run_id": run.run_id,
                    "harness": harness_of(run),
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
                    {**cell.as_dict(), **self.described(cell), "clear_of_leader": clear}
                    for cell, clear in self.ranked(condition)
                ]
                for condition in self.conditions
            },
            "matrix": [
                {"task_id": task, "model": model, "condition": condition, **rate.as_dict()}
                for (task, model, condition), rate in sorted(self.matrix.items())
            ],
            "across_harnesses": self.across_harnesses(),
            "preflight": self.preflight,
            **(
                {"catalogue": self.catalogue.source, "uncatalogued": self.uncatalogued}
                if self.catalogue
                else {}
            ),
            "warnings": self.warnings,
        }


# --------------------------------------------------------------------------- pooling


def pool(runs: list[LoadedRun], catalogue: Catalogue | None = None) -> Leaderboard:
    """Pool runs of one suite, refusing any that measured something else."""
    check_suite(runs)
    first = runs[0]
    board = Leaderboard(
        suite=first.suite,
        suite_hash=first.suite_hash,
        runs=list(runs),
        components=components(runs),
        catalogue=catalogue,
    )
    board.warnings += run_warnings(runs)
    board.preflight = preflight_summary(runs)
    for run in runs:
        contexts = _contexts(run)
        labels = entrant_labels(run, several=len(board.harnesses) > 1)
        for result in run.results:
            _add(board, run, result, contexts, labels)
    return board


def preflight_summary(runs: list[LoadedRun]) -> dict[str, list[dict[str, Any]]]:
    """Models a pooled rate leaves out: those that failed preflight, and those that passed but ran
    nothing, each with the run it was in.

    A model that failed in one run and passed in another is listed for the run it failed in, since
    its pooled rate omits that run.
    """
    failed, idle = [], []
    for run in runs:
        ran = {result["model"] for result in run.results}
        refused = preflight_failures(run.manifest)
        for model in sorted(run.manifest.get("preflight") or {}):
            if model in refused:
                failed.append({"model": model, "run_id": run.run_id, "problems": refused[model]})
            elif model not in ran:
                idle.append({"model": model, "run_id": run.run_id})
    return {"failed": failed, "no_units": idle}


def preflight_failures(manifest: dict[str, Any]) -> dict[str, list[str]]:
    """Each model a run's preflight did not pass, with its problems.

    The one reading of `run.json`'s `preflight`, for the report and the pooled outputs alike: an
    entry that does not say `ok`, a missing or empty one included, did not pass.
    """
    return {
        model: list((entry or {}).get("problems") or ["preflight failed"])
        for model, entry in (manifest.get("preflight") or {}).items()
        if not (entry or {}).get("ok")
    }


def check_suite(runs: list[LoadedRun]) -> None:
    """Refuse runs of different suites, or of different content of one suite."""
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


def run_warnings(runs: list[LoadedRun]) -> list[str]:
    """What pooling these runs leaves unverified or mixed, without refusing them."""
    warnings = []
    if not runs[0].suite_hash:
        warnings.append("no run recorded a suite_hash, so the suite content is unverified")
    for harness in sorted({harness_of(run) for run in runs}):
        versions = {
            run.manifest.get("harness_version") for run in runs if harness_of(run) == harness
        }
        if len(versions) > 1:
            warnings.append(
                f"the runs used different {harness} versions: "
                + ", ".join(sorted(str(v) for v in versions))
            )
    caps = {(run.manifest.get("options") or {}).get("max_output_tokens") for run in runs}
    if len(caps) > 1:
        warnings.append(
            "the runs capped a model turn differently: "
            + ", ".join(sorted(str(cap) for cap in caps))
            + " output tokens"
        )
    return warnings


def entrant_labels(run: LoadedRun, *, several: bool) -> tuple[str, str, str]:
    """The thinking suffix, the entrant suffix and the harness for one run's units.

    The harness is named in the entrant only when the runs pooled used more than one.
    """
    thinking = _thinking_label(run)
    harness = harness_of(run)
    return thinking, thinking + (f" [{harness}]" if several else ""), harness


def _thinking_label(run: LoadedRun) -> str:
    """What a model is called in this run's rows: thinking on and off are two different entrants."""
    thinking = (run.manifest.get("options") or {}).get("thinking")
    return f" (thinking {thinking})" if thinking in ("on", "off") else ""


def components(runs: list[LoadedRun], *, vary: str | None = None) -> dict[str, str | None]:
    """Every component under test and its one version, or a refusal naming the runs that differ.

    ``vary`` is the one component whose versions may differ, for a board ranking its versions; it
    is left out of what is returned.
    """
    seen: dict[str, tuple[str | None, str]] = {}
    for run in runs:
        for name, digest in run.hashes().items():
            if name == vary:
                continue
            if name not in seen:
                seen[name] = (digest, run.run_id)
                continue
            known, where = seen[name]
            if known != digest:
                hint = (
                    f"Only {vary} may differ on this board."
                    if vary
                    else "Pool runs of one version; `wikiskill compare` is for two."
                )
                raise LeaderboardError(
                    f"{name} differs between runs: {_short(known)} in {where}, {_short(digest)} in "
                    f"{run.run_id}. {hint}"
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


def _add(
    board: Leaderboard,
    run: LoadedRun,
    result: dict[str, Any],
    contexts: dict,
    labels: tuple[str, str, str],
) -> None:
    """Count one unit. `labels` is the thinking suffix, the entrant suffix, and the harness."""
    thinking, label, harness = labels
    served, condition, task = result["model"], result["condition"], result["task_id"]
    model = served + label

    def fresh() -> Cell:
        return Cell(
            model=model,
            condition=condition,
            harness=harness,
            served=served + thinking,
            base=served,
        )

    verdict, basis = unit_verdict(result)
    for cell in (
        board.cells.setdefault((model, condition), fresh()),
        board.task_cells.setdefault((task, model, condition), fresh()),
    ):
        _tally(cell, run, result, contexts, verdict)
    if verdict is None or result.get("outcome") in UNSCORED:
        return
    board.bases.setdefault(task, basis)
    rate = board.matrix.get((task, model, condition), Rate(0, 0))
    board.matrix[(task, model, condition)] = Rate(
        passed=rate.passed + (1 if verdict else 0), total=rate.total + 1
    )


def _tally(
    cell: Cell, run: LoadedRun, result: dict[str, Any], contexts: dict, verdict: bool | None
) -> None:
    """One unit into one cell: its outcome, its cost, its route, and its verdict."""
    cell.runs.add(run.run_id)
    if result["model"] in contexts:
        cell.contexts.add(contexts[result["model"]])
    cell.outcomes[result.get("outcome") or "unknown"] += 1
    if result.get("outcome") in UNSCORED:
        cell.not_run += 1
        return
    _cost(cell, result)
    expected = (result.get("expected") or {}).get("primary")
    if expected and cell.condition == ROUTED:
        cell.routed += 1
        cell.routed_first += 1 if same(first_activation(result), expected) else 0
    if verdict is None:
        return
    cell.passed += 1 if verdict else 0
    cell.total += 1


def _cost(cell: Cell, result: dict[str, Any]) -> None:
    """Time and tokens of a unit that ran, where it recorded them."""
    if isinstance(result.get("duration_ms"), int):
        cell.durations_ms.append(result["duration_ms"])
    tokens = result.get("tokens") or {}
    cell.tokens.update({kind: n for kind, n in tokens.items() if isinstance(n, int)})
    if isinstance(tokens.get("input"), int):
        cell.tokens_in.append(tokens["input"])
    if isinstance(tokens.get("output"), int):
        cell.tokens_out.append(tokens["output"])


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


def ranking_lines(ranking: dict[str, list[dict[str, Any]]]) -> list[str]:
    """The pooled table per condition, from `as_dict()["ranking"]`.

    Shared by the leaderboard and a single run's report, which stores it as data.
    """
    lines: list[str] = []
    for condition, entries in sorted(ranking.items()):
        if not entries:
            continue
        described = any("family" in entry for entry in entries)
        lines += [
            f"### {condition}",
            "",
            "| # | model | "
            + ("family | size (B) | " if described else "")
            + "passed (95% CI) | not run | median s | runs | context |",
            "|---|---|" + ("---|---|" if described else "") + "---|---|---|---|---|",
        ]
        for place, entry in enumerate(entries, start=1):
            mark = str(place) if place == 1 or entry["clear_of_leader"] else f"{place}≈"
            rate = Rate(passed=entry["passed"], total=entry["total"])
            contexts = (
                ", ".join(f"{c // 1024}k" for c in entry["context_tokens"]) or present.MISSING
            )
            seconds = entry.get("median_duration_ms")
            about = (
                f"{entry.get('family') or 'uncatalogued'} | {_size(entry.get('size_b'))} | "
                if described
                else ""
            )
            lines.append(
                f"| {mark} | {entry['model']} | {about}{present.of(rate)} | {entry['not_run']} | "
                f"{present.seconds(seconds)} | "
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
    data = board.as_dict()
    lines += preflight_lines(board.preflight)
    if board.catalogue:
        lines += [f"- model catalogue: `{board.catalogue.source}`"]
        if board.uncatalogued:
            lines += [f"- uncatalogued: {', '.join(board.uncatalogued)}"]
        lines.append("")
    lines += ["## Ranking", "", *ranking_lines(data["ranking"])]
    lines += across_harness_lines(board.across_harnesses())
    lines += outcome_lines(data["ranking"], board.models_in_order)
    lines += _matrix_lines(board)
    return "\n".join(lines)


def preflight_lines(preflight: dict[str, list[dict[str, Any]]]) -> list[str]:
    """Models the pooled rates leave out, from `preflight_summary`."""
    failed, idle = preflight.get("failed") or [], preflight.get("no_units") or []
    if not failed and not idle:
        return []
    lines = ["## Not in the rates", ""]
    for entry in failed:
        why = "; ".join(str(problem) for problem in entry["problems"]) or "no reason recorded"
        lines.append(f"- {entry['model']} failed preflight in `{entry['run_id']}`: {why}")
    for entry in idle:
        lines.append(f"- {entry['model']} passed preflight in `{entry['run_id']}` but ran no unit")
    return [*lines, ""]


def outcome_lines(
    ranking: dict[str, list[dict[str, Any]]], order: list[str] | None = None
) -> list[str]:
    """Each model's units by outcome class, with median time and tokens of the units that ran.

    What tells a model that cannot drive the harness (`permission_blocked`, `step_exhausted`,
    `infra_error`) from one that drives it and gets the task wrong (`completed`, failed).
    """
    rows = [(condition, e) for condition, entries in sorted(ranking.items()) for e in entries]
    if not rows:
        return []
    classes = sorted({name for _, entry in rows for name in entry.get("outcomes") or {}})
    lines = [
        "## Outcomes and cost",
        "",
        "Medians are of the units that ran.",
        "",
        "| model | condition | " + " | ".join(classes) + " | median s | median tokens in/out |",
        "|---|---|" + "---|" * len(classes) + "---|---|",
    ]
    place = {model: index for index, model in enumerate(order or [])}
    rows.sort(key=lambda r: (place.get(r[1]["model"], len(place)), r[1]["model"], r[0]))
    for condition, entry in rows:
        counts = [str((entry.get("outcomes") or {}).get(name, 0)) for name in classes]
        seconds = entry.get("median_duration_ms")
        tokens = entry.get("median_tokens") or {}
        lines.append(
            f"| {entry['model']} | {condition} | " + " | ".join(counts) + " | "
            f"{present.seconds(seconds)} | "
            f"{_count(tokens.get('input'))}/{_count(tokens.get('output'))} |"
        )
    return [*lines, ""]


def _size(value: float | None) -> str:
    return present.value(value, "g")


def _count(value: float | None) -> str:
    return present.value(value, ".0f")


def across_harness_lines(rows: list[dict[str, Any]]) -> list[str]:
    """One model under each harness it ran in, from `as_dict()["across_harnesses"]`."""
    if not rows:
        return []
    lines = [
        "## Same model across harnesses",
        "",
        (
            "Each row is one model under one condition; route@1 counts ROUTED units whose first "
            "activation was the expected component. Only the harness differs within a row, so "
            "this is the table to read for a harness effect; overlapping intervals show none."
        ),
        "",
        "| model | condition | harness | passed (95% CI) | route@1 (95% CI) | not run |",
        "|---|---|---|---|---|---|",
    ]
    for row in rows:
        for harness, entry in row["harnesses"].items():
            rate = Rate(passed=entry["passed"], total=entry["total"])
            route = Rate(passed=entry["route@1"]["passed"], total=entry["route@1"]["total"])
            lines.append(
                f"| {row['model']} | {row['condition']} | {harness} | {present.of(rate)} | "
                f"{present.of(route)} | {entry['not_run']} |"
            )
    return [*lines, ""]


def _matrix_lines(board: Leaderboard) -> list[str]:
    seen = {model for _, model, _ in board.matrix}
    models = [model for model in board.models_in_order if model in seen]
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
            cells = [present.count_of(r) for r in rates]
            basis = board.bases.get(task, present.MISSING)
            lines.append(f"| {task} | {basis} | " + " | ".join(cells) + " |")
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
