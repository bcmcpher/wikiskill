"""What `maint.sh` asks of the sandboxes, the runs and the judges, kept out of the shell script.

    maint_state.py sandbox <root> <collection> <manifest> <model> <evidence>
        make one maintainer's sandbox: its own config (roles set to <model>) and data (the evidence
        runs linked, raw/ and sources/ copied, no wiki)
    maint_state.py baseline <collection> <evidence> <model> <thinking>
        the evidence run that ran <model> at <thinking>: a candidate's replay baseline
    maint_state.py outcome <log>
        `proposal <id>`, `no_action`, `failed` or `review_failed`, read off a refine log
    maint_state.py judge <root> <collection> <id> <judge> <base-url> <out> <evidence-digest>
        score one proposal, blind to its proposer, against the evidence every maintainer was shown
        and the component's text; write the judge's JSON to <out>
    maint_state.py table <maint-root> <out-dir>
        one row per (maintainer, component): `maint.csv` and `maint.md`

A sandbox is a pair of XDG roots: run wikiskill with XDG_CONFIG_HOME=<root>/config and
XDG_DATA_HOME=<root>/data, and it sees only that maintainer's roles, wiki and proposals.

Run with `uv run python`, so `wikiskill` is importable.
"""

from __future__ import annotations

import csv
import json
import re
import shutil
import sys
import tomllib
from pathlib import Path

from wikiskill import compare, paths, roles
from wikiskill.runner.preflight import Endpoint

ROLES = ("maintainer", "proposer")
DATA = ("raw", "sources")


def _evidence(path: str) -> list[str]:
    return [
        line.strip() for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()
    ]


def _set_roles(text: str, model: str) -> str:
    """Set `model` in `[roles.maintainer]` and `[roles.proposer]`, and touch nothing else."""
    out, section = [], None
    for line in text.splitlines():
        header = re.match(r"\s*\[([^\]]+)\]", line)
        if header:
            section = header.group(1).strip()
        elif section in {f"roles.{r}" for r in ROLES} and re.match(r"\s*model\s*=", line):
            out.append(f'model = "{model}"')
            continue
        out.append(line)
    return "\n".join(out) + "\n"


def sandbox(root: str, collection: str, manifest: str, model: str, evidence: str) -> int:
    base = Path(root)
    config = base / "config" / "wikiskill" / "collections" / f"{collection}.toml"
    config.parent.mkdir(parents=True, exist_ok=True)
    config.write_text(_set_roles(Path(manifest).read_text(encoding="utf-8"), model), "utf-8")
    parsed = tomllib.loads(config.read_text(encoding="utf-8"))
    for role in ROLES:
        if parsed["roles"][role]["model"] != model:
            print(f"{config}: [roles.{role}] did not take {model}")
            return 1

    source = paths.collection_data(collection)
    data = base / "data" / "wikiskill" / collection
    evals = data / "evals"
    evals.mkdir(parents=True, exist_ok=True)
    for run_id in _evidence(evidence):
        link = evals / run_id
        if not (source / "evals" / run_id).is_dir():
            print(f"evidence run {run_id} is not in {source / 'evals'}")
            return 1
        if not link.exists():
            link.symlink_to(source / "evals" / run_id)
    for name in DATA:
        if (source / name).is_dir() and not (data / name).exists():
            shutil.copytree(source / name, data / name, symlinks=True)
    return 0


def baseline(collection: str, evidence: str, model: str, thinking: str) -> int:
    for run_id in _evidence(evidence):
        manifest = compare.load_run(collection, run_id).manifest
        if (manifest.get("options") or {}).get("thinking", "default") != thinking:
            continue
        if f"ollama/{model}" in (manifest.get("models") or []):
            print(run_id)
            return 0
    print(f"no evidence run of {collection} ran {model} at --thinking {thinking}", file=sys.stderr)
    return 1


def _outcome(log: Path) -> tuple[str, str]:
    """(outcome, detail) from a refine log, or from a review log when refine never ran."""
    if not log.is_file():
        return "not_run", ""
    text = log.read_text(encoding="utf-8", errors="replace")
    if m := re.search(r"^proposal (p-\d+) for ", text, re.M):
        return "proposal", m.group(1)
    if m := re.search(r"^no_action for [^:]+: (.*)$", text, re.M):
        kind = "review_failed" if "holds no pattern" in m.group(1) else "no_action"
        return kind, m.group(1).strip()
    if "failed validation" in text:
        problems = re.findall(r"^  - (.*)$", text, re.M)
        return "failed", "; ".join(problems)[:400]
    return "error", text.strip().splitlines()[-1][:200] if text.strip() else ""


def outcome(log: str) -> int:
    kind, detail = _outcome(Path(log))
    print(f"{kind} {detail}".strip())
    return 0


RUBRIC = """\
You are reviewing a proposed edit to an AI agent's instructions (a "component": a skill or a
subagent prompt). A maintainer read evaluation evidence, wrote one or more failure patterns, and
proposed the patch below. You do not know which model wrote it. You are given the evidence the
maintainer was shown, the component's current text, the maintainer's patterns and the patch. Check
the maintainer's reading against the evidence yourself: a coherent story is not a correct one.
Score the proposal on four dimensions, each 1 to 5:

- diagnosis: is the stated cause what the evidence actually shows? 5 = correct and specific; 1 =
  it misreads the evidence, e.g. blames the model for what the environment caused.
- specificity: 5 = the edit changes exactly what the diagnosis needs; 1 = vague advice or
  restated rules.
- regression_risk: 5 = very unlikely to break behaviour that worked; 1 = likely to break it
  (removes rules, contradicts other steps, or forces one environment).
- generality: 5 = helps any model in any install; 1 = only one model or the evaluator's machine.

Answer with one JSON object and nothing else:
{"diagnosis": n, "specificity": n, "regression_risk": n, "generality": n,
 "cause_in_one_line": "...", "comment": "at most two sentences"}
"""

BLIND = re.compile(r"^(maintainer|proposer):.*$", re.M)


def _proposal_text(root: Path, collection: str, proposal_id: str, digest: str | None = None) -> str:
    wiki = root / "data" / "wikiskill" / collection / "wiki"
    directory = wiki / "proposals" / proposal_id
    meta = json.loads((directory / "meta.json").read_text(encoding="utf-8"))
    parts = [f"# Component: {meta['component']}"]
    if digest:
        parts += ["", "## Evidence the maintainer was shown", "", Path(digest).read_text("utf-8")]
        source = Path(meta["source_path"])
        if source.is_file():
            parts += ["", "## The component's current text", "", source.read_text("utf-8")]
    parts += ["", "## Patterns the proposal cites"]
    for slug in meta["patterns"]:
        page = wiki / "patterns" / f"{slug}.md"
        if page.is_file():
            parts += ["", BLIND.sub("", page.read_text(encoding="utf-8"))]
    parts += ["", "## Proposal", "", f"Why: {meta['reason']}", "", "```diff"]
    parts += [(directory / "patch.diff").read_text(encoding="utf-8").rstrip(), "```"]
    return "\n".join(parts)


def judge(  # noqa: PLR0917 - positional, as maint.sh calls every command
    root: str, collection: str, proposal_id: str, model: str, base_url: str, out: str, digest: str
) -> int:
    messages = [
        {"role": "system", "content": RUBRIC},
        {"role": "user", "content": _proposal_text(Path(root), collection, proposal_id, digest)},
    ]
    try:
        status, body = roles.chat(Endpoint(base_url), model, messages, timeout=900)
    except OSError as exc:
        print(f"{model} is unreachable: {exc}")
        return 1
    content = ""
    for choice in (body or {}).get("choices") or [] if status == 200 else []:
        content = (choice.get("message") or {}).get("content") or ""
    match = re.search(r"\{.*\}", content, re.S)
    try:
        scores = json.loads(match.group(0)) if match else None
    except json.JSONDecodeError:
        scores = None
    record = {"judge": model, "status": status, "scores": scores, "reply": content}
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    Path(out).write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    if scores is None:
        print(f"{model} gave no JSON scores for {proposal_id} (status {status})")
        return 1
    return 0


# The defect the event found in archive-doer: its toolbox paths are repository-relative, so the
# readiness check never runs outside a DSH checkout (docs/pilots/dsh/report.md, "Tool choice").
# A hint only; a person reads every flagged and unflagged archive proposal.
DEFECT_HINT = re.compile(
    r"CLAUDE_PLUGIN_ROOT|absolute path|not? (?:exist|resolve)|does not resolve|working director"
    r"|install(?:ed)? (?:location|dir)|relative to the (?:plugin|repo)",
    re.I,
)
DIMENSIONS = ("diagnosis", "specificity", "regression_risk", "generality")


def table(maint_root: str, out_dir: str) -> int:
    rows = []
    for state in sorted(Path(maint_root).glob("*/results/*.json")):
        record = json.loads(state.read_text(encoding="utf-8"))
        root = state.parent.parent
        unit = state.stem
        kind, detail = _outcome(root / "results" / f"{unit}.refine.log")
        row = {"maintainer": record["maintainer"], "unit": unit, "outcome": kind}
        row["proposal"] = detail if kind == "proposal" else ""
        row["detail"] = "" if kind == "proposal" else detail
        log = root / "results" / f"{unit}.refine.log"
        warnings = (
            re.findall(r"^  warning +(.*)$", log.read_text(encoding="utf-8"), re.M)
            if log.is_file()
            else []
        )
        row["warnings"] = "; ".join(warnings)[:400]
        if kind == "proposal":
            text = _proposal_text(root, record["collection"], detail)
            row["defect_hint"] = bool(DEFECT_HINT.search(text)) if unit == "archive" else ""
            for judged in sorted((root / "results").glob(f"{unit}.judge.*.json")):
                verdict = json.loads(judged.read_text(encoding="utf-8"))
                name = judged.name.removeprefix(f"{unit}.judge.").removesuffix(".json")
                for dim in DIMENSIONS:
                    row[f"{name}:{dim}"] = (verdict.get("scores") or {}).get(dim, "")
            for replayed in sorted((root / "results").glob(f"{unit}.replay.*.json")):
                panel = replayed.name.removeprefix(f"{unit}.replay.").removesuffix(".json")
                verdict = json.loads(replayed.read_text(encoding="utf-8"))
                row[f"replay:{panel}"] = verdict.get("recommendation", "?")
        rows.append(row)
    if not rows:
        print(f"no results under {maint_root}")
        return 1
    columns = list(dict.fromkeys(key for row in rows for key in row))
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    with (out / "maint.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, columns)
        writer.writeheader()
        writer.writerows(rows)
    lines = ["| " + " | ".join(columns) + " |", "|" + "---|" * len(columns)]
    for row in rows:
        cells = [str(row.get(c, "")).replace("|", "/").replace("\n", " ")[:120] for c in columns]
        lines.append("| " + " | ".join(cells) + " |")
    (out / "maint.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"{len(rows)} rows: {out / 'maint.csv'}, {out / 'maint.md'}")
    return 0


COMMANDS = {
    "sandbox": sandbox,
    "baseline": baseline,
    "outcome": outcome,
    "judge": judge,
    "table": table,
}

if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] not in COMMANDS:
        print(__doc__)
        sys.exit(2)
    sys.exit(COMMANDS[sys.argv[1]](*sys.argv[2:]))
