"""Rank several versions of one component across models: the best for each model, and overall.

The gate judges one candidate against one baseline. A sweep with several candidates over many models
asks something it cannot: which version is best, for each model and overall? This pools runs that
differ only in that component's version, the way the leaderboard pools runs across machines, and
puts versions on a second axis beside models.

One condition is ranked, the one in which the component is in use (INJECTED, or ROUTED). OFF does
not load the component, so its units are pooled across every version of a model and shown once, as
that model's control; a candidate run can therefore skip OFF.

"Best" is guarded three ways, because the top of several noisy versions is flattered by noise:
- per model, the best version is reported with its direction against the baseline, and a top place
  whose interval overlaps the baseline's says `no detectable difference`;
- overall, a version that regresses any model is ranked but never named best, whatever its mean;
- a version that fails a critical check once, on any model, is never named best at all.

Nothing is decided here. The board ranks; `proposal decide` still records what is accepted.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from . import diff, paths, rawlog
from .compare import DOWN, SAME, LoadedRun, Rate, direction
from .gate import DEFAULT_TOLERANCE
from .leaderboard import (
    LeaderboardError,
    _fmt,
    _short,
    check_suite,
    components,
    entrant_labels,
    harness_of,
    output_name,
    run_warnings,
    unit_verdict,
)
from .runner.base import INJECTED, OFF, ROUTED
from .score.route import UNSCORED

#: The conditions a board can rank: those in which the component is in use.
RANKABLE = (INJECTED, ROUTED)
#: A critical-check entry that applies to every task.
EVERY_TASK = "*"


class BoardError(LeaderboardError):
    """Runs or checks a version board cannot use."""


# --------------------------------------------------------------------------- critical checks


@dataclass(frozen=True)
class Critical:
    """Verifiers that must never fail, named by task id (or `*`) and 0-based declaration index."""

    entries: tuple[tuple[str, int], ...]
    source: str = ""
    content_hash: str | None = None

    def indices(self, task: str) -> list[int]:
        return sorted({index for name, index in self.entries if name in (task, EVERY_TASK)})

    def as_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "content_hash": self.content_hash,
            "entries": [{"task": task, "verifier": index} for task, index in self.entries],
        }


def load_critical(path: str | Path) -> Critical:
    """A critical-check file: a YAML list of `{task: <id or *>, verifier: <index>}`."""
    path = Path(path)
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise BoardError(f"cannot read critical checks {path}: {exc}") from exc
    try:
        document = yaml.safe_load(data)
    except yaml.YAMLError as exc:
        raise BoardError(f"{path} is not valid YAML: {exc}") from exc
    if not isinstance(document, list) or not document:
        raise BoardError(f"{path} must be a non-empty list of {{task, verifier}} entries")
    entries = []
    for number, entry in enumerate(document, start=1):
        if not isinstance(entry, dict) or set(entry) != {"task", "verifier"}:
            raise BoardError(f"{path} entry {number}: expected exactly `task` and `verifier`")
        task, index = entry["task"], entry["verifier"]
        if not isinstance(task, str) or not task:
            raise BoardError(f"{path} entry {number}: `task` must be a task id or `*`")
        if not isinstance(index, int) or isinstance(index, bool) or index < 0:
            raise BoardError(f"{path} entry {number}: `verifier` must be a 0-based index")
        entries.append((task, index))
    return Critical(tuple(entries), source=str(path), content_hash=rawlog.content_hash(data))


def _verifier_counts(runs: list[LoadedRun]) -> dict[str, int]:
    """How many verifiers each task's units recorded, which is how many the task declares."""
    counts: dict[str, int] = {}
    for run in runs:
        for result in run.results:
            recorded = result.get("verifiers") or []
            task = result["task_id"]
            counts[task] = max(counts.get(task, 0), len(recorded))
    return counts


def _check_critical(critical: Critical, runs: list[LoadedRun]) -> None:
    """Refuse an entry naming a verifier that a task, as these runs recorded it, does not have."""
    counts = _verifier_counts(runs)
    for task, index in critical.entries:
        if task == EVERY_TASK:
            short = sorted(t for t, n in counts.items() if n and n <= index)
            if short:
                raise BoardError(
                    f"critical check `*` verifier {index}: task(s) {', '.join(short)} have fewer "
                    f"than {index + 1} verifiers"
                )
            continue
        if task not in counts:
            raise BoardError(f"critical check names task {task!r}, which none of the runs ran")
        if counts[task] <= index:
            raise BoardError(
                f"critical check names verifier {index} of {task!r}, which records "
                f"{counts[task]} verifier(s)"
            )


# --------------------------------------------------------------------------- the board


@dataclass(frozen=True)
class Entry:
    """One version on one model."""

    version: str
    rate: Rate
    lift: float | None
    direction: str
    regression: bool
    disqualified: bool
    not_run: int


@dataclass
class VersionBoard:
    component: str
    condition: str
    baseline: str
    suite: str | None
    suite_hash: str | None
    runs: list[LoadedRun]
    #: every other component under test, and its one version
    others: dict[str, str | None]
    #: versions in the order they are shown: the baseline first, then by first appearance
    versions: list[str] = field(default_factory=list)
    labels: dict[str, str] = field(default_factory=dict)
    #: model → OFF units pooled across versions
    control: dict[str, Rate] = field(default_factory=dict)
    #: (model, version) → ranked-condition rate
    cells: dict[tuple[str, str], Rate] = field(default_factory=dict)
    #: (model, version) → units that did not run
    not_run: dict[tuple[str, str], int] = field(default_factory=dict)
    #: (model, version, task) → rate
    matrix: dict[tuple[str, str, str], Rate] = field(default_factory=dict)
    #: every unit behind a figure, so a report can be recomputed without the runs
    units: list[dict[str, Any]] = field(default_factory=list)
    critical: Critical | None = None
    #: version → units that failed a critical check
    failures: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    tolerance: float = DEFAULT_TOLERANCE
    warnings: list[str] = field(default_factory=list)

    def label(self, version: str) -> str:
        return self.labels.get(version) or _short(version)

    @property
    def models(self) -> list[str]:
        """Every model with a unit on the board, scored or not run."""
        return sorted({model for model, _ in self.cells} | {model for model, _ in self.not_run})

    @property
    def panel(self) -> list[str]:
        """Models on which every version ran: the only ones an overall figure may average."""
        return [
            model
            for model in self.models
            if all(self.cells.get((model, version), Rate(0, 0)).total for version in self.versions)
        ]

    @property
    def left_out(self) -> list[str]:
        panel = set(self.panel)
        return [model for model in self.models if model not in panel]

    def disqualified(self, version: str) -> bool:
        return bool(self.failures.get(version))

    def regression(self, model: str, version: str) -> bool:
        """`down` against the baseline on the model, or any task fallen beyond the tolerance.

        The tolerance is the gate's, which is per task on one model: one task collapsing is a
        regression even when the model's rate over every task barely moves.
        """
        base = self.cells.get((model, self.baseline))
        here = self.cells.get((model, version))
        if version == self.baseline or not base or not here or not base.total or not here.total:
            return False
        return direction(base, here) == DOWN or bool(self.fallen_tasks(model, version))

    def fallen_tasks(self, model: str, version: str) -> list[str]:
        """Tasks whose rate on ``model`` fell below the baseline's by more than the tolerance."""
        fallen = []
        for task in self.tasks:
            base = self.matrix.get((model, self.baseline, task))
            here = self.matrix.get((model, version, task))
            if not base or not here or not base.total or not here.total:
                continue
            if (base.rate or 0.0) - (here.rate or 0.0) > self.tolerance + 1e-9:
                fallen.append(task)
        return fallen

    @property
    def tasks(self) -> list[str]:
        return sorted({task for _, _, task in self.matrix})

    def entries(self, model: str) -> list[Entry]:
        """Every version that ran on one model, in board order."""
        base = self.cells.get((model, self.baseline))
        control = self.control.get(model)
        found = []
        for version in self.versions:
            rate = self.cells.get((model, version)) or Rate(0, 0)
            not_run = self.not_run.get((model, version), 0)
            if not rate.total and not not_run:
                continue
            lift = (
                (rate.rate or 0.0) - (control.rate or 0.0)
                if rate.total and control and control.total
                else None
            )
            moved = (
                SAME
                if version == self.baseline or not base or not rate.total
                else direction(base, rate)
            )
            found.append(
                Entry(
                    version=version,
                    rate=rate,
                    lift=lift,
                    direction=moved,
                    regression=self.regression(model, version),
                    disqualified=self.disqualified(version),
                    not_run=not_run,
                )
            )
        return found

    def best(self, model: str) -> Entry | None:
        """The highest point estimate among versions not disqualified; ties go to the earlier."""
        eligible = [e for e in self.entries(model) if e.rate.total and not e.disqualified]
        if not eligible:
            return None
        return max(eligible, key=lambda e: (e.rate.rate or 0.0, -self.versions.index(e.version)))

    def overall(self) -> list[dict[str, Any]]:
        """Each version: its mean and cells won and lost over the panel, and models it regresses.

        Regressions are looked for on every model the version and the baseline both ran, not only
        the panel: a model left out of the mean can still be one the version broke.
        """
        panel = self.panel
        rows = []
        for version in self.versions:
            rates = [self.cells[(model, version)].rate or 0.0 for model in panel]
            won, lost = self._cells_against_baseline(version, panel)
            rows.append(
                {
                    "version": version,
                    "label": self.label(version),
                    "mean": sum(rates) / len(rates) if rates else None,
                    "won": won,
                    "lost": lost,
                    "sign_test_p": sign_test(won, lost) if version != self.baseline else None,
                    "regressions": [m for m in self.models if self.regression(m, version)],
                    "disqualified": self.disqualified(version),
                }
            )
        return rows

    def best_overall(self) -> dict[str, Any] | None:
        """The highest panel mean among versions not disqualified that regress no model."""
        if not self.panel:
            return None
        eligible = [
            row
            for row in self.overall()
            if not row["disqualified"] and not row["regressions"] and row["mean"] is not None
        ]
        if not eligible:
            return None
        return max(eligible, key=lambda r: (r["mean"], -self.versions.index(r["version"])))

    def _cells_against_baseline(self, version: str, panel: list[str]) -> tuple[int, int]:
        """Panel (model, task) cells where this version's rate rose above or fell below the base."""
        if version == self.baseline:
            return 0, 0
        won = lost = 0
        tasks = self.tasks
        for model in panel:
            for task in tasks:
                base = self.matrix.get((model, self.baseline, task))
                here = self.matrix.get((model, version, task))
                if not base or not here or not base.total or not here.total:
                    continue
                if (here.rate or 0.0) > (base.rate or 0.0):
                    won += 1
                elif (here.rate or 0.0) < (base.rate or 0.0):
                    lost += 1
        return won, lost

    def as_dict(self) -> dict[str, Any]:
        best = self.best_overall()
        return {
            "component": self.component,
            "condition": self.condition,
            "baseline": {"version": self.baseline, "label": self.label(self.baseline)},
            "suite": self.suite,
            "suite_hash": self.suite_hash,
            "runs": [
                {
                    "run_id": run.run_id,
                    "harness": harness_of(run),
                    "version": run.hashes().get(self.component),
                    "proposal": run.manifest.get("proposal"),
                }
                for run in self.runs
            ],
            "other_components": self.others,
            "versions": [{"version": v, "label": self.label(v)} for v in self.versions],
            "versions_compared": len(self.versions),
            "tolerance": self.tolerance,
            "panel": self.panel,
            "left_out": self.left_out,
            "per_model": {
                model: {
                    "control": self.control[model].as_dict() if model in self.control else None,
                    "versions": [
                        {
                            "version": entry.version,
                            "label": self.label(entry.version),
                            **entry.rate.as_dict(),
                            "lift": entry.lift,
                            "direction": entry.direction,
                            "regression": entry.regression,
                            "disqualified": entry.disqualified,
                            "not_run": entry.not_run,
                        }
                        for entry in self.entries(model)
                    ],
                    "best": _best_dict(self, self.best(model)),
                }
                for model in self.models
            },
            "overall": self.overall(),
            "best_overall": (
                {"version": best["version"], "label": best["label"], "mean": best["mean"]}
                if best
                else None
            ),
            "matrix": [
                {"model": model, "version": version, "task_id": task, **rate.as_dict()}
                for (model, version, task), rate in sorted(self.matrix.items())
            ],
            "critical": self.critical.as_dict() if self.critical else None,
            "critical_failures": {
                version: units for version, units in self.failures.items() if units
            },
            "units": self.units,
            "warnings": self.warnings,
        }


def _best_dict(board: VersionBoard, entry: Entry | None) -> dict[str, Any] | None:
    if entry is None:
        return None
    return {
        "version": entry.version,
        "label": board.label(entry.version),
        "direction": entry.direction,
    }


def sign_test(won: int, lost: int) -> float:
    """Two-sided exact sign test on the cells that moved; 1.0 when none did."""
    moved = won + lost
    if moved == 0:
        return 1.0
    tail = sum(math.comb(moved, i) for i in range(min(won, lost) + 1)) / 2**moved
    return round(min(1.0, 2 * tail), 6)


# --------------------------------------------------------------------------- pooling


def pool(
    runs: list[LoadedRun],
    component: str,
    *,
    condition: str = INJECTED,
    baseline: str | None = None,
    labels: dict[str, str] | None = None,
    critical: Critical | None = None,
    tolerance: float = DEFAULT_TOLERANCE,
) -> VersionBoard:
    """Pool runs that differ only in ``component``'s version, refusing any that differ otherwise.

    ``baseline`` is a full `source_hash`; by default the version of the first run given.
    """
    if condition not in RANKABLE:
        raise BoardError(
            f"a board ranks {' or '.join(RANKABLE)}, the conditions that use the component; "
            f"not {condition!r}"
        )
    check_suite(runs)
    others = components(runs, vary=component)
    missing = [run.run_id for run in runs if not run.hashes().get(component)]
    if missing:
        raise BoardError(
            f"{', '.join(missing)} recorded no source_hash for {component}, so the version it ran "
            "is unknown"
        )
    if critical:
        _check_critical(critical, runs)

    versions: list[str] = []
    for run in runs:
        version = run.hashes()[component]
        if version not in versions:
            versions.append(version)  # type: ignore[arg-type]
    chosen = baseline or versions[0]
    if chosen not in versions:
        ran = ", ".join((labels or {}).get(v) or _short(v) for v in versions)
        raise BoardError(
            f"the baseline {_short(chosen)} is not a version any of these runs ran of {component}; "
            f"they ran {ran}. Name one with --baseline"
        )
    versions.remove(chosen)

    board = VersionBoard(
        component=component,
        condition=condition,
        baseline=chosen,
        suite=runs[0].suite,
        suite_hash=runs[0].suite_hash,
        runs=list(runs),
        others=others,
        versions=[chosen, *versions],
        labels=dict(labels or {}),
        critical=critical,
        tolerance=tolerance,
    )
    board.warnings += run_warnings(runs)
    several = len({harness_of(run) for run in runs}) > 1
    ignored: set[str] = set()
    for run in runs:
        version = run.hashes()[component] or ""
        _, entrant, _ = entrant_labels(run, several=several)
        for result in run.results:
            unit_condition = result["condition"]
            if unit_condition not in (OFF, condition):
                ignored.add(unit_condition)
                continue
            _add(board, run, result, version, result["model"] + entrant)
    if ignored:
        board.warnings.append(
            f"units under {', '.join(sorted(ignored))} are not on this board, which ranks "
            f"{condition} against OFF"
        )
    return board


def _add(
    board: VersionBoard, run: LoadedRun, result: dict[str, Any], version: str, model: str
) -> None:
    condition, task = result["condition"], result["task_id"]
    if result.get("outcome") in UNSCORED:
        if condition != OFF:
            key = (model, version)
            board.not_run[key] = board.not_run.get(key, 0) + 1
        return
    verdict, _ = unit_verdict(result)
    if verdict is None:
        return
    board.units.append(
        {
            "run_id": run.run_id,
            "task_id": task,
            "model": model,
            "condition": condition,
            "repeat": result.get("repeat"),
            "version": None if condition == OFF else version,
            "passed": verdict,
        }
    )
    if condition == OFF:
        board.control[model] = _plus(board.control.get(model), verdict)
        return
    board.cells[(model, version)] = _plus(board.cells.get((model, version)), verdict)
    board.matrix[(model, version, task)] = _plus(board.matrix.get((model, version, task)), verdict)
    if board.critical:
        _critical_failures(board, run, result, version, model)


def _critical_failures(
    board: VersionBoard, run: LoadedRun, result: dict[str, Any], version: str, model: str
) -> None:
    assert board.critical is not None
    recorded = result.get("verifiers") or []
    for index in board.critical.indices(result["task_id"]):
        if index < len(recorded) and recorded[index].get("passed") is False:
            board.failures.setdefault(version, []).append(
                {
                    "run_id": run.run_id,
                    "task_id": result["task_id"],
                    "model": model,
                    "repeat": result.get("repeat"),
                    "verifier": index,
                    "detail": recorded[index].get("detail", ""),
                }
            )


def _plus(rate: Rate | None, passed: bool) -> Rate:
    rate = rate or Rate(0, 0)
    return Rate(passed=rate.passed + (1 if passed else 0), total=rate.total + 1)


# --------------------------------------------------------------------------- labels


def version_labels(collection, component: str, runs: list[LoadedRun]) -> dict[str, str]:
    """`p-NNN` for a proposal's candidate, `current` for the source's version, else a short hash.

    Labelled as `wikiskill diff --list` knows them: from proposals, the runs, and the current file.
    """
    labels = {}
    for version in diff.versions(collection, component, loaded=runs, raw=False):
        name = version.produced_by[0] if version.produced_by else _short(version.source_hash)
        if version.current:
            name = f"{name} (current)" if version.produced_by else "current"
        labels[version.source_hash] = name
    for run in runs:
        proposal = run.manifest.get("proposal")
        version = run.hashes().get(component)
        if proposal and version and version not in labels:
            labels[version] = proposal
    return labels


# --------------------------------------------------------------------------- output


def _pct(value: float | None, *, signed: bool = False) -> str:
    if value is None:
        return "-"
    return f"{value:+.0%}" if signed else f"{value:.0%}"


def render(board: VersionBoard) -> str:
    label = board.label
    lines = [
        f"# Versions of {board.component}: {board.suite}",
        "",
        f"- ranked condition: {board.condition}, against OFF as the control",
        f"- baseline: `{label(board.baseline)}`",
        f"- versions compared: {len(board.versions)}",
        f"- runs: {len(board.runs)} ({', '.join(f'`{run.run_id}`' for run in board.runs)})",
        f"- suite_hash: `{_short(board.suite_hash)}`",
    ]
    lines += [f"- `{name}`: `{_short(digest)}`" for name, digest in board.others.items()]
    if board.critical:
        lines.append(
            f"- critical checks: `{board.critical.source}` "
            f"(`{_short(board.critical.content_hash)}`)"
        )
    lines += [
        "",
        (
            "A unit passes on its verifiers, or, for a task with none, when its first activation "
            "is the expected component. Intervals are Wilson 95%. A direction is `up` or `down` "
            "only when the intervals do not overlap. A regression is `down`, or a fall of more "
            f"than {board.tolerance:.0%} against the baseline. Several versions were compared, so "
            "the top of the table is flattered by noise: confirm it with a fresh run before "
            "relying on it."
        ),
        "",
    ]
    lines += [f"> warning: {warning}" for warning in board.warnings]
    if board.warnings:
        lines.append("")
    lines += _overall_lines(board)
    lines += _per_model_lines(board)
    lines += _critical_lines(board)
    lines += _matrix_lines(board)
    return "\n".join(lines)


def _overall_lines(board: VersionBoard) -> list[str]:
    lines = ["## Overall", ""]
    if not board.panel:
        return [*lines, "No model ran every version, so there is no overall figure.", ""]
    lines += [
        f"Panel: {len(board.panel)} model(s) that ran every version, each weighted equally.",
    ]
    if board.left_out:
        lines.append(f"Left out, missing a version: {', '.join(board.left_out)}.")
    best = board.best_overall()
    lines += [
        "",
        "| version | mean | cells won | cells lost | sign test p | regressions | disqualified |",
        "|---|---|---|---|---|---|---|",
    ]
    for row in sorted(board.overall(), key=lambda r: -(r["mean"] or 0.0)):
        mark = " **best**" if best and row["version"] == best["version"] else ""
        baseline = " (baseline)" if row["version"] == board.baseline else ""
        p = "-" if row["sign_test_p"] is None else f"{row['sign_test_p']:.3g}"
        lines.append(
            f"| `{row['label']}`{baseline}{mark} | {_pct(row['mean'])} | {row['won']} | "
            f"{row['lost']} | {p} | {', '.join(row['regressions']) or '-'} | "
            f"{'yes' if row['disqualified'] else '-'} |"
        )
    lines.append("")
    if best is None:
        lines += [
            "No version is named best overall: each regresses a model or is disqualified.",
            "",
        ]
    return lines


def _per_model_lines(board: VersionBoard) -> list[str]:
    lines = [
        "## Per model",
        "",
        "| model | OFF | version | passed (95% CI) | lift | against baseline | not run | |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for model in board.models:
        best = board.best(model)
        control = _fmt(board.control.get(model) or Rate(0, 0))
        for entry in board.entries(model):
            notes = []
            if best and entry.version == best.version:
                notes.append("**best**")
            if entry.regression:
                notes.append("regression")
            if entry.disqualified:
                notes.append("disqualified")
            if not entry.rate.total:
                notes.append("not run")
            fallen = board.fallen_tasks(model, entry.version)
            if fallen:
                notes.append("fell on " + ", ".join(fallen))
            against = "baseline" if entry.version == board.baseline else entry.direction
            lines.append(
                f"| {model} | {control} | `{board.label(entry.version)}` | {_fmt(entry.rate)} | "
                f"{_pct(entry.lift, signed=True)} | {against} | {entry.not_run} | "
                f"{', '.join(notes)} |"
            )
            control = ""
    return [*lines, ""]


def _critical_lines(board: VersionBoard) -> list[str]:
    failed = {version: units for version, units in board.failures.items() if units}
    if not board.critical:
        return []
    if not failed:
        return ["## Critical checks", "", "No version failed a critical check.", ""]
    lines = ["## Critical checks", ""]
    for version in board.versions:
        for unit in failed.get(version, []):
            lines.append(
                f"- `{board.label(version)}` failed verifier {unit['verifier']} of "
                f"`{unit['task_id']}` on {unit['model']} (run `{unit['run_id']}`, repeat "
                f"{unit['repeat']}): {unit['detail']}"
            )
    return [*lines, ""]


def _matrix_lines(board: VersionBoard) -> list[str]:
    tasks = sorted({task for _, _, task in board.matrix})
    lines = ["## Per task", ""]
    for model in board.models:
        versions = [v for v in board.versions if (model, v) in board.cells]
        lines += [
            f"### {model}",
            "",
            "| task | " + " | ".join(f"`{board.label(v)}`" for v in versions) + " |",
            "|---|" + "---|" * len(versions),
        ]
        for task in tasks:
            rates = [board.matrix.get((model, v, task)) for v in versions]
            if not any(rates):
                continue
            cells = [f"{r.passed}/{r.total}" if r and r.total else "-" for r in rates]
            lines.append(f"| {task} | " + " | ".join(cells) + " |")
        lines.append("")
    return lines


def output_dir(collection: str, board: VersionBoard) -> Path:
    """One directory per run set and setting, so boards ranked differently never overwrite.

    The condition, the baseline and the critical checks each change the figures; all three are in
    the name.
    """
    slug = board.component.replace("/", "-").replace(":", "-")
    name = f"{output_name(board.runs)}-{board.condition}-base-{_short(board.baseline)[:7]}"
    if board.critical:
        name += f"-critical-{_short(board.critical.content_hash)[:7]}"
    return paths.evals_dir(collection) / "versions" / slug / name


def write(board: VersionBoard, out: Path) -> tuple[Path, Path]:
    out.mkdir(parents=True, exist_ok=True)
    md, js = out / "board.md", out / "board.json"
    md.write_text(render(board), encoding="utf-8")
    js.write_text(json.dumps(board.as_dict(), indent=2) + "\n", encoding="utf-8")
    return md, js
