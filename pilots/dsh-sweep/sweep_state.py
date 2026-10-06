"""What `sweep.sh` asks of the study, the runs and the server, kept out of the shell script.

    sweep_state.py recorded <study>                   each sweep run's model, thinking and repeats
    sweep_state.py finished <collection> <run> <max>  exit 0 if the run is complete, else say why
    sweep_state.py thinks <ollama-url> <model>        exit 0 if the server lists `thinking`, else 1
    sweep_state.py served <ollama-url> <model>        exit 0 if the server has the model, else 1
    sweep_state.py catalogue <models.toml> <model>... exit 1 if a model is not in the catalogue
    sweep_state.py judges <collection>                the collection's judge models, one a line
    sweep_state.py requires <suite>...                exit 1 if a task's programs are not on PATH

Run with `uv run python`, so `wikiskill` is importable.
"""

from __future__ import annotations

import json
import sys
import tomllib
import urllib.request
from pathlib import Path

from wikiskill import collection as collections
from wikiskill import compare, findings, leaderboard, names
from wikiskill import suite as suites
from wikiskill.runner.base import INFRA_OUTCOMES
from wikiskill.runner.run import missing_capabilities


def recorded(study_dir: str) -> int:
    """`model<TAB>thinking<TAB>repeats`: the repeats every task ran, `mixed` when they differ, and
    `?` for a run from before `run.json` recorded them. The sweep reruns a pair at other repeats."""
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
        counts = set((manifest.get("repeats") or {}).values())
        repeats = "?" if not counts else str(counts.pop()) if len(counts) == 1 else "mixed"
        for model in manifest.get("models") or []:
            print(f"{model}\t{thinking}\t{repeats}")
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


def _show(ollama_url: str, model: str) -> dict:
    request = urllib.request.Request(
        f"{ollama_url.rstrip('/')}/api/show",
        data=json.dumps({"model": model}).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)


def thinks(ollama_url: str, model: str) -> int:
    try:
        capabilities = _show(ollama_url, model).get("capabilities") or []
    except OSError as exc:
        print(f"cannot ask {ollama_url} about {model}: {exc}", file=sys.stderr)
        return 2
    return 0 if "thinking" in capabilities else 1


def served(ollama_url: str, model: str) -> int:
    try:
        _show(ollama_url, model)
    except OSError as exc:
        print(f"{ollama_url} does not serve {model}: {exc}")
        return 1
    return 0


def catalogue(models_file: str, *order: str) -> int:
    listed = set(tomllib.loads(Path(models_file).read_text(encoding="utf-8"))["models"])
    missing = [model for model in order if model not in listed]
    for model in missing:
        print(f"{model} is in the sweep's order but not in {models_file}")
    return 1 if missing else 0


def judges(name: str) -> int:
    """A judge must not be a model under test: the sweep never runs these on this collection's
    suite. Printed without a provider and lower-cased, so the sweep compares like with like."""
    judge = collections.load(name).roles.get("judge")
    for model in judge.panel if judge else ():
        print(names.model_id(model).lower())
    return 0


def requires(*paths: str) -> int:
    """A task missing a program is `skipped`, which leaves its run incomplete: say so up front."""
    missing = []
    for path in paths:
        for task in suites.load(path).tasks:
            missing += [f"{path}: {task.id} needs {name}" for name in missing_capabilities(task)]
    print("\n".join(missing))
    return 1 if missing else 0


COMMANDS = {
    "recorded": recorded,
    "finished": finished,
    "thinks": thinks,
    "served": served,
    "catalogue": catalogue,
    "judges": judges,
    "requires": requires,
}

if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] not in COMMANDS:
        sys.exit(__doc__)
    sys.exit(COMMANDS[sys.argv[1]](*sys.argv[2:]))
