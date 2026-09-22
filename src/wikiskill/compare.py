"""Compare two runs of one suite across versions of a component: the light gate.

A refinement is worth keeping only if the version it produced does better on the same tasks, the
same models and the same conditions. This reads two finished runs and says, per model and pooled,
whether the pass rate moved by more than its uncertainty — and says "no detectable difference" when
it did not, which on a handful of tasks is the usual and honest answer.

Nothing is re-run. The comparison is computed from each run's `run.json`, `results.jsonl`, and the
eval events it appended to the raw log.
"""

from __future__ import annotations

import json
import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import paths, rawlog
from .score.route import UNSCORED

#: 95% two-sided.
Z = 1.959963984540054

UP, DOWN, SAME = "up", "down", "no detectable difference"
POOLED = "pooled"


class CompareError(Exception):
    """Two runs cannot be compared."""


@dataclass(frozen=True)
class LoadedRun:
    run_id: str
    root: Path
    manifest: dict[str, Any]
    results: tuple[dict[str, Any], ...]

    @property
    def suite(self) -> str | None:
        return self.manifest.get("suite")

    @property
    def tasks(self) -> list[str]:
        return list(self.manifest.get("tasks") or sorted({r["task_id"] for r in self.results}))

    def hashes(self) -> dict[str, str | None]:
        return {c["name"]: c.get("source_hash") for c in self.manifest.get("components", [])}


@dataclass(frozen=True)
class Rate:
    passed: int
    total: int

    @property
    def rate(self) -> float | None:
        return self.passed / self.total if self.total else None

    @property
    def interval(self) -> tuple[float, float] | None:
        return wilson(self.passed, self.total)

    def as_dict(self) -> dict[str, Any]:
        low_high = self.interval
        return {
            "passed": self.passed,
            "total": self.total,
            "rate": self.rate,
            "ci95": list(low_high) if low_high else None,
        }


@dataclass
class Comparison:
    a: LoadedRun
    b: LoadedRun
    component: str | None
    hash_a: str | None
    hash_b: str | None
    #: (condition, model or POOLED) → (rate in A, rate in B, direction)
    rows: dict[tuple[str, str], tuple[Rate, Rate, str]] = field(default_factory=dict)
    #: condition → the pooled row with timeouts counted as failures rather than excluded
    with_timeouts: dict[str, tuple[Rate, Rate, str]] = field(default_factory=dict)
    #: (condition, run label) → {tool key: units that used it}, and units in that cell
    tools: dict[tuple[str, str], tuple[dict[str, int], int]] = field(default_factory=dict)
    unmatched_models: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def pooled(self, condition: str) -> tuple[Rate, Rate, str] | None:
        return self.rows.get((condition, POOLED))

    def as_dict(self) -> dict[str, Any]:
        return {
            "suite": self.a.suite,
            "a": {"run_id": self.a.run_id, "source_hash": self.hash_a},
            "b": {"run_id": self.b.run_id, "source_hash": self.hash_b},
            "component": self.component,
            "rows": [
                {
                    "condition": condition,
                    "model": model,
                    "a": ra.as_dict(),
                    "b": rb.as_dict(),
                    "direction": direction,
                }
                for (condition, model), (ra, rb, direction) in sorted(self.rows.items())
            ],
            "with_timeouts_as_failures": {
                condition: {"a": ra.as_dict(), "b": rb.as_dict(), "direction": direction}
                for condition, (ra, rb, direction) in sorted(self.with_timeouts.items())
            },
            "tool_choice": [
                {"condition": condition, "run": label, "units": units, "tools": counts}
                for (condition, label), (counts, units) in sorted(self.tools.items())
            ],
            "unmatched_models": self.unmatched_models,
            "warnings": self.warnings,
        }


# --------------------------------------------------------------------------- statistics


def wilson(passed: int, total: int, z: float = Z) -> tuple[float, float] | None:
    """The Wilson score interval: honest at small n and at 0% or 100%, unlike the normal one."""
    if total <= 0:
        return None
    p = passed / total
    denominator = 1 + z * z / total
    centre = (p + z * z / (2 * total)) / denominator
    half = z * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total)) / denominator
    return max(0.0, centre - half), min(1.0, centre + half)


def direction(a: Rate, b: Rate) -> str:
    """Up or down only when the intervals do not overlap; otherwise say so."""
    ia, ib = a.interval, b.interval
    if ia is None or ib is None:
        return SAME
    if ib[0] > ia[1]:
        return UP
    if ib[1] < ia[0]:
        return DOWN
    return SAME


# --------------------------------------------------------------------------- loading


def load_run(collection: str, run: str | Path) -> LoadedRun:
    """A run by id under the collection's evals directory, or by path."""
    root = Path(run)
    if not root.is_dir():
        root = paths.evals_dir(collection) / str(run)
    manifest_path = root / "run.json"
    if not manifest_path.is_file():
        raise CompareError(f"no run at {root}: it has no run.json")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    results_path = root / "results.jsonl"
    results = []
    if results_path.is_file():
        for line in results_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                results.append(json.loads(line))
    return LoadedRun(
        run_id=manifest.get("run_id") or root.name,
        root=root,
        manifest=manifest,
        results=tuple(results),
    )


# --------------------------------------------------------------------------- comparing


def compare(
    a: LoadedRun,
    b: LoadedRun,
    *,
    component: str | None = None,
    raw_root: Path | None = None,
) -> Comparison:
    if a.suite != b.suite:
        raise CompareError(f"the runs used different suites: {a.suite!r} and {b.suite!r}")
    if sorted(a.tasks) != sorted(b.tasks):
        only_a = sorted(set(a.tasks) - set(b.tasks))
        only_b = sorted(set(b.tasks) - set(a.tasks))
        raise CompareError(
            f"the runs used different tasks of suite {a.suite!r}: only in {a.run_id}: "
            f"{', '.join(only_a) or '-'}; only in {b.run_id}: {', '.join(only_b) or '-'}"
        )

    component = component or _component_under_test(a)
    hash_a, hash_b = a.hashes().get(component or ""), b.hashes().get(component or "")
    comparison = Comparison(a=a, b=b, component=component, hash_a=hash_a, hash_b=hash_b)
    if component is None:
        comparison.warnings.append("no component under test could be identified in run A")
    elif hash_a is not None and hash_a == hash_b:
        comparison.warnings.append(
            f"{component} has the same source_hash in both runs, so this compares repeats of one "
            "version, not two versions"
        )

    models_a = {r["model"] for r in a.results}
    models_b = {r["model"] for r in b.results}
    comparison.unmatched_models = sorted(models_a ^ models_b)
    models = sorted(models_a & models_b)
    conditions = sorted({r["condition"] for r in a.results} & {r["condition"] for r in b.results})

    for condition in conditions:
        for model in [*models, POOLED]:
            ra = _rate(a.results, condition, model, models)
            rb = _rate(b.results, condition, model, models)
            comparison.rows[(condition, model)] = (ra, rb, direction(ra, rb))
        ra = _rate(a.results, condition, POOLED, models, timeouts_fail=True)
        rb = _rate(b.results, condition, POOLED, models, timeouts_fail=True)
        comparison.with_timeouts[condition] = (ra, rb, direction(ra, rb))

    root = raw_root or paths.raw_dir(a.manifest.get("collection") or "")
    events = _eval_tool_calls(root, {a.run_id, b.run_id})
    for label, run in (("A", a), ("B", b)):
        for condition in conditions:
            comparison.tools[(condition, label)] = _tool_choice(
                events.get(run.run_id, {}), run.results, condition, models
            )
    return comparison


def _component_under_test(run: LoadedRun) -> str | None:
    """The one component every task expects, when there is one."""
    expected = {(r.get("expected") or {}).get("primary") for r in run.results} - {None}
    names = list(run.hashes())
    if len(expected) == 1:
        bare = next(iter(expected))
        for name in names:
            if name == bare or name.rsplit("/", 1)[-1] == bare:
                return name
        return bare
    return names[0] if len(names) == 1 else None


def _is_timeout(result: dict[str, Any]) -> bool:
    return result.get("outcome") == "infra_error" and str(result.get("reason") or "").startswith(
        "timed out"
    )


def _rate(
    results: Iterable[dict[str, Any]],
    condition: str,
    model: str,
    models: Sequence[str],
    *,
    timeouts_fail: bool = False,
) -> Rate:
    """Verifier verdicts for one cell. A timeout counts only when asked, and then as a failure."""
    passed = total = 0
    for result in results:
        if result["condition"] != condition or result["model"] not in models:
            continue
        if model != POOLED and result["model"] != model:
            continue
        if timeouts_fail and _is_timeout(result):
            total += 1
            continue
        if result.get("outcome") in UNSCORED or result.get("passed") is None:
            continue
        total += 1
        passed += 1 if result["passed"] else 0
    return Rate(passed=passed, total=total)


# --------------------------------------------------------------------------- tool choice


def tool_key(event: dict[str, Any]) -> str | None:
    """What a tool call chose, at the grain that distinguishes one approach from another.

    A shell command is keyed by its program, and for `git` and `datalad` by the subcommand as well,
    because `datalad save` and `git commit` are different choices that both look like "bash".
    """
    payload = event.get("payload") or {}
    tool = payload.get("tool")
    if not tool:
        return None
    if tool != "bash":
        return tool
    command = str((payload.get("input") or {}).get("command") or "").strip()
    words = command.split()
    if not words:
        return "bash"
    program = words[0].rsplit("/", 1)[-1]
    if program in ("git", "datalad") and len(words) > 1 and not words[1].startswith("-"):
        return f"{program} {words[1]}"
    return program


def _eval_tool_calls(
    raw_root: Path, run_ids: set[str]
) -> dict[str, dict[tuple[str, str, str, int], set[str]]]:
    """Per run: (task, model, condition, repeat) → the tool keys used in that unit."""
    found: dict[str, dict[tuple[str, str, str, int], set[str]]] = {}
    if not raw_root.is_dir():
        return found
    for file in rawlog.log_files(raw_root):
        for event in rawlog.read_events(file):
            meta = event.get("eval") or {}
            run_id = meta.get("run_id")
            if run_id not in run_ids or event.get("type") != "tool_call":
                continue
            key = tool_key(event)
            if key is None:
                continue
            unit = (meta["task_id"], event.get("model") or "", meta["condition"], meta["repeat"])
            found.setdefault(run_id, {}).setdefault(unit, set()).add(key)
    return found


def _tool_choice(
    units: dict[tuple[str, str, str, int], set[str]],
    results: Iterable[dict[str, Any]],
    condition: str,
    models: Sequence[str],
) -> tuple[dict[str, int], int]:
    """How many units of one condition used each tool, out of the units that ran."""
    counts: dict[str, int] = {}
    ran = 0
    for result in results:
        if result["condition"] != condition or result["model"] not in models:
            continue
        if result.get("outcome") == "skipped":
            continue
        ran += 1
        key = (result["task_id"], _event_model(result["model"]), condition, result["repeat"])
        used = units.get(key) or units.get((result["task_id"], result["model"], condition, key[3]))
        for tool in used or ():
            counts[tool] = counts.get(tool, 0) + 1
    return dict(sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))), ran


def _event_model(model: str) -> str:
    """Raw events carry the model without its provider; results carry `provider/model`."""
    return model.split("/", 1)[1] if "/" in model else model


# --------------------------------------------------------------------------- output


def _fmt(rate: Rate) -> str:
    if rate.total == 0:
        return "-"
    low, high = rate.interval or (0.0, 0.0)
    return f"{rate.passed}/{rate.total} ({rate.rate:.0%}, CI {low:.0%}-{high:.0%})"


def render(comparison: Comparison) -> str:
    a, b = comparison.a, comparison.b
    short = lambda h: (h or "?")[:12]  # noqa: E731
    lines = [
        f"# Compare: {a.suite}",
        "",
        f"- component: `{comparison.component or 'unknown'}`",
        f"- A: run `{a.run_id}`, source_hash `{short(comparison.hash_a)}`",
        f"- B: run `{b.run_id}`, source_hash `{short(comparison.hash_b)}`",
        "",
        (
            "Pass rates are verifier verdicts with Wilson 95% intervals. A direction is reported "
            "only when the intervals do not overlap."
        ),
        "",
    ]
    for warning in comparison.warnings:
        lines.append(f"> warning: {warning}")
    if comparison.warnings:
        lines.append("")
    hash_a, hash_b = short(comparison.hash_a), short(comparison.hash_b)
    conditions = sorted({condition for condition, _ in comparison.rows})
    for condition in conditions:
        lines += [
            f"## {condition}",
            "",
            f"| model | A `{hash_a}` | B `{hash_b}` | direction |",
            "|---|---|---|---|",
        ]
        models = sorted(m for c, m in comparison.rows if c == condition and m != POOLED)
        for model in [*models, POOLED]:
            ra, rb, move = comparison.rows[(condition, model)]
            label = f"**{model}**" if model == POOLED else model
            lines.append(f"| {label} | {_fmt(ra)} | {_fmt(rb)} | {move} |")
        ta, tb, tmove = comparison.with_timeouts[condition]
        lines.append(f"| pooled, timeouts as failures | {_fmt(ta)} | {_fmt(tb)} | {tmove} |")
        lines.append("")
        counts_a, units_a = comparison.tools.get((condition, "A"), ({}, 0))
        counts_b, units_b = comparison.tools.get((condition, "B"), ({}, 0))
        keys = sorted(
            set(counts_a) | set(counts_b), key=lambda k: -(counts_a.get(k, 0) + counts_b.get(k, 0))
        )
        if keys:
            lines += [
                f"Tool choice, units that used each tool (A of {units_a}, B of {units_b}):",
                "",
                "| tool | A | B |",
                "|---|---|---|",
            ]
            lines += [f"| `{k}` | {counts_a.get(k, 0)} | {counts_b.get(k, 0)} |" for k in keys]
            lines.append("")
    if comparison.unmatched_models:
        lines.append(
            "Models in only one run, not compared: " + ", ".join(comparison.unmatched_models)
        )
        lines.append("")
    return "\n".join(lines)


def output_dir(collection: str, a: LoadedRun, b: LoadedRun) -> Path:
    return paths.evals_dir(collection) / "compare" / f"{a.run_id}_vs_{b.run_id}"


def write(comparison: Comparison, out: Path) -> tuple[Path, Path]:
    out.mkdir(parents=True, exist_ok=True)
    md, js = out / "compare.md", out / "compare.json"
    md.write_text(render(comparison), encoding="utf-8")
    js.write_text(json.dumps(comparison.as_dict(), indent=2) + "\n", encoding="utf-8")
    return md, js


def record(collection: str, comparison: Comparison, decision: str, proposal: str) -> Path:
    """Append the user's decision to `skill-impact.md`. Applies and reverts nothing."""
    if decision not in ("accept", "reject"):
        raise CompareError(f"a decision is `accept` or `reject`, not {decision!r}")
    target = paths.wiki_dir(collection) / "skill-impact.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.exists():
        target.write_text(
            "# Skill impact\n\nOne entry per decision on a proposal, newest last.\n",
            encoding="utf-8",
        )
    pooled = []
    for condition in sorted({c for c, _ in comparison.rows}):
        ra, rb, move = comparison.rows[(condition, POOLED)]
        pooled.append(f"  - {condition}: {_fmt(ra)} -> {_fmt(rb)}, {move}")
    entry = [
        "",
        f"## {proposal}: {decision}",
        "",
        f"- component: `{comparison.component}`",
        (
            f"- runs: `{comparison.a.run_id}` (`{(comparison.hash_a or '?')[:12]}`) -> "
            f"`{comparison.b.run_id}` (`{(comparison.hash_b or '?')[:12]}`)"
        ),
        f"- recorded: {rawlog.now_ts()}",
        "- pooled:",
        *pooled,
        "",
    ]
    with target.open("a", encoding="utf-8") as handle:
        handle.write("\n".join(entry))
    return target
