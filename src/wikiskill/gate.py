"""The refinement gate: replay a proposal, recommend, and record the user's decision.

A proposal moves `proposed → replayed → accepted | rejected | withdrawn`, and only `decide` reaches
the last three: replay recommends, the user decides. Its state lives in the proposal's `meta.json`.

Replay re-runs nothing itself. A baseline is an ordinary run of a suite at the proposal's
`source_hash`; a candidate is the same suite run with `wikiskill eval --proposal <id>`, which
evaluates the rendered file from a copy of its source in the run directory, so the user's
repository is never written. `replay` checks that the two runs are what they claim, compares them
with `compare`, and breaks the result down per model and per task:
- *motivating cases* are the suite tasks the cited patterns' evidence came from
- the *regression bank* is every other task of the suite
- evidence that cannot be replayed (a live session, a task from another suite) is listed with why

With a collection graph (`wikiskill graph build`), replay also names the component's neighbours and
the suite tasks that expect them, lists the neighbours the suite leaves out, and checks a
description edit for trigger theft: `route@1` of each conflict neighbour's routing tasks, per model.

Every decision appends to `skill-impact.md`; a rejected or withdrawn proposal keeps its full content
there, which the next proposer for the component is shown.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from . import compare, present, rawlog, refine, wiki
from . import graph as graph_mod
from .collection import Collection
from .errors import WikiskillError
from .frontmatter import FrontmatterError
from .runner.base import OFF, ROUTED
from .score.route import UNSCORED, first_activation, same

REPLAYED = "replayed"
DECISIONS = {"accept": "accepted", "reject": "rejected", "withdraw": "withdrawn"}
FINAL = tuple(DECISIONS.values())
#: How far one task's pass rate may fall on one model before the gate stops recommending: one
#: repeat in three, the noise floor of a three-repeat suite.
DEFAULT_TOLERANCE = 1 / 3
ACCEPT, DO_NOT_ACCEPT, NO_RECOMMENDATION = "accept", "do not accept", "none"


class GateError(WikiskillError):
    """A proposal cannot move as asked."""


@dataclass
class TaskChange:
    condition: str
    model: str
    task: str
    a: compare.Rate
    b: compare.Rate

    @property
    def drop(self) -> float:
        return (self.a.rate or 0.0) - (self.b.rate or 0.0)

    def as_dict(self) -> dict[str, Any]:
        return {
            "condition": self.condition,
            "model": self.model,
            "task": self.task,
            "a": self.a.as_dict(),
            "b": self.b.as_dict(),
        }


@dataclass
class Replay:
    proposal: str
    comparison: compare.Comparison
    motivating: list[str]
    bank: list[str]
    #: evidence label or ref → why it cannot be replayed
    unreplayable: dict[str, str]
    tolerance: float
    #: (condition, model) → motivating cases' rate in A and in B
    motivating_rates: dict[tuple[str, str], tuple[compare.Rate, compare.Rate]] = field(
        default_factory=dict
    )
    #: every task whose pass rate fell, whatever the tolerance
    regressions: list[TaskChange] = field(default_factory=list)
    #: neighbour → its edge kinds, weight, and the suite tasks that expect it; empty with no graph
    neighbours: dict[str, dict[str, Any]] = field(default_factory=dict)
    graph: bool = False
    #: whether the proposal changed the description; None when that cannot be told
    description_changed: bool | None = None
    #: conflict neighbours' routing tasks whose route@1 fell under ROUTED
    theft: list[TaskChange] = field(default_factory=list)
    recommendation: str = NO_RECOMMENDATION
    reasons: list[str] = field(default_factory=list)

    def beyond_tolerance(self) -> list[TaskChange]:
        changes = [*self.regressions, *self.theft]
        return [r for r in changes if r.drop > self.tolerance + 1e-9]

    @property
    def uncovered(self) -> list[str]:
        return sorted(name for name, seen in self.neighbours.items() if not seen["tasks"])

    @property
    def unchecked(self) -> list[str]:
        """Conflict neighbours of a description edit with no routing task in the suite."""
        if not self.description_changed:
            return []
        return sorted(
            name
            for name, seen in self.neighbours.items()
            if graph_mod.CONFLICT in seen["kinds"] and not seen["routing_tasks"]
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "proposal": self.proposal,
            "baseline": {"run_id": self.comparison.a.run_id, "hash": self.comparison.hash_a},
            "candidate": {"run_id": self.comparison.b.run_id, "hash": self.comparison.hash_b},
            "motivating": self.motivating,
            "regression_bank": self.bank,
            "unreplayable": self.unreplayable,
            "tolerance": self.tolerance,
            "motivating_rates": [
                {"condition": c, "model": m, "a": a.as_dict(), "b": b.as_dict()}
                for (c, m), (a, b) in sorted(self.motivating_rates.items())
            ],
            "regressions": [
                {**r.as_dict(), "beyond_tolerance": r.drop > self.tolerance + 1e-9}
                for r in self.regressions
            ],
            "graph": self.graph,
            "neighbours": self.neighbours,
            "uncovered": self.uncovered,
            "description_changed": self.description_changed,
            "theft": [
                {**r.as_dict(), "beyond_tolerance": r.drop > self.tolerance + 1e-9}
                for r in self.theft
            ],
            "unchecked": self.unchecked,
            "recommendation": self.recommendation,
            "reasons": self.reasons,
            "comparison": self.comparison.as_dict(),
        }


# --------------------------------------------------------------------------- proposals


def directory(collection: str, proposal: str) -> Path:
    found = wiki.wiki_root(collection) / refine.PROPOSALS / proposal
    if not (found / "meta.json").is_file():
        raise GateError(f"no proposal {proposal!r} in collection {collection!r}")
    return found


def load(collection: str, proposal: str) -> dict[str, Any]:
    return json.loads((directory(collection, proposal) / "meta.json").read_text(encoding="utf-8"))


def _save(collection: str, meta: dict[str, Any]) -> None:
    path = directory(collection, meta["id"]) / "meta.json"
    path.write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")


def proposals(collection: str) -> list[dict[str, Any]]:
    """Every proposal's `meta.json`, oldest first."""
    root = wiki.wiki_root(collection) / refine.PROPOSALS
    if not root.is_dir():
        return []
    return [
        json.loads((d / "meta.json").read_text(encoding="utf-8"))
        for d in sorted(root.iterdir())
        if (d / "meta.json").is_file()
    ]


def _open(meta: dict[str, Any]) -> None:
    if meta.get("status") in FINAL:
        raise GateError(f"{meta['id']} is already {meta['status']}; a decision is final")


# --------------------------------------------------------------------------- apply


def _git(repo: Path, *args: str, check: bool = True) -> str:
    done = subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True, check=False
    )
    if check and done.returncode != 0:
        raise GateError(f"git {' '.join(args)}: {done.stderr.strip() or done.stdout.strip()}")
    return done.stdout.strip()


def apply(collection: str, proposal: str, *, branch: bool = False) -> str:
    """How to apply a proposal, or, with ``branch``, a commit of it on a branch of its own.

    Without ``branch`` nothing is written. With it, the patch is committed on
    `wikiskill/<component>/<id>` and the user is left on the branch they were on.
    """
    meta = load(collection, proposal)
    patch = directory(collection, proposal) / "patch.diff"
    repo = Path(meta["repository"]) if meta.get("repository") else None
    if not branch:
        if repo:
            return f"git -C {repo} apply {patch}"
        return f"patch {meta['source_path']} < {patch}"
    if repo is None:
        raise GateError(f"{meta['source_path']} is not in a git repository; --branch needs one")
    if rawlog.file_hash(meta["source_path"]) != meta["source_hash"]:
        raise GateError(
            f"{meta['source_path']} has changed since {proposal} was made from it; the patch is "
            "for an older version"
        )
    if _git(repo, "status", "--porcelain"):
        raise GateError(f"{repo} has uncommitted changes; commit or stash them first")
    name = f"wikiskill/{meta['component']}/{proposal}"
    # Back to where the user was afterwards: their branch, or the commit a detached HEAD was on.
    on_branch = _git(repo, "symbolic-ref", "--quiet", "--short", "HEAD", check=False)
    back = [on_branch] if on_branch else ["--detach", _git(repo, "rev-parse", "HEAD")]
    _git(repo, "switch", "--quiet", "-c", name)
    try:
        _git(repo, "apply", "--index", str(patch))
        message = f"{meta['component']}: {proposal}\n\n{meta['reason']}"
        _git(repo, "commit", "--quiet", "-m", message)
    except GateError:
        _git(repo, "reset", "--quiet", "--hard", check=False)
        _git(repo, "switch", "--quiet", *back, check=False)
        _git(repo, "branch", "--quiet", "-D", name, check=False)
        raise
    _git(repo, "switch", "--quiet", *back)
    meta["branch"] = name
    _save(collection, meta)
    wiki.commit(wiki.wiki_root(collection), f"put {proposal} on branch {name}")
    return name


# --------------------------------------------------------------------------- candidate runs


def candidate_collection(collection: Collection, proposal: str, into: Path) -> Collection:
    """The collection with the proposal's rendered file in a copy of its source, under ``into``."""
    meta = load(collection.name, proposal)
    _open(meta)
    component = collection.component(meta["component"])
    if component is None:
        raise GateError(f"{meta['component']} is no longer a component of {collection.name}")
    if rawlog.file_hash(component.path) != meta["source_hash"]:
        raise GateError(
            f"{component.path} has changed since {proposal} was made from it, so a run with it "
            "would not test the proposal against the version it was written for"
        )
    source = component.source
    copy = into / "candidate-source"
    shutil.copytree(source.path, copy, symlinks=True, ignore=shutil.ignore_patterns(".git"))
    rendered = directory(collection.name, proposal) / "rendered" / component.path.name
    shutil.copyfile(rendered, copy / component.path.relative_to(source.path))
    sources = tuple(replace(s, path=copy) if s == source else s for s in collection.sources)
    return replace(collection, sources=sources)


# --------------------------------------------------------------------------- replay


def replay(
    collection: str,
    proposal: str,
    baseline: str | Path,
    candidate: str | Path,
    *,
    tolerance: float = DEFAULT_TOLERANCE,
) -> Replay:
    """Compare a baseline and a candidate run of one suite for a proposal, and recommend."""
    meta = load(collection, proposal)
    _open(meta)
    component = meta["component"]
    a, b = compare.load_run(collection, baseline), compare.load_run(collection, candidate)
    hash_a, hash_b = a.hashes().get(component), b.hashes().get(component)
    if hash_a != meta["source_hash"]:
        raise GateError(
            f"the baseline {a.run_id} ran {component} at {hash_a}, not at {proposal}'s "
            f"source_hash {meta['source_hash']}"
        )
    if b.manifest.get("proposal") != proposal and hash_b != meta.get("candidate_hash"):
        raise GateError(
            f"the candidate {b.run_id} neither ran under {proposal} nor ran {component} at its "
            f"rendered hash {meta.get('candidate_hash')}"
        )
    comparison = compare.compare(a, b, component=component)
    motivating, unreplayable = _cases(collection, meta, a)
    bank = [task for task in a.tasks if task not in motivating]
    result = Replay(
        proposal=proposal,
        comparison=comparison,
        motivating=motivating,
        bank=bank,
        unreplayable=unreplayable,
        tolerance=tolerance,
        description_changed=_description_changed(collection, meta),
    )
    _breakdown(result, a, b)
    _neighbours(result, graph_mod.load(collection), component, a, b)
    _recommend(result)
    out = directory(collection, proposal)
    (out / "replay.json").write_text(json.dumps(result.as_dict(), indent=2) + "\n", "utf-8")
    (out / "replay.md").write_text(render(result), encoding="utf-8")
    meta["status"] = REPLAYED
    meta["replay"] = {
        "baseline": a.run_id,
        "candidate": b.run_id,
        "recommendation": result.recommendation,
        "replayed": rawlog.now_ts(),
    }
    _save(collection, meta)
    wiki.commit(wiki.wiki_root(collection), f"replay {proposal}: {result.recommendation}")
    return result


def _cases(
    collection: str, meta: dict[str, Any], run: compare.LoadedRun
) -> tuple[list[str], dict[str, str]]:
    """The suite tasks the cited patterns came from, and the evidence that cannot be replayed."""
    known = wiki.patterns(collection, meta["component"])
    motivating: list[str] = []
    unreplayable: dict[str, str] = {}
    for slug in meta["patterns"]:
        document = known.get(slug)
        for ref in (document.meta.get("evidence") if document else None) or []:
            if "session_id" in ref:
                unreplayable[f"session {ref['session_id']}"] = (
                    "a live session: its workspace and conversation state were not recorded"
                )
            elif ref.get("task_id") in run.tasks:
                if ref["task_id"] not in motivating:
                    motivating.append(ref["task_id"])
            else:
                unreplayable[f"task {ref.get('task_id')} of run {ref.get('run_id')}"] = (
                    f"not a task of suite {run.suite}"
                )
    return sorted(motivating), unreplayable


def _breakdown(result: Replay, a: compare.LoadedRun, b: compare.LoadedRun) -> None:
    models = sorted({r["model"] for r in a.results} & {r["model"] for r in b.results})
    conditions = sorted(
        ({r["condition"] for r in a.results} & {r["condition"] for r in b.results}) - {OFF}
    )
    for condition in conditions:
        for model in models:
            if result.motivating:
                result.motivating_rates[(condition, model)] = (
                    _task_rate(a, condition, model, models, result.motivating),
                    _task_rate(b, condition, model, models, result.motivating),
                )
            for task in a.tasks:
                ra = _task_rate(a, condition, model, models, [task])
                rb = _task_rate(b, condition, model, models, [task])
                if ra.total and rb.total and (rb.rate or 0.0) < (ra.rate or 0.0):
                    result.regressions.append(TaskChange(condition, model, task, ra, rb))


def _description_changed(collection: str, meta: dict[str, Any]) -> bool | None:
    """From `meta.json`, or for an older proposal from its source while that is unchanged."""
    if "description_changed" in meta:
        return meta["description_changed"]
    source = Path(meta["source_path"])
    if not source.is_file() or rawlog.file_hash(source) != meta["source_hash"]:
        return None
    rendered = directory(collection, meta["id"]) / "rendered" / source.name
    try:
        after = rendered.read_text(encoding="utf-8")
        return refine.description_changed(source.read_text(encoding="utf-8"), after)
    except (OSError, FrontmatterError):
        return None


def _expects(run: compare.LoadedRun) -> dict[str, tuple[str | None, tuple[str, ...]]]:
    """Task → its expected primary route and expected agents."""
    found: dict[str, tuple[str | None, tuple[str, ...]]] = {}
    for result in run.results:
        expected = result.get("expected") or {}
        found.setdefault(
            result["task_id"], (expected.get("primary"), tuple(expected.get("agents") or ()))
        )
    return found


def _neighbours(
    result: Replay,
    graph: graph_mod.Graph | None,
    component: str,
    a: compare.LoadedRun,
    b: compare.LoadedRun,
) -> None:
    """Name each neighbour and its tasks, and check conflict neighbours' routes for theft."""
    if graph is None:
        return
    result.graph = True
    expects = _expects(a)
    models = sorted({r["model"] for r in a.results} & {r["model"] for r in b.results})
    for neighbour in graph.neighbours(component):
        name = neighbour.name
        routing = sorted(t for t, (primary, _) in expects.items() if same(primary, name))
        tasks = sorted(
            t
            for t, (primary, agents) in expects.items()
            if same(primary, name) or any(same(agent, name) for agent in agents)
        )
        result.neighbours[name] = {
            "kinds": list(neighbour.kinds),
            "weight": neighbour.weight,
            "tasks": tasks,
            "routing_tasks": routing,
        }
        if not result.description_changed or graph_mod.CONFLICT not in neighbour.kinds:
            continue
        for task in routing:
            for model in models:
                ra, rb = _route_rate(a, task, model), _route_rate(b, task, model)
                if ra.total and rb.total and (rb.rate or 0.0) < (ra.rate or 0.0):
                    result.theft.append(TaskChange(ROUTED, model, task, ra, rb))


def _route_rate(run: compare.LoadedRun, task: str, model: str) -> compare.Rate:
    """route@1 of one task on one model under ROUTED, over its scored repeats."""
    units = [
        r
        for r in run.results
        if r["task_id"] == task
        and r["model"] == model
        and r["condition"] == ROUTED
        and r.get("outcome") not in UNSCORED
    ]
    hits = sum(
        1 for r in units if same(first_activation(r), (r.get("expected") or {}).get("primary"))
    )
    return compare.Rate(passed=hits, total=len(units))


def _task_rate(
    run: compare.LoadedRun, condition: str, model: str, models: list[str], tasks: list[str]
) -> compare.Rate:
    results = [r for r in run.results if r["task_id"] in tasks]
    return compare.rate(results, condition, model, models)


def _recommend(result: Replay) -> None:
    improved = [
        f"{model} ({condition})"
        for (condition, model), (ra, rb) in sorted(result.motivating_rates.items())
        if ra.total and rb.total and (rb.rate or 0.0) > (ra.rate or 0.0)
    ]
    broken = result.beyond_tolerance()
    _neighbour_reasons(result)
    if not result.motivating:
        result.reasons.append("no motivating case is a task of this suite")
    elif improved:
        result.reasons.append("motivating cases improved on " + ", ".join(improved))
    else:
        result.reasons.append("motivating cases improved on no model")
    for change in broken:
        result.reasons.append(
            f"{change.task} fell on {change.model} ({change.condition}) by {change.drop:.0%}, "
            f"beyond the tolerance of {result.tolerance:.0%}"
        )
    if not result.motivating:
        result.recommendation = NO_RECOMMENDATION
    elif improved and not broken:
        # A description edit whose conflict neighbours the suite cannot route is unchecked.
        result.recommendation = NO_RECOMMENDATION if result.unchecked else ACCEPT
    else:
        result.recommendation = DO_NOT_ACCEPT


def _neighbour_reasons(result: Replay) -> None:
    for name in result.uncovered:
        kinds = " and ".join(result.neighbours[name]["kinds"])
        result.reasons.append(
            f"neighbour {name} ({kinds}) is not covered: no task of this suite expects it"
        )
    for change in result.theft:
        result.reasons.append(
            f"trigger theft: {change.task} reached its route first less often on "
            f"{change.model}: {present.count_of(change.a)} -> {present.count_of(change.b)}"
        )
    for name in result.unchecked:
        result.reasons.append(
            f"the description changed and conflict neighbour {name} has no routing task in this "
            "suite, so trigger theft from it cannot be checked"
        )
    if result.description_changed is None:
        result.reasons.append(
            "whether the description changed is not known, so trigger theft was not checked"
        )
    elif result.description_changed and not result.graph:
        result.reasons.append(
            "the description changed, but the collection has no graph: trigger theft was not "
            "checked (`wikiskill graph build`)"
        )


def render(result: Replay) -> str:
    comparison = result.comparison
    lines = [
        f"# Replay of {result.proposal}",
        "",
        f"**Recommendation: {result.recommendation}.** The user decides.",
        "",
        *[f"- {reason}" for reason in result.reasons],
        "",
        f"- baseline `{comparison.a.run_id}`, candidate `{comparison.b.run_id}`",
        f"- motivating cases: {', '.join(result.motivating) or 'none in this suite'}",
        f"- regression bank: {len(result.bank)} task(s)",
        "",
        "## Motivating cases, per model",
        "",
    ]
    if result.motivating_rates:
        lines += ["| condition | model | baseline | candidate |", "|---|---|---|---|"]
        lines += [
            f"| {c} | {m} | {present.of(ra)} | {present.of(rb)} |"
            for (c, m), (ra, rb) in sorted(result.motivating_rates.items())
        ]
    else:
        lines.append("- none to report")
    lines += ["", "## Every task that fell", ""]
    if result.regressions:
        lines += ["| condition | model | task | baseline | candidate | beyond tolerance |"]
        lines.append("|---|---|---|---|---|---|")
        lines += [
            f"| {r.condition} | {r.model} | {r.task} | "
            f"{present.count_of(r.a)} | {present.count_of(r.b)} | "
            f"{'yes' if r.drop > result.tolerance + 1e-9 else 'no'} |"
            for r in result.regressions
        ]
    else:
        lines.append("- none")
    lines += ["", "## Neighbours", ""]
    if not result.graph:
        lines.append("- no collection graph; `wikiskill graph build` adds this section")
    elif not result.neighbours:
        lines.append("- none above the thresholds")
    for name, seen in sorted(result.neighbours.items()):
        tasks = ", ".join(seen["tasks"]) or "not covered by this suite"
        lines.append(f"- {name} ({', '.join(seen['kinds'])}, {seen['weight']:.2f}): {tasks}")
    if result.theft:
        lines += ["", "### Trigger theft: route@1 under routed", ""]
        lines += ["| model | task | baseline | candidate | beyond tolerance |"]
        lines.append("|---|---|---|---|---|")
        lines += [
            f"| {r.model} | {r.task} | {present.count_of(r.a)} | {present.count_of(r.b)} | "
            f"{'yes' if r.drop > result.tolerance + 1e-9 else 'no'} |"
            for r in result.theft
        ]
    lines += ["", "## Not replayable", ""]
    lines += [f"- {what}: {why}" for what, why in sorted(result.unreplayable.items())] or ["- none"]
    lines += ["", compare.render(comparison)]
    return "\n".join(lines)


# --------------------------------------------------------------------------- decide


def decide(collection: str, proposal: str, decision: str, *, note: str = "") -> Path:
    """Record the user's decision in `skill-impact.md`. Changes no pattern and no source."""
    if decision not in DECISIONS:
        raise GateError(f"a decision is one of {', '.join(DECISIONS)}, not {decision!r}")
    meta = load(collection, proposal)
    _open(meta)
    out = directory(collection, proposal)
    replayed = out / "replay.json"
    summary = (
        json.loads(replayed.read_text(encoding="utf-8"))
        if meta.get("status") == REPLAYED and replayed.is_file()
        else None
    )
    now = rawlog.now_ts()
    meta["status"] = DECISIONS[decision]
    meta["decision"] = {"decision": decision, "note": note, "decided": now}
    _save(collection, meta)

    entry = [
        "",
        f"## {proposal}: {decision}",
        "",
        f"- component: `{meta['component']}`",
        f"- recorded: {now}",
        f"- note: {note or '(none)'}",
        f"- patterns: {', '.join(meta['patterns'])}",
        "- evidence: "
        + (", ".join(_ref_label(ref) for ref in (meta.get("evidence") or {}).values()) or "none"),
        *_replay_lines(summary),
        "",
        "### Diff",
        "",
        "```diff",
        (out / "patch.diff").read_text(encoding="utf-8").rstrip(),
        "```",
        "",
    ]
    if decision != "accept" and (out / "proposal.json").is_file():
        entry += [
            "### Proposal",
            "",
            "```json",
            (out / "proposal.json").read_text(encoding="utf-8").rstrip(),
            "```",
            "",
        ]
    root = wiki.ensure(collection)
    target = root / wiki.IMPACT
    with target.open("a", encoding="utf-8") as handle:
        handle.write("\n".join(entry))
    wiki.commit(root, f"{decision} {proposal} for {meta['component']}")
    return target


def _ref_label(ref: dict[str, Any]) -> str:
    if "session_id" in ref:
        return f"`{ref['session_id']}`"
    return f"`{ref.get('run_id')}/{ref.get('task_id')}/{ref.get('condition')}/r{ref.get('repeat')}`"


def _replay_lines(summary: dict[str, Any] | None) -> list[str]:
    if summary is None:
        return ["- replay: not run"]
    base, cand = summary["baseline"], summary["candidate"]
    lines = [
        f"- replay: recommendation {summary['recommendation']}",
        (
            f"- runs: `{base['run_id']}` (`{(base['hash'] or '?')[:12]}`) -> "
            f"`{cand['run_id']}` (`{(cand['hash'] or '?')[:12]}`)"
        ),
        "- pooled:",
    ]
    for row in summary["comparison"]["rows"]:
        if row["model"] == compare.POOLED:
            lines.append(
                f"  - {row['condition']}: {_rate_text(row['a'])} -> {_rate_text(row['b'])}, "
                f"{row['direction']}"
            )
    for row in summary["motivating_rates"]:
        lines.append(
            f"- motivating, {row['model']} ({row['condition']}): {_rate_text(row['a'])} -> "
            f"{_rate_text(row['b'])}"
        )
    for row in summary["regressions"]:
        lines.append(
            f"- fell: {row['task']} on {row['model']} ({row['condition']}): "
            f"{_rate_text(row['a'])} -> {_rate_text(row['b'])}"
        )
    for row in summary.get("theft") or []:
        lines.append(
            f"- trigger theft: {row['task']} on {row['model']}: route@1 "
            f"{_rate_text(row['a'])} -> {_rate_text(row['b'])}"
        )
    for name in summary.get("uncovered") or []:
        lines.append(f"- neighbour not covered: {name}")
    for what, why in sorted(summary["unreplayable"].items()):
        lines.append(f"- not replayable: {what}: {why}")
    return lines


def _rate_text(rate: dict[str, Any]) -> str:
    return present.count(rate["passed"], rate["total"])
