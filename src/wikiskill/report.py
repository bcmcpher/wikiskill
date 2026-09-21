"""Turning a run's results into `report.json` and `report.md`.

A report states what was not run as plainly as what was. A suite that skipped half its tasks for a
missing capability, or lost a model to preflight, is not a suite that scored badly — and a
reader who cannot tell those apart will draw the wrong conclusion about a skill. So every skipped,
preflight-failed and `infra_error` combination is listed with its reason, and nothing is presented
as complete that was not.

A pass rate comes from a task's verifiers where it declares any, and falls back to `route@1` where
it does not; `pass_basis` on every row says which, because the two are not comparable.

Routing loss and content value need the INJECTED condition, which `add-explicit-eval` task 3.2 adds;
until then they are reported as not computed rather than silently omitted.
"""

from __future__ import annotations

import json
from collections import Counter
from typing import Any

from . import score as score_mod
from .runner.base import INFRA_OUTCOMES, RunLayout


def build_report(results: list[dict[str, Any]], manifest: dict[str, Any]) -> dict[str, Any]:
    """The whole report as data. `report.md` is a rendering of this and adds nothing."""
    scores = score_mod.score_all(results)
    by_model_condition: dict[tuple[str, str], list[score_mod.RouteScore]] = {}
    for score in scores:
        by_model_condition.setdefault((score.model, score.condition), []).append(score)

    rows = [_row(score, results) for score in scores]
    return {
        "run_id": manifest.get("run_id"),
        "suite": manifest.get("suite"),
        "collection": manifest.get("collection"),
        "harness": manifest.get("harness"),
        "harness_version": manifest.get("harness_version"),
        "wikiskill_version": manifest.get("wikiskill_version"),
        "models": manifest.get("models", []),
        "conditions": manifest.get("conditions", []),
        "duration_s": manifest.get("duration_s"),
        "rows": rows,
        "per_model_condition": {
            f"{model}|{condition}": score_mod.aggregate(group)
            for (model, condition), group in by_model_condition.items()
        },
        "confusion": score_mod.confusion(scores),
        "outcomes": dict(Counter(result["outcome"] for result in results)),
        "derived": _derived(),
        "not_run": not_run(results, manifest),
    }


def _row(score: score_mod.RouteScore, results: list[dict[str, Any]]) -> dict[str, Any]:
    """One task, model and condition: routing, pass rate, tokens, wall time, outcome classes."""
    group = [
        result
        for result in results
        if result["task_id"] == score.task_id
        and result["model"] == score.model
        and result["condition"] == score.condition
    ]
    usable = [result for result in group if result["outcome"] not in INFRA_OUTCOMES]
    tokens = Counter()
    for result in usable:
        tokens.update({k: v for k, v in (result.get("tokens") or {}).items() if isinstance(v, int)})
    pass_rate, pass_basis = _pass(usable, score)
    row = score.as_dict()
    row.update(
        {
            "attempted": len(group),
            "pass_rate": pass_rate,
            "pass_basis": pass_basis,
            "failed_verifiers": _failed_verifiers(usable),
            "tokens": dict(tokens),
            "wall_time_ms": sum(result.get("duration_ms") or 0 for result in usable),
            "outcomes": dict(Counter(result["outcome"] for result in group)),
        }
    )
    return row


def _pass(usable: list[dict[str, Any]], score: score_mod.RouteScore) -> tuple[float | None, str]:
    """A task's pass rate, and what it is based on.

    Verifier-first, as the `eval-scoring` spec requires: where a task declares verifiers their
    verdict *is* the pass/fail outcome, and the route metrics stay on the row as a separate
    dimension rather than standing in for one. A task with no verifiers falls back to `route@1`, and
    a task with neither is not measured at all.

    `pass_basis` says which of the three it was on every row, so a report with verifiers is never
    silently compared against one without.
    """
    verdicts = [result["passed"] for result in usable if result.get("passed") is not None]
    if verdicts:
        return sum(1 for verdict in verdicts if verdict) / len(verdicts), "verifier"
    if score.expected:
        return score.route_at_1, "route"
    return None, "not measured"


def _failed_verifiers(usable: list[dict[str, Any]]) -> list[dict[str, str]]:
    """Which checks failed, deduplicated across repeats.

    Repeats of the same task usually fail the same check for the same reason; listing it once per
    repeat would bury the two distinct failures under ten copies of one.
    """
    failures: dict[tuple[str, str], dict[str, str]] = {}
    for result in usable:
        for verifier in result.get("verifiers") or []:
            if verifier.get("passed"):
                continue
            entry = {"kind": verifier.get("kind", "?"), "detail": verifier.get("detail", "")}
            failures.setdefault((entry["kind"], entry["detail"]), entry)
    return list(failures.values())


def _derived() -> dict[str, Any]:
    return {
        "routing_loss": None,
        "content_value": None,
        "transfer_rate": None,
        "regression_rate": None,
        "note": (
            "routing loss and content value need the INJECTED condition (task 3.2); transfer and "
            "regression rates arrive with the matrix statistics (task 4.5)"
        ),
    }


def not_run(results: list[dict[str, Any]], manifest: dict[str, Any]) -> list[dict[str, Any]]:
    """Every combination that did not produce a usable result, with the reason it did not."""
    entries = []
    for model, preflight in (manifest.get("preflight") or {}).items():
        if not preflight.get("ok"):
            entries.append(
                {
                    "kind": "preflight",
                    "model": model,
                    "reason": "; ".join(preflight.get("problems") or ["preflight failed"]),
                }
            )
    for result in results:
        if result["outcome"] not in INFRA_OUTCOMES:
            continue
        entries.append(
            {
                "kind": result["outcome"],
                "task_id": result["task_id"],
                "model": result["model"],
                "condition": result["condition"],
                "repeat": result["repeat"],
                "reason": result.get("reason") or result.get("error") or "no reason recorded",
            }
        )
    return entries


# --------------------------------------------------------------------------- markdown


def render_markdown(report: dict[str, Any]) -> str:
    """`report.md`: the same facts, readable without a JSON tool."""
    lines = [
        f"# Evaluation {report.get('run_id')}",
        "",
        f"- suite: `{report.get('suite')}`",
        f"- collection: `{report.get('collection')}`",
        (
            f"- harness: {report.get('harness')} {report.get('harness_version')}"
            f" (wikiskill {report.get('wikiskill_version')})"
        ),
        f"- models: {', '.join(report.get('models') or []) or '—'}",
        f"- conditions: {', '.join(report.get('conditions') or []) or '—'}",
        f"- wall time: {report.get('duration_s')}s",
        "",
        "## Outcomes",
        "",
    ]
    outcomes = report.get("outcomes") or {}
    lines += [f"- {name}: {count}" for name, count in sorted(outcomes.items())] or ["- none"]

    lines += ["", "## Per task, model and condition", ""]
    if report.get("rows"):
        lines += [
            (
                "| task | model | condition | repeats | route@1 | route@k | cap@k | pass |"
                " pass basis | tokens | time (s) |"
            ),
            "|---|---|---|---|---|---|---|---|---|---|---|",
        ]
        for row in report["rows"]:
            tokens = row.get("tokens") or {}
            total = sum(value for value in tokens.values() if isinstance(value, int))
            lines.append(
                f"| {row['task_id']} | {row['model']} | {row['condition']} | {row['repeats']} | "
                f"{_pct(row.get('route@1'))} | {_pct(row.get('route@k'))} | "
                f"{_pct(row.get('capability@k'))} | {_pct(row.get('pass_rate'))} | "
                f"{row.get('pass_basis', '—')} | {total} | "
                f"{round((row.get('wall_time_ms') or 0) / 1000, 1)} |"
            )
    else:
        lines.append("No task produced a scorable result.")

    lines += _failing_verifier_lines(report.get("rows") or [])

    lines += ["", "## Per model and condition", ""]
    for key, summary in sorted((report.get("per_model_condition") or {}).items()):
        model, _, condition = key.partition("|")
        lines.append(
            f"- **{model}** / {condition}: route@1 {_pct(summary.get('route@1'))}, "
            f"route@k {_pct(summary.get('route@k'))}, "
            f"capability@k {_pct(summary.get('capability@k'))} "
            f"over {summary.get('tasks_measuring_route')} routing tasks"
        )

    confusion = report.get("confusion") or {}
    if confusion:
        lines += [
            "",
            "## Routing confusion",
            "",
            "| expected | activated | runs |",
            "|---|---|---|",
        ]
        for expected, row in sorted(confusion.items()):
            for chosen, count in sorted(row.items(), key=lambda item: -item[1]):
                lines.append(f"| {expected} | {chosen} | {count} |")

    derived = report.get("derived") or {}
    lines += [
        "",
        "## Derived measures",
        "",
        f"Not computed in this run: {derived.get('note')}.",
        "",
        "## Not run",
        "",
    ]
    entries = report.get("not_run") or []
    if not entries:
        lines.append("Everything the suite declared was attempted and produced a result.")
    else:
        for entry in entries:
            where = " ".join(
                str(entry[key])
                for key in ("task_id", "model", "condition", "repeat")
                if entry.get(key) is not None
            )
            lines.append(
                f"- **{entry['kind']}** {where or entry.get('model', '')}: {entry['reason']}"
            )
    return "\n".join(lines) + "\n"


def _failing_verifier_lines(rows: list[dict[str, Any]]) -> list[str]:
    """Which check failed, per row. A pass rate of 0% is a question; this is the answer."""
    failing = [row for row in rows if row.get("failed_verifiers")]
    if not failing:
        return []
    lines = ["", "## Failing verifiers", ""]
    for row in failing:
        lines.append(f"- **{row['task_id']}** / {row['model']} / {row['condition']}:")
        lines += [
            f"  - `{verifier['kind']}`: {verifier['detail']}"
            for verifier in row["failed_verifiers"]
        ]
    return lines


def _pct(value: float | None) -> str:
    return "—" if value is None else f"{value * 100:.0f}%"


def write(layout: RunLayout, results: list[dict[str, Any]], manifest: dict[str, Any]) -> dict:
    """Write `report.json` and `report.md` into a run directory, and return the report."""
    report = build_report(results, manifest)
    layout.report_json.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    layout.report_md.write_text(render_markdown(report), encoding="utf-8")
    return report
