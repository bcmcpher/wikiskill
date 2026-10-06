"""What `sweep.sh` asks of the study, the runs and the server, kept out of the shell script.

    sweep_state.py recorded <study>                   each sweep run's (model, thinking), one a line
    sweep_state.py finished <collection> <run> <max>  exit 0 if the run is complete, else say why
    sweep_state.py thinks <ollama-url> <model>        exit 0 if the server lists `thinking`, else 1
    sweep_state.py catalogue <models.toml> <model>... exit 1 if the order and the catalogue differ

Run with `uv run python`, so `wikiskill` is importable.
"""

from __future__ import annotations

import json
import sys
import tomllib
import urllib.request
from pathlib import Path

from wikiskill import compare, findings, leaderboard
from wikiskill.runner.base import INFRA_OUTCOMES


def recorded(study_dir: str) -> int:
    study = findings.load(study_dir)
    for run in study.runs:
        if run.role != "sweep":
            continue
        bundled = study.bundled(run) / "run.json"
        if bundled.is_file():
            manifest = json.loads(bundled.read_text(encoding="utf-8"))
        else:
            manifest = compare.load_run(study.collection or "", run.path or run.id).manifest
        thinking = (manifest.get("options") or {}).get("thinking", "default")
        for model in manifest.get("models") or []:
            print(f"{model}\t{thinking}")
    return 0


def finished(collection: str, run_id: str, max_not_run: str) -> int:
    """Complete means every unit ran: a run cut short has no `run.json`, or too few result lines,
    and one whose endpoint failed under it has infrastructure outcomes."""
    try:
        run = compare.load_run(collection, run_id)
    except compare.CompareError as exc:
        print(exc)
        return 1
    failed = leaderboard.preflight_failures(run.manifest)
    if failed:
        print("preflight failed: " + "; ".join(f"{m}: {', '.join(p)}" for m, p in failed.items()))
        return 1
    repeats = run.manifest.get("repeats")
    if not repeats or not run.results:
        print("the run recorded no repeats or no results, so it ran no suite")
        return 1
    expected = (
        sum(repeats.get(task, 0) for task in run.tasks)
        * len(run.manifest.get("conditions") or [])
        * len(run.manifest.get("models") or [])
    )
    if len(run.results) < expected:
        print(f"{len(run.results)} of {expected} units have a result")
        return 1
    not_run = sum(1 for result in run.results if result["outcome"] in INFRA_OUTCOMES)
    if not_run > int(max_not_run):
        print(f"{not_run} units did not run ({', '.join(INFRA_OUTCOMES)}), above {max_not_run}")
        return 1
    return 0


def thinks(ollama_url: str, model: str) -> int:
    request = urllib.request.Request(
        f"{ollama_url.rstrip('/')}/api/show",
        data=json.dumps({"model": model}).encode(),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            capabilities = json.load(response).get("capabilities") or []
    except OSError as exc:
        print(f"cannot ask {ollama_url} about {model}: {exc}", file=sys.stderr)
        return 2
    return 0 if "thinking" in capabilities else 1


def catalogue(models_file: str, *order: str) -> int:
    listed = set(tomllib.loads(Path(models_file).read_text(encoding="utf-8"))["models"])
    missing, extra = sorted(set(order) - listed), sorted(listed - set(order))
    for model in missing:
        print(f"{model} is in the sweep's order but not in {models_file}")
    for model in extra:
        print(f"{model} is in {models_file} but not in the sweep's order")
    return 1 if missing or extra else 0


COMMANDS = {"recorded": recorded, "finished": finished, "thinks": thinks, "catalogue": catalogue}

if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] not in COMMANDS:
        sys.exit(__doc__)
    sys.exit(COMMANDS[sys.argv[1]](*sys.argv[2:]))
