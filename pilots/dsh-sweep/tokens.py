#!/usr/bin/env python3
"""Token figures for the DSH sweep, both passes pooled.

`tokens`: from the bundled `results.jsonl`, per suite, entrant and condition: the median output
per unit, output per passed unit, and the median context (`input` + `cache_read`) over the units
that record `cache_read` (the second pass and the first pass's last runs; their count in brackets).

`thinking`: from the transcripts under the collections' evals (on the batch machine only), per
entrant over all three suites: the median per unit of reported output, visible text plus tool-call
arguments, and reasoning-part text, both at 4 characters a token; the share of units with any
reasoning part; and the share whose final reply opens by thinking aloud.

Usage: pilots/dsh-sweep/tokens.py tokens|thinking   (from the repository root)
"""

import collections
import json
import re
import statistics
import sys
import tomllib
from pathlib import Path

STUDIES = {
    "dsh": ("archive", "dsh-archive"),
    "dsh-bids": ("bids", "dsh-bids"),
    "dsh-curate": ("curate", "dsh-curate"),
}
EVALS = Path.home() / ".local/share/wikiskill"
THINKS_ALOUD = re.compile(
    r"^\s*(okay|ok,|alright|the user (wants|is asking)|let me|we need|"
    r"i need to|first, i)",
    re.I,
)


def runs():
    """Yield (study, suite, collection, run id, model, thinking) for every sweep run."""
    for study, (suite, collection) in STUDIES.items():
        root = Path("docs/pilots") / study
        for run in tomllib.loads((root / "findings.toml").read_text())["runs"]:
            if run["role"] != "sweep":
                continue
            meta = json.loads((root / "runs" / run["id"] / "run.json").read_text())
            model = meta["models"][0].split("/")[-1]
            yield (
                study,
                suite,
                collection,
                run["id"],
                model,
                meta["options"].get("thinking") or "default",
            )


def k(value: float) -> str:
    return f"{value / 1000:.1f}k"


def tokens() -> None:
    cells = collections.defaultdict(list)
    for study, suite, _, rid, model, thinking in runs():
        for line in (
            (Path("docs/pilots") / study / "runs" / rid / "results.jsonl").read_text().splitlines()
        ):
            unit = json.loads(line)
            cells[(suite, model, thinking, unit["condition"])].append(unit)
    print(
        "| suite | entrant | condition | units | median output | output per pass | median context |"
    )
    print("|---|---|---|---|---|---|---|")
    for (suite, model, thinking, cond), units in sorted(cells.items()):
        outputs = [u["tokens"]["output"] for u in units if u.get("tokens")]
        passed = sum(u["passed"] for u in units)
        per_pass = k(sum(outputs) / passed) if passed else "no pass"
        with_cache = [u["tokens"] for u in units if "cache_read" in (u.get("tokens") or {})]
        context = (
            (
                k(statistics.median(t["input"] + t["cache_read"] for t in with_cache))
                + f" ({len(with_cache)})"
            )
            if with_cache
            else "-"
        )
        entrant = model + ("" if thinking == "default" else f" ({thinking})")
        print(
            f"| {suite} | {entrant} | {cond} | {len(units)} | {k(statistics.median(outputs))} "
            f"| {per_pass} | {context} |"
        )


def unit_split(unit_dir: Path) -> tuple[int, int, int, bool, str] | None:
    """(reported output, visible estimate, reasoning estimate, any reasoning part, final text)."""
    sessions = unit_dir / "sessions.json"
    if not sessions.is_file():
        return None
    output = visible = reasoning = 0
    any_reasoning = False
    final = ""
    for session in json.loads(sessions.read_text()):
        for message in session.get("messages", []):
            if message["info"].get("role") != "assistant":
                continue
            output += (message["info"].get("tokens") or {}).get("output", 0)
            for part in message.get("parts", []):
                if part["type"] == "text":
                    visible += len(part.get("text", ""))
                elif part["type"] == "tool":
                    visible += len(json.dumps((part.get("state") or {}).get("input", {})))
                elif part["type"] == "reasoning":
                    reasoning += len(part.get("text", ""))
                    any_reasoning = True
    for line in (unit_dir / "run.ndjson").read_text().splitlines():
        event = json.loads(line)
        if event["type"] == "text":
            final = event["part"].get("text", "")
    return output, visible // 4, reasoning // 4, any_reasoning, final


def thinking() -> None:
    cells = collections.defaultdict(list)
    for _, _, collection, rid, model, think in runs():
        for unit_dir in sorted((EVALS / collection / "evals" / rid / "units").glob("*")):
            split = unit_split(unit_dir)
            if split:
                cells[(model, think)].append(split)
    print("| entrant | units | output | visible | reasoning | with reasoning | thinks aloud |")
    print("|---|---|---|---|---|---|---|")
    for (model, think), units in sorted(cells.items()):
        med = [round(statistics.median(u[i] for u in units)) for i in range(3)]
        with_reasoning = sum(u[3] for u in units)
        aloud = sum(bool(THINKS_ALOUD.match(u[4])) for u in units)
        entrant = model + ("" if think == "default" else f" ({think})")
        print(
            f"| {entrant} | {len(units)} | {med[0]} | {med[1]} | {med[2]} | {with_reasoning} "
            f"| {aloud} |"
        )


if __name__ == "__main__":
    {"tokens": tokens, "thinking": thinking}[sys.argv[1] if len(sys.argv) > 1 else "tokens"]()
