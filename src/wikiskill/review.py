"""Review one component: turn what it did in evaluations and in use into wiki patterns.

Started only by the user, for one component at a time. The maintainer is shown a compact digest
of the evidence under short ids: E1, E2 for eval units, and S1, S2 for live sessions. It also sees
the component's own text and the patterns it already has. Its reply is validated before anything is
written, re-prompted with the problems a bounded number of times, and logged as a failure if it
still fails.

Evidence is sampled, not dumped. Each piece is ranked by its strongest signal, a user's explicit
note first and a clean pass last. Signals and clean evidence each have a quota. Only evidence no
earlier review was shown is eligible, so a review looks at what is new. The whole prompt is capped
by characters, scaled to the maintainer's context when the collection states it, because the
maintainer is often a small local model.

A sample can be persisted (`wikiskill sample`) and answered elsewhere, such as by the maintainer
subagent inside the harness. The reply is then validated against exactly the evidence that sample
showed.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import Any

from . import compare, names, paths, rawlog, wiki
from .collection import Collection
from .errors import WikiskillError
from .frontmatter import read as read_frontmatter
from .runner.base import INFRA_OUTCOMES, OFF, new_run_id
from .runner.opencode import _default_guard_plugin
from .runner.preflight import Endpoint, request_json

DEFAULT_BUDGET = 15_000
#: Below this context, in tokens, the budget shrinks in proportion; never below `MIN_BUDGET`.
FULL_CONTEXT = 65_536
MIN_BUDGET = 4_000
#: How many pieces of evidence with a signal, and how many clean ones, a sample holds at most.
DEFAULT_SIGNALS = 5
DEFAULT_CLEAN = 3
DEFAULT_RETRIES = 2
COMPONENT_TEXT_LIMIT = 3_000
PASSES_PER_TASK = 1
#: Tool calls a harness-served role may make before the guard refuses the rest.
ROLE_MAX_STEPS = 3


class ReviewError(WikiskillError):
    """A review could not be carried out."""


class NothingToReview(ReviewError):
    """Every piece of evidence for the component has been reviewed already."""


#: Eval outcomes that say nothing about the component: the unit never ran, or the harness or the
#: endpoint broke under it.
UNINFORMATIVE = (*INFRA_OUTCOMES, "api_error")

#: Signal ranks, strongest first. A piece of evidence takes the strongest it carries.
NOTE, OUTPUT_EDIT, REPEAT, FAILURE, FOLLOW_UP, UNSCORED, CLEAN = range(7)


@dataclass
class Digest:
    """What the maintainer is shown, and what each id it may cite stands for.

    ``shown`` is the same evidence as watermark keys; ``patterns_seen`` is each existing pattern's
    last update when the digest was made, so a persisted sample can tell when it has gone stale.
    """

    component: str
    text: str
    evidence: dict[str, wiki.Evidence] = field(default_factory=dict)
    runs: list[str] = field(default_factory=list)
    omitted: int = 0
    shown: dict[str, Any] = field(default_factory=lambda: {"eval": [], "sessions": {}})
    patterns_seen: dict[str, str] = field(default_factory=dict)
    budget: int = DEFAULT_BUDGET


@dataclass
class Candidate:
    rank: int
    #: Sorts newest first within a rank: a run id or an event id, both time-ordered.
    newest: str
    text: str
    evidence: wiki.Evidence
    #: An eval unit key, or a live session id.
    key: str
    #: For a live session, the id of its last event.
    mark: str = ""


@dataclass
class Outcome:
    applied: wiki.Applied | None
    attempts: int
    problems: list[str] = field(default_factory=list)
    output: Any = None


# --------------------------------------------------------------------------- evidence


def component_runs(collection: str, component: str) -> list[compare.LoadedRun]:
    """Every finished run that evaluated this component, newest first."""
    directory = paths.evals_dir(collection)
    if not directory.is_dir():
        return []
    found = []
    for root in sorted(directory.iterdir(), reverse=True):
        if not (root / "run.json").is_file():
            continue
        run = compare.load_run(collection, root)
        if component in run.hashes():
            found.append(run)
    return found


def _unit_events(
    raw_root: Path, run_ids: set[str]
) -> dict[tuple[str, str, str, str, int], list[dict[str, Any]]]:
    """Eval events per (run, task, model, condition, repeat), in log order."""
    found: dict[tuple[str, str, str, str, int], list[dict[str, Any]]] = {}
    for file in rawlog.log_files(raw_root):
        for event in rawlog.read_events(file):
            meta = event.get("eval") or {}
            if meta.get("run_id") not in run_ids:
                continue
            key = (
                meta["run_id"],
                meta["task_id"],
                event.get("model") or "",
                meta["condition"],
                meta["repeat"],
            )
            found.setdefault(key, []).append(event)
    return found


def _live_sessions(raw_root: Path, component: str) -> dict[str, list[dict[str, Any]]]:
    """Ordinary-use sessions that activated this component, by root session."""
    found: dict[str, list[dict[str, Any]]] = {}
    for file in rawlog.log_files(raw_root):
        events = list(rawlog.read_events(file))
        if not any(
            e.get("origin") == "live"
            and names.bare((e.get("component") or {}).get("name", "")) == names.bare(component)
            for e in events
        ):
            continue
        root_id = events[0].get("root_session_id") or file.stem
        found.setdefault(root_id, []).extend(events)
    return found


def _summarise(events: Sequence[dict[str, Any]], limit: int = 600) -> tuple[str, str]:
    """The tool calls a unit made, in order, and its last words."""
    calls = []
    final = ""
    for event in events:
        payload = event.get("payload") or {}
        if event.get("type") == "tool_call":
            key = compare.tool_key(event) or "?"
            command = str((payload.get("input") or {}).get("command") or "").strip()
            mark = "" if payload.get("ok", True) else " [refused/failed]"
            calls.append(f"{key}: {command[:80]}{mark}" if command else f"{key}{mark}")
        elif event.get("type") == "assistant_turn" and payload.get("text"):
            final = str(payload["text"])
    return "; ".join(calls)[:limit], final.strip()[:limit]


def budget_for(collection: Collection, role_name: str = "maintainer") -> int:
    """The prompt budget in characters: the default, shrunk for a role with a small context."""
    role = collection.roles.get(role_name)
    context = role.context_tokens if role else None
    if not context or context >= FULL_CONTEXT:
        return DEFAULT_BUDGET
    return max(MIN_BUDGET, DEFAULT_BUDGET * context // FULL_CONTEXT)


def digest(
    collection: Collection,
    component: str,
    *,
    runs: Sequence[compare.LoadedRun] | None = None,
    budget: int | None = None,
    raw_root: Path | None = None,
    signals: int = DEFAULT_SIGNALS,
    clean: int = DEFAULT_CLEAN,
    resample: bool = False,
) -> Digest:
    """The maintainer's whole input for one component, within ``budget`` characters.

    Raises `NothingToReview` when every piece of evidence has been reviewed before, and
    `ReviewError` when there never was any.
    """
    found = collection.component(component)
    if found is None:
        raise ReviewError(f"{component!r} is not a component of collection {collection.name!r}")
    source_text = found.path.read_text(encoding="utf-8")[:COMPONENT_TEXT_LIMIT]
    budget = budget if budget is not None else budget_for(collection)

    runs = list(runs) if runs is not None else component_runs(collection.name, component)
    root = raw_root or paths.raw_dir(collection.name)
    events = _unit_events(root, {run.run_id for run in runs})
    candidates = _eval_candidates(component, runs, events) + _live_candidates(component, root)
    if not candidates:
        raise ReviewError(
            f"nothing to review for {component}: no eval run or live session recorded it"
        )
    if not resample:
        candidates = _unprocessed(candidates, *wiki.processed(collection.name, component))
        if not candidates:
            raise NothingToReview(
                f"nothing new to review for {component}: every eval unit and live session that "
                "recorded it has been reviewed (--resample reviews them again)"
            )

    existing = wiki.patterns(collection.name, component)
    header = _header(component, source_text, existing)
    result = Digest(
        component=component,
        text="",
        runs=[run.run_id for run in runs],
        patterns_seen={slug: str(doc.meta.get("updated") or "") for slug, doc in existing.items()},
        budget=budget,
    )
    chosen, held = _choose(candidates, signals, clean)
    blocks = _fit(chosen, result, budget - len(header))
    result.omitted += held
    if not result.evidence:
        raise ReviewError(
            f"no evidence for {component} fits a budget of {budget} characters; raise --budget"
        )
    omitted = (
        f"\n({result.omitted} more pieces of evidence wait for a later review)"
        if result.omitted
        else ""
    )
    result.text = header + "\n\n".join(blocks) + omitted + "\n"
    return result


def cited_digest(
    collection: Collection,
    component: str,
    refs: Sequence[dict[str, Any]],
    *,
    budget: int,
    raw_root: Path | None = None,
) -> Digest:
    """The evidence behind ``refs``, rendered and labelled as review renders it, strongest first.

    What the proposer reads: the units and sessions its patterns were drawn from. A ref whose run or
    session is no longer on disk is left out, and so cannot be cited.
    """
    run_ids = {str(ref["run_id"]) for ref in refs if "run_id" in ref}
    wanted = {_ref_key(ref) for ref in refs}
    # Only the cited units, so review's one-pass-per-task thinning cannot drop a cited pass.
    runs = [
        replace(run, results=tuple(r for r in run.results if _ref_key(r) in wanted))
        for run in component_runs(collection.name, component)
        if run.run_id in run_ids
    ]
    root = raw_root or paths.raw_dir(collection.name)
    events = _unit_events(root, run_ids)
    found = [
        c
        for c in _eval_candidates(component, runs, events) + _live_candidates(component, root)
        if _ref_key(c.evidence.ref) in wanted
    ]
    found.sort(key=lambda c: c.newest, reverse=True)
    found.sort(key=lambda c: c.rank)
    result = Digest(component=component, text="", runs=sorted(run_ids), budget=budget)
    result.text = "\n\n".join(_fit(found, result, budget)) + "\n"
    return result


def _ref_key(ref: dict[str, Any]) -> tuple[str, ...]:
    """An evidence ref without its model, which refs written before step 7 do not carry.

    Also keys an eval result, which carries its harness's `session_id` beside its `run_id`; only a
    live session's ref has no `run_id`.
    """
    if "run_id" not in ref:
        return (str(ref["session_id"]),)
    return tuple(str(ref.get(k)) for k in ("run_id", "task_id", "condition", "repeat"))


def _unprocessed(
    candidates: list[Candidate], units: set[str], sessions: dict[str, str]
) -> list[Candidate]:
    """What no earlier review was shown. A live session is new again once it has gained events."""
    return [
        c
        for c in candidates
        if (c.mark and sessions.get(c.key) != c.mark) or (not c.mark and c.key not in units)
    ]


def _choose(candidates: list[Candidate], signals: int, clean: int) -> tuple[list[Candidate], int]:
    """Strongest signal first, newest first within a rank, each kind up to its quota.

    Within a rank, evidence the component took part in comes before OFF units, which ran without
    it: an OFF failure says what the task needs, never what the component's text did, so OFF units
    alone filling the quota leaves the maintainer nothing to review.
    """
    ordered = sorted(candidates, key=lambda c: c.newest, reverse=True)
    ordered.sort(key=lambda c: (c.rank, c.evidence.ref.get("condition") == OFF))
    with_signal = [c for c in ordered if c.rank != CLEAN][:signals]
    without = [c for c in ordered if c.rank == CLEAN][:clean]
    chosen = with_signal + without
    return chosen, len(candidates) - len(chosen)


def _eval_candidates(
    component: str,
    runs: Sequence[compare.LoadedRun],
    events: dict[tuple[str, str, str, str, int], list[dict[str, Any]]],
) -> list[Candidate]:
    """One candidate per eval unit of this component; one passing unit per task is enough."""
    found: list[Candidate] = []
    passes_seen: dict[tuple[str, str], int] = {}
    for run in runs:
        source_hash = run.hashes().get(component)
        harness = run.manifest.get("harness") or "unknown"
        for result in run.results:
            expected = (result.get("expected") or {}).get("primary")
            if (expected and names.bare(expected) != names.bare(component)) or result.get(
                "outcome"
            ) in UNINFORMATIVE:
                continue
            passed = result.get("passed")
            if passed:
                seen = passes_seen.get((run.run_id, result["task_id"]), 0)
                if seen >= PASSES_PER_TASK:
                    continue
                passes_seen[(run.run_id, result["task_id"])] = seen + 1
            key = (
                run.run_id,
                result["task_id"],
                result["model"].split("/", 1)[-1],
                result["condition"],
                result["repeat"],
            )
            ref = {
                "run_id": run.run_id,
                "task_id": result["task_id"],
                "condition": result["condition"],
                "repeat": result["repeat"],
                "model": result["model"],
            }
            evidence = wiki.Evidence(
                id="",
                component=component,
                model=result["model"],
                harness=harness,
                source_hash=source_hash,
                ref=ref,
            )
            found.append(
                Candidate(
                    rank=_eval_rank(result),
                    newest=run.run_id,
                    text=_describe(result, events.get(key, [])),
                    evidence=evidence,
                    key=_unit_key(ref),
                )
            )
    return found


def _eval_rank(result: dict[str, Any]) -> int:
    if result.get("passed") is False or result.get("outcome") not in (None, "completed"):
        return FAILURE
    return UNSCORED if result.get("passed") is None else CLEAN


def _unit_key(ref: dict[str, Any]) -> str:
    return "/".join(str(ref[k]) for k in ("run_id", "task_id", "model", "condition", "repeat"))


def _describe(result: dict[str, Any], events: Sequence[dict[str, Any]]) -> str:
    tools, final = _summarise(events)
    failed_checks = [
        v.get("detail") or v.get("kind")
        for v in result.get("verifiers") or []
        if not v.get("passed")
    ]
    head = (
        f"task={result['task_id']} condition={result['condition']} model={result['model']} "
        f"outcome={result['outcome']} passed={result.get('passed')}"
    )
    lines = [head]
    if result.get("reason"):
        lines.append(f"  reason: {str(result['reason'])[:200]}")
    if failed_checks:
        lines.append("  failed checks: " + "; ".join(str(c)[:160] for c in failed_checks))
    if tools:
        lines.append(f"  tools: {tools}")
    if final:
        lines.append(f"  final reply: {final}")
    return "\n".join(lines)


#: How many follow-up turns a live digest quotes, and how much of each signal's text.
FOLLOW_UPS_SHOWN = 2
SIGNAL_TEXT_LIMIT = 300


def _live_candidates(component: str, root: Path) -> list[Candidate]:
    found: list[Candidate] = []
    for session_id, session_events in sorted(_live_sessions(root, component).items()):
        tools, final = _summarise(session_events)
        first = session_events[0]
        model = "/".join(p for p in (first.get("provider"), first.get("model")) if p)
        evidence = wiki.Evidence(
            id="",
            component=component,
            model=model or "unknown",
            harness=first.get("harness") or "unknown",
            source_hash=_live_source_hash(session_events, component),
            ref={"session_id": session_id},
        )
        rank, signal_lines = _signals(session_events, component)
        lines = [f"live session model={model}", *signal_lines]
        if tools:
            lines.append(f"  tools: {tools}")
        if final:
            lines.append(f"  final reply: {final}")
        last = max((str(e.get("event_id") or "") for e in session_events), default="")
        found.append(
            Candidate(
                rank=rank,
                newest=last,
                text="\n".join(lines),
                evidence=evidence,
                key=session_id,
                mark=last or session_id,
            )
        )
    return found


def _live_source_hash(events: Sequence[dict[str, Any]], component: str) -> str | None:
    """The version of the component the session ran: the hash on its activation."""
    for event in events:
        ref = event.get("component") or {}
        if names.bare(ref.get("name", "")) == names.bare(component) and ref.get("source_hash"):
            return ref["source_hash"]
    return None


def _signals(events: Sequence[dict[str, Any]], component: str) -> tuple[int, list[str]]:
    """A live session's strongest signal for this component, and a line for each it carries.

    A signal attributed to another component is not this one's; a note attributed to none is kept,
    since the session did activate this component.
    """
    rank, lines, follow_ups, failures = CLEAN, [], 0, 0
    for event in events:
        kind, payload = event.get("type"), event.get("payload") or {}
        if kind == "tool_call" and payload.get("ok") is False:
            failures += 1
            rank = min(rank, FAILURE)
            continue
        named = (event.get("component") or {}).get("name")
        if named and names.bare(named) != names.bare(component):
            continue
        if kind == "note":
            rank = min(rank, NOTE)
            lines.append(f"  user note: {_clip(payload.get('text'))}")
        elif kind == "output_edit":
            rank = min(rank, OUTPUT_EDIT)
            lines.append(
                f"  user edited {payload.get('path')} after it was written: "
                f"{_clip(payload.get('diff'))}"
            )
        elif kind == "repeat_activation":
            rank = min(rank, REPEAT)
            lines.append(f"  run again after {payload.get('turns_since_previous')} user turn(s)")
        elif kind == "user_turn":
            rank = min(rank, FOLLOW_UP)
            follow_ups += 1
            if follow_ups <= FOLLOW_UPS_SHOWN:
                lines.append(
                    f"  user said next ({event.get('confidence')} confidence): "
                    f"{_clip(payload.get('text'))}"
                )
    if follow_ups > FOLLOW_UPS_SHOWN:
        lines.append(f"  ({follow_ups - FOLLOW_UPS_SHOWN} more follow-up turns)")
    if failures:
        lines.append(f"  failed tool calls: {failures}")
    return rank, lines


def _clip(text: Any) -> str:
    text = " ".join(str(text or "").split())
    return text if len(text) <= SIGNAL_TEXT_LIMIT else text[:SIGNAL_TEXT_LIMIT] + "…"


def _fit(candidates: list[Candidate], result: Digest, budget: int) -> list[str]:
    """Number the evidence in the order given and keep what fits; the rest is counted as omitted."""
    blocks: list[str] = []
    used = 0
    counters = {"E": 0, "S": 0}
    for candidate in candidates:
        item = candidate.evidence
        prefix = "S" if "session_id" in item.ref else "E"
        label = f"{prefix}{counters[prefix] + 1}"
        block = f"[{label}] {candidate.text}"
        if used + len(block) + 2 > budget:
            result.omitted += 1
            continue
        counters[prefix] += 1
        used += len(block) + 2
        blocks.append(block)
        result.evidence[label] = wiki.Evidence(
            id=label,
            component=item.component,
            model=item.model,
            harness=item.harness,
            source_hash=item.source_hash,
            ref=item.ref,
        )
        if candidate.mark:
            result.shown["sessions"][candidate.key] = candidate.mark
        else:
            result.shown["eval"].append(candidate.key)
    return blocks


def _header(component: str, source_text: str, existing: dict[str, Any]) -> str:
    lines = [
        f"# Component under review: {component}",
        "",
        "## Its instructions (possibly truncated)",
        "",
        source_text.strip(),
        "",
        "## Patterns it already has",
        "",
    ]
    active = {
        slug: doc for slug, doc in existing.items() if doc.meta.get("status") != wiki.SUPERSEDED
    }
    if active:
        for slug, document in sorted(active.items()):
            meta = document.meta
            lines.append(
                f"- {slug}: {meta.get('summary') or meta.get('title')} "
                f"(cause {meta.get('cause')}, models {', '.join(meta.get('models') or [])})"
            )
    else:
        lines.append("- none yet")
    lines += ["", "## Evidence, strongest signal first", "", ""]
    return "\n".join(lines)


# --------------------------------------------------------------------------- persisted samples


def samples_dir(collection: str) -> Path:
    return paths.collection_data(collection) / "samples"


def save_sample(collection: Collection, found: Digest) -> tuple[str, Path]:
    """Persist a digest so a reply written elsewhere is checked against exactly this evidence."""
    sample_id = new_run_id()
    directory = samples_dir(collection.name) / sample_id
    directory.mkdir(parents=True)
    (directory / "prompt.md").write_text(found.text, encoding="utf-8")
    (directory / "instructions.md").write_text(maintainer_prompt() + "\n", encoding="utf-8")
    evidence = {label: asdict(item) for label, item in found.evidence.items()}
    (directory / "evidence.json").write_text(json.dumps(evidence, indent=2) + "\n", "utf-8")
    meta = {
        "sample_id": sample_id,
        "collection": collection.name,
        "component": found.component,
        "runs": found.runs,
        "budget": found.budget,
        "omitted": found.omitted,
        "shown": found.shown,
        "patterns_seen": found.patterns_seen,
        "taken": rawlog.now_ts(),
    }
    (directory / "sample.json").write_text(json.dumps(meta, indent=2) + "\n", "utf-8")
    return sample_id, directory


def load_sample(collection: Collection, sample: str) -> Digest:
    """A persisted digest, by id or directory; refused once the component's patterns moved on."""
    directory = Path(sample) if Path(sample).is_dir() else samples_dir(collection.name) / sample
    try:
        meta = json.loads((directory / "sample.json").read_text(encoding="utf-8"))
        evidence = json.loads((directory / "evidence.json").read_text(encoding="utf-8"))
        text = (directory / "prompt.md").read_text(encoding="utf-8")
    except (OSError, json.JSONDecodeError) as exc:
        raise ReviewError(f"no readable sample at {directory}: {exc}") from exc
    if meta.get("collection") != collection.name:
        raise ReviewError(
            f"sample {directory.name} was taken from collection {meta.get('collection')!r}"
        )
    component = meta["component"]
    now = {
        slug: str(doc.meta.get("updated") or "")
        for slug, doc in wiki.patterns(collection.name, component).items()
    }
    if now != meta.get("patterns_seen", {}):
        raise ReviewError(
            f"sample {directory.name} is stale: {component}'s patterns changed after it was "
            "taken, so the maintainer saw a list that no longer holds. Take a new sample."
        )
    return Digest(
        component=component,
        text=text,
        evidence={label: wiki.Evidence(**item) for label, item in evidence.items()},
        runs=list(meta.get("runs") or []),
        omitted=int(meta.get("omitted") or 0),
        shown=meta.get("shown") or {"eval": [], "sessions": {}},
        patterns_seen=meta.get("patterns_seen") or {},
        budget=int(meta.get("budget") or DEFAULT_BUDGET),
    )


# --------------------------------------------------------------------------- the maintainer


def maintainer_prompt() -> str:
    """The maintainer's instructions: the body of its single-source agent definition."""
    path = paths.source_tree() / "agents" / "wikiskill-maintainer.md"
    return read_frontmatter(path).body.strip()


Ask = Callable[[list[dict[str, str]]], str]


def role_asker(
    collection: Collection, role_name: str = "maintainer", timeout_s: int = 600
) -> tuple[Ask, str]:
    """How to reach a meta-role: its own endpoint, or, with no `base_url`, the harness.

    A model the harness serves itself — `opencode/big-pickle` is the case in point — refuses a
    direct HTTP request and answers only through `opencode run`.
    """
    role = collection.roles.get(role_name)
    if role is None:
        raise ReviewError(f"collection {collection.name!r} configures no `[roles.{role_name}]`")
    if role.base_url:
        return endpoint_asker(collection, role_name, timeout_s)
    return harness_asker(role.model, timeout_s=timeout_s), role.model


def harness_flatten(messages: Sequence[dict[str, str]]) -> str:
    """One prompt from a conversation, for a harness that takes a single message per run.

    The harness's default agent is a coding agent, so it is told outright that this is a question
    to answer in text: everything it needs is in the prompt.
    """
    parts = [
        (
            "Answer in text only. Do not use any tools: they are disabled, and everything you "
            "need is below."
        )
    ]
    for message in messages:
        heading = {
            "system": "# Your instructions",
            "user": "# Input",
            "assistant": "# Your previous reply",
        }.get(message["role"], f"# {message['role']}")
        parts.append(f"{heading}\n\n{message['content'].strip()}")
    return "\n\n".join(parts) + "\n"


def harness_asker(
    model: str,
    *,
    executable: str = "opencode",
    timeout_s: int = 600,
    guard: Path | None = None,
) -> Ask:
    """Ask a model through `opencode run`, in an isolated root, where no command can run.

    The role only has to answer in text. A fresh config and data root keep the user's own skills,
    agents and MCP servers out of its context, and file edits are denied.

    Shell commands cannot simply be denied too: OpenCode's free tier refuses a request whose `bash`
    tool is switched off (`FreeTierError`, checked on 2026-09-22). So `bash` stays declared and the
    evaluation guard refuses every command instead, and without the guard nothing is run at all.
    """
    guard = guard or _default_guard_plugin()
    if guard is None or not guard.is_file():
        raise ReviewError(
            "the evaluation guard plugin is missing, so no role is run through the harness"
        )
    config = {
        "$schema": "https://opencode.ai/config.json",
        "autoupdate": False,
        "share": "disabled",
        "mcp": {},
        "plugin": [str(guard)],
        "permission": {
            "edit": "deny",
            "bash": {"*": "allow"},
            "webfetch": "deny",
            "external_directory": "deny",
        },
    }

    def ask(messages: list[dict[str, str]]) -> str:
        root = Path(tempfile.mkdtemp(prefix="wikiskill-role-"))
        try:
            env = dict(os.environ)
            env.update(
                {
                    "XDG_CONFIG_HOME": str(root / "config"),
                    "XDG_DATA_HOME": str(root / "data"),
                    "XDG_STATE_HOME": str(root / "state"),
                    "XDG_CACHE_HOME": str(root / "cache"),
                    "OPENCODE_CONFIG_CONTENT": json.dumps(config),
                    "OPENCODE_DISABLE_PROJECT_CONFIG": "true",
                    "OPENCODE_DISABLE_CLAUDE_CODE": "1",
                    "WIKISKILL_GUARD_DENY": json.dumps(["*"]),
                    # A role answers in text. Past a few tool calls the guard refuses the rest,
                    # which pushes a model that went exploring back to answering.
                    "WIKISKILL_MAX_STEPS": str(ROLE_MAX_STEPS),
                }
            )
            env.pop("OPENCODE_CONFIG", None)
            work = root / "work"
            work.mkdir()
            try:
                done = subprocess.run(
                    [
                        executable,
                        "run",
                        "--format",
                        "json",
                        "--dir",
                        str(work),
                        "-m",
                        model,
                        harness_flatten(messages),
                    ],
                    capture_output=True,
                    text=True,
                    timeout=timeout_s,
                    env=env,
                    check=False,
                )
            except subprocess.TimeoutExpired as exc:
                partial = (
                    exc.stdout.decode(errors="replace")
                    if isinstance(exc.stdout, bytes)
                    else (exc.stdout or "")
                )
                raise ReviewError(
                    f"{model} did not answer within {timeout_s}s; {_stream_summary(partial)}"
                ) from exc
            except OSError as exc:
                raise ReviewError(f"cannot run {executable}: {exc}") from exc
            text = _stream_text(done.stdout)
            if not text:
                tail = (done.stderr.strip().splitlines() or ["no output"])[-1]
                raise ReviewError(f"{model} gave no answer through {executable}: {tail}")
            return text
        finally:
            shutil.rmtree(root, ignore_errors=True)

    return ask


def _stream_summary(stdout: str) -> str:
    """What a stream got as far as, for an error message: event counts and the last error."""
    counts: dict[str, int] = {}
    last_error = ""
    for line in stdout.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict):
            continue
        kind = str(event.get("type"))
        counts[kind] = counts.get(kind, 0) + 1
        if kind == "error":
            last_error = str(((event.get("error") or {}).get("data") or {}).get("message", ""))[
                :160
            ]
    if not counts:
        return "the stream was empty"
    seen = ", ".join(f"{n} {k}" for k, n in sorted(counts.items()))
    return f"the stream had {seen}" + (f"; last error: {last_error}" if last_error else "")


def _stream_text(stdout: str) -> str:
    """The assistant's text from an `opencode run --format json` stream."""
    chunks = []
    for line in stdout.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        part = event.get("part") if isinstance(event, dict) else None
        if isinstance(part, dict) and part.get("type") == "text" and part.get("text"):
            chunks.append(str(part["text"]))
    return "\n".join(chunks).strip()


def endpoint_asker(
    collection: Collection, role_name: str = "maintainer", timeout_s: int = 600
) -> tuple[Ask, str]:
    """A function sending messages to one of the collection's role endpoints, and its model."""
    role = collection.roles.get(role_name)
    if role is None or not role.base_url:
        raise ReviewError(
            f"collection {collection.name!r} configures no `[roles.{role_name}]` endpoint"
        )
    endpoint = Endpoint(
        role.base_url, api_key=os.environ.get(role.api_key_env) if role.api_key_env else None
    )

    def ask(messages: list[dict[str, str]]) -> str:
        payload = {
            "model": names.bare(role.model),  # the last segment, as the endpoint serves it
            "messages": messages,
            "temperature": 0,
            "stream": False,
        }
        try:
            status, body = request_json(
                f"{endpoint.root}/chat/completions",
                payload=payload,
                api_key=endpoint.api_key,
                timeout=timeout_s,
            )
        except OSError as exc:
            raise ReviewError(f"the {role_name} endpoint is unreachable: {exc}") from exc
        if status != 200:
            raise ReviewError(f"the {role_name} endpoint answered {status}: {str(body)[:200]}")
        for choice in (body or {}).get("choices") or []:
            content = (choice.get("message") or {}).get("content")
            if isinstance(content, str):
                return content
        raise ReviewError(f"the {role_name}'s reply had no message content")

    return ask, role.model


def review(
    collection: Collection,
    component: str,
    *,
    ask: Ask,
    maintainer: str,
    runs: Sequence[compare.LoadedRun] | None = None,
    budget: int | None = None,
    retries: int = DEFAULT_RETRIES,
    raw_root: Path | None = None,
    signals: int = DEFAULT_SIGNALS,
    clean: int = DEFAULT_CLEAN,
    resample: bool = False,
    sample: Digest | None = None,
) -> Outcome:
    """Show the maintainer the evidence, validate its reply, and apply it or log the failure.

    ``sample`` is a digest taken earlier, for a reply written against it; otherwise one is taken
    now. Raises `NothingToReview`, before any model is asked, when nothing new is there.
    """
    found = sample or digest(
        collection,
        component,
        runs=runs,
        budget=budget,
        raw_root=raw_root,
        signals=signals,
        clean=clean,
        resample=resample,
    )
    existing = {slug: doc.meta for slug, doc in wiki.patterns(collection.name, component).items()}
    taken = set(wiki.patterns(collection.name))
    messages = [
        {"role": "system", "content": maintainer_prompt()},
        {"role": "user", "content": found.text},
    ]
    problems: list[str] = []
    output: Any = None
    for attempt in range(1, retries + 2):
        reply = ask(messages)
        try:
            output = wiki.parse_reply(reply)
            problems = wiki.validate(
                output,
                component=component,
                evidence=found.evidence,
                existing=existing,
                taken=taken,
            )
        except wiki.WikiError as exc:
            problems = [str(exc)]
        if not problems:
            applied = wiki.apply(
                collection.name,
                output,
                component=component,
                evidence=found.evidence,
                maintainer=maintainer,
                runs=found.runs,
                shown=found.shown,
            )
            return Outcome(applied=applied, attempts=attempt, output=output)
        messages += [
            {"role": "assistant", "content": reply},
            {
                "role": "user",
                "content": (
                    "Your reply cannot be applied. Fix these problems and reply with the whole "
                    "JSON object again, nothing else:\n- " + "\n- ".join(problems)
                ),
            },
        ]
    wiki.record_failure(
        collection.name,
        component,
        maintainer=maintainer,
        attempts=retries + 1,
        problems=problems,
    )
    return Outcome(applied=None, attempts=retries + 1, problems=problems, output=output)
