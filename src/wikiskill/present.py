"""How every output prints a rate, a percentage and a table, so one number reads one way everywhere.

A pass rate prints as `9/10 (90%, 60-98%)`: the counts first, because a rate without its total is
not a finding, then the rate and its 95% Wilson interval. Where a table cell has no room for an
interval (a per-task matrix), it prints as `9/10`. A missing value prints as `—`.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import Any

MISSING = "—"


def rate(passed: int, total: int) -> str:
    """``passed/total (rate, low-high)``, or `—` when nothing was counted."""
    if not total:
        return MISSING
    from .compare import wilson  # noqa: PLC0415 - compare prints through this module

    low, high = wilson(passed, total) or (0.0, 0.0)
    return f"{passed}/{total} ({passed / total:.0%}, {low * 100:.0f}-{high:.0%})"


def count(passed: int, total: int) -> str:
    """``passed/total`` alone, for cells too small for an interval."""
    return f"{passed}/{total}" if total else MISSING


def pct(value: float | None, *, signed: bool = False) -> str:
    if value is None:
        return MISSING
    return f"{value:+.0%}" if signed else f"{value:.0%}"


def value(item: Any, fmt: str = "") -> str:
    """Any value, or `—` when it is missing."""
    if item is None or item == "":
        return MISSING
    return format(item, fmt)


def seconds(ms: float | None) -> str:
    return MISSING if ms is None else f"{ms / 1000:.1f}"


def table(header: Sequence[str], rows: Iterable[Sequence[Any]]) -> list[str]:
    """Markdown table lines: the header, its rule, and one line per row."""
    lines = [
        "| " + " | ".join(header) + " |",
        "|" + "|".join("---" for _ in header) + "|",
    ]
    lines += ["| " + " | ".join(str(cell) for cell in row) + " |" for row in rows]
    return lines


def of(found: Any) -> str:
    """`rate` for anything with `passed` and `total`, or `—` for none."""
    return MISSING if found is None else rate(found.passed, found.total)


def count_of(found: Any) -> str:
    """`count` for anything with `passed` and `total`, or `—` for none."""
    return MISSING if found is None else count(found.passed, found.total)
