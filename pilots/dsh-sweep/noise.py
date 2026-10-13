#!/usr/bin/env python3
"""Run-to-run noise across days, from the bundled sweep runs (add-dsh-pilot 4.5).

Every entrant of the first pass (2026-10-06/07, 3 repeats) got 2 more repeats in the second pass
(`v2.sh 1b`, 2026-10-11) with the same suite hash and settings. Each (suite, model, thinking,
condition) cell is split into its first-pass and second-pass units, and the two pass rates are
compared:

- a two-sided Fisher exact test per cell;
- the mean |difference| over cells, against a null that resamples each (cell, task) from its own
  pooled pass rate, so a day effect shows as a spread larger than the null's;
- per (cell, task): stable (all pass or all fail on both days), flipped (all pass one day, all fail
  the other), or mixed.

Usage: pilots/dsh-sweep/noise.py   (from the repository root)
"""

import collections
import json
import random
import tomllib
from math import comb
from pathlib import Path

STUDIES = {"dsh": "archive", "dsh-bids": "bids", "dsh-curate": "curate"}
SECOND_PASS = "01M4H"  # run ids sort by time; the second pass starts at this prefix
DRAWS = 2000


def fisher(a: int, n1: int, b: int, n2: int) -> float:
    k, n = a + b, n1 + n2

    def p(x: int) -> float:
        return comb(n1, x) * comb(n2, k - x) / comb(n, k)

    observed = p(a)
    return sum(p(x) for x in range(max(0, k - n2), min(n1, k) + 1) if p(x) <= observed * (1 + 1e-9))


def tasks() -> dict[tuple, list[int]]:
    """(suite, model, thinking, condition, task) -> [passed, n] on pass one, then pass two."""
    out: dict[tuple, list[int]] = collections.defaultdict(lambda: [0, 0, 0, 0])
    for study, suite in STUDIES.items():
        root = Path("docs/pilots") / study
        for run in tomllib.loads((root / "findings.toml").read_text())["runs"]:
            if run["role"] != "sweep":
                continue
            meta = json.loads((root / "runs" / run["id"] / "run.json").read_text())
            entrant = (
                suite,
                meta["models"][0].split("/")[-1],
                meta["options"].get("thinking") or "default",
            )
            late = 2 * (run["id"] >= SECOND_PASS)
            for line in (root / "runs" / run["id"] / "results.jsonl").read_text().splitlines():
                unit = json.loads(line)
                counts = out[(*entrant, unit["condition"], unit["task_id"])]
                counts[late] += unit["passed"]
                counts[late + 1] += 1
    return out


def null_spread(cells: dict[tuple, list[list[int]]], rng: random.Random) -> list[float]:
    """Mean |difference| over cells, DRAWS times, each (cell, task) resampled at its pooled rate."""
    null = []
    for _ in range(DRAWS):
        total = 0.0
        for ts in cells.values():
            x = y = n1 = n2 = 0
            for a, m1, b, m2 in ts:
                p = (a + b) / (m1 + m2)
                x += sum(rng.random() < p for _ in range(m1))
                y += sum(rng.random() < p for _ in range(m2))
                n1, n2 = n1 + m1, n2 + m2
            total += abs(y / n2 - x / n1) * 100
        null.append(total / len(cells))
    return sorted(null)


def stability(by_cell: dict[tuple, dict[str, list[int]]]) -> tuple[int, int, list[tuple]]:
    """Count (cell, task)s all-pass or all-fail on both days, and list the ones that flip."""
    stable = mixed = 0
    flips = []
    for key, per_task in by_cell.items():
        for task, (a, m1, b, m2) in per_task.items():
            r1, r2 = a / m1, b / m2
            if r1 not in (0, 1) or r2 not in (0, 1):
                mixed += 1
            elif r1 == r2:
                stable += 1
            else:
                flips.append((*key, task, a, m1, b, m2))
    return stable, mixed, flips


def main() -> None:
    by_cell: dict[tuple, dict[str, list[int]]] = collections.defaultdict(dict)
    for key, counts in tasks().items():
        by_cell[key[:4]][key[4]] = counts
    by_cell = {k: v for k, v in by_cell.items() if all(c[1] and c[3] for c in v.values())}
    cells = {k: list(v.values()) for k, v in by_cell.items()}

    rows = []
    for key, ts in sorted(cells.items()):
        a, n1, b, n2 = (sum(c[i] for c in ts) for i in range(4))
        rows.append((key, a, n1, b, n2, b / n2 - a / n1, fisher(a, n1, b, n2)))
    spread = sorted(abs(r[5]) * 100 for r in rows)
    observed = sum(spread) / len(spread)
    null = null_spread(cells, random.Random(0))
    above = sum(v >= observed for v in null) / DRAWS
    stable, mixed, flips = stability(by_cell)

    print(f"cells: {len(rows)} (suite x entrant x condition with units on both days)")
    print(f"mean |second - first|: {observed:.1f} points", end="")
    print(f"; median {spread[len(spread) // 2]:.1f}, max {spread[-1]:.1f}")
    print(f"null (per-task resampling): mean {sum(null) / DRAWS:.1f}", end="")
    print(
        f", 90% {null[DRAWS // 20]:.1f}-{null[DRAWS * 19 // 20]:.1f}; share >= observed {above:.2f}"
    )
    significant = sum(r[6] < 0.05 for r in rows)
    print(f"cells with Fisher p < 0.05: {significant} (about {0.05 * len(rows):.1f} by chance)")
    for suite in STUDIES.values():
        signed = [r[5] * 100 for r in rows if r[0][0] == suite]
        mean = sum(signed) / len(signed)
        print(f"  {suite}: mean signed difference {mean:+.1f} points over {len(signed)} cells")
    print(f"(cell, task): {stable} stable, {len(flips)} flipped, {mixed} mixed")
    for *key, a, m1, b, m2 in flips:
        print(f"  flipped: {' '.join(key)} {a}/{m1} -> {b}/{m2}")
    print("smallest Fisher p:")
    for key, a, n1, b, n2, _diff, p in sorted(rows, key=lambda r: r[6])[:5]:
        print(f"  {' '.join(key)}: {a}/{n1} -> {b}/{n2} (p = {p:.2f})")


if __name__ == "__main__":
    main()
