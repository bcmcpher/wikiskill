#!/usr/bin/env -S uv run python
"""Re-apply the v2 suites' no-claim verifiers to the sweep's recorded final texts.

`suite-v2.yaml` changes only negated `final_text` regex verifiers, so a recorded unit can be
rescored without rerunning it: its final text is read from its transcript with the runner's own
`_final_text`, each changed verifier is matched again, and every other verdict is kept. Nothing
is written; the bundled runs keep their recorded verdicts.

Prints, per suite: the units whose changed verifiers now give another verdict, then the pass
counts per entrant and condition under v1 and under v2. Needs the transcripts under the
collections' evals, so it runs on the batch machine only.

Usage: pilots/dsh-sweep/rescore.py   (from the repository root)
"""

import collections
import json
import re
import tomllib
from pathlib import Path

import yaml

from wikiskill.runner.opencode import _final_text

EVALS = Path.home() / ".local/share/wikiskill"
SUITES = {
    "dsh": ("dsh-archive", Path("pilots/archive-doer")),
    "dsh-bids": ("dsh-bids", Path("pilots/bids-doer")),
}


def changed(folder: Path) -> dict[str, list[tuple[int, str, str]]]:
    """task id -> [(verifier index, v1 pattern, v2 pattern)] for every verifier that changed."""
    v1 = {
        t["id"]: t["verifiers"]
        for t in yaml.safe_load((folder / "suite.yaml").read_text())["tasks"]
    }
    v2 = {
        t["id"]: t["verifiers"]
        for t in yaml.safe_load((folder / "suite-v2.yaml").read_text())["tasks"]
    }
    out = collections.defaultdict(list)
    for task, verifiers in v1.items():
        for i, (old, new) in enumerate(zip(verifiers, v2[task], strict=True)):
            if old != new:
                if not (old.get("negate") and old.get("target") == "final_text"):
                    raise SystemExit(f"{task}/{i}: only negated final_text verifiers may change")
                out[task].append((i, old["pattern"], new["pattern"]))
    return out


def main() -> None:
    for study, (collection, folder) in SUITES.items():
        diffs = changed(folder)
        passes = collections.defaultdict(lambda: [0, 0, 0])
        flips = []
        for run in tomllib.loads((Path("docs/pilots") / study / "findings.toml").read_text())[
            "runs"
        ]:
            if run["role"] != "sweep":
                continue
            units_dir = EVALS / collection / "evals" / run["id"] / "units"
            bundle = Path("docs/pilots") / study / "runs" / run["id"]
            thinking = json.loads((bundle / "run.json").read_text())["options"].get("thinking")
            for line in (bundle / "results.jsonl").read_text().splitlines():
                unit = json.loads(line)
                model = unit["model"].split("/")[-1]
                entrant = model + ("" if thinking in (None, "default") else f" ({thinking})")
                verdicts = [v["passed"] for v in unit["verifiers"]]
                found = list(
                    units_dir.glob(f"{unit['task_id']}__*__{unit['condition']}__r{unit['repeat']}")
                )
                if diffs.get(unit["task_id"]) and verdicts:
                    if len(found) != 1:
                        raise SystemExit(f"no transcript for {run['id']} {unit['task_id']}")
                    sessions = json.loads((found[0] / "sessions.json").read_text())
                    text = _final_text(sessions)
                    for i, old, new in diffs[unit["task_id"]]:
                        was = not re.search(old, text)
                        now = not re.search(new, text)
                        if was != verdicts[i]:
                            raise SystemExit(
                                f"{run['id']} {unit['task_id']}: v1 does not reproduce"
                            )
                        if was != now:
                            flips.append(
                                (
                                    unit["condition"],
                                    entrant,
                                    unit["task_id"],
                                    unit["repeat"],
                                    run["id"],
                                    "fail -> pass" if now else "pass -> fail",
                                )
                            )
                        verdicts[i] = now
                cell = passes[(entrant, unit["condition"])]
                cell[0] += unit["passed"]
                cell[1] += bool(verdicts) and all(verdicts)  # as recorded: every verifier passed
                cell[2] += 1
        print(f"== {folder.name}: {len(flips)} changed verdicts")
        for flip in sorted(flips):
            print("  " + "  ".join(str(f) for f in flip))
        print("  entrant, condition: v1 -> v2 passes")
        for (entrant, cond), (v1, v2, n) in sorted(passes.items()):
            if v1 != v2:
                print(f"    {entrant} {cond}: {v1}/{n} -> {v2}/{n}")


if __name__ == "__main__":
    main()
