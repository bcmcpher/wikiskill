"""Review one component: turn what it did in evaluations and in use into wiki patterns.

Started only by the user, for one component at a time. The maintainer is shown a compact digest
of the evidence, failures first, under short ids: E1, E2 for eval units, and S1, S2 for live
sessions. It also sees the component's own text and the patterns it already has. Its reply is
validated before anything is written, re-prompted with the problems a bounded number of times, and
dropped if it still fails. The whole prompt is capped by characters, because the maintainer is often
a small local model with a small context.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import compare, paths, rawlog, wiki
from .collection import Collection
from .frontmatter import read as read_frontmatter
from .runner.opencode import _default_guard_plugin
from .runner.preflight import Endpoint, request_json

DEFAULT_BUDGET = 12_000
DEFAULT_RETRIES = 2
COMPONENT_TEXT_LIMIT = 3_000
PASSES_PER_TASK = 1
#: Tool calls a harness-served role may make before the guard refuses the rest.
ROLE_MAX_STEPS = 3


class ReviewError(Exception):
    """A review could not be carried out."""


@dataclass
class Digest:
    """What the maintainer is shown, and what each id it may cite stands for."""

    component: str
    text: str
    evidence: dict[str, wiki.Evidence] = field(default_factory=dict)
    runs: list[str] = field(default_factory=list)
    omitted: int = 0


@dataclass
class Outcome:
    applied: wiki.Applied | None
    attempts: int
    problems: list[str] = field(default_factory=list)
    output: Any = None


# --------------------------------------------------------------------------- evidence


def _bare(name: str) -> str:
    return name.rsplit("/", 1)[-1]


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
            and _bare((e.get("component") or {}).get("name", "")) == _bare(component)
            for e in events
        ):
            continue
        root_id = events[0].get("root_session_id") or file.stem
        found[root_id] = events
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


Candidate = tuple[int, str, wiki.Evidence]


def digest(
    collection: Collection,
    component: str,
    *,
    runs: Sequence[compare.LoadedRun] | None = None,
    budget: int = DEFAULT_BUDGET,
    raw_root: Path | None = None,
) -> Digest:
    """The maintainer's whole input for one component, within ``budget`` characters."""
    matches = [c for c in collection.discover() if c.name == component]
    if not matches:
        raise ReviewError(f"{component!r} is not a component of collection {collection.name!r}")
    source_text = matches[0].path.read_text(encoding="utf-8")[:COMPONENT_TEXT_LIMIT]

    runs = list(runs) if runs is not None else component_runs(collection.name, component)
    root = raw_root or paths.raw_dir(collection.name)
    events = _unit_events(root, {run.run_id for run in runs})
    candidates = _eval_candidates(component, runs, events) + _live_candidates(component, root)

    header = _header(component, source_text, wiki.patterns(collection.name, component))
    result = Digest(component=component, text="", runs=[run.run_id for run in runs])
    blocks = _fit(candidates, result, budget - len(header))
    if not result.evidence:
        raise ReviewError(
            f"nothing to review for {component}: no eval run or live session recorded it"
        )
    omitted = f"\n({result.omitted} more pieces of evidence did not fit)" if result.omitted else ""
    result.text = header + "\n\n".join(blocks) + omitted + "\n"
    return result


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
            if (expected and _bare(expected) != _bare(component)) or result.get(
                "outcome"
            ) == "skipped":
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
            priority = 0 if passed is False else (1 if passed is None else 2)
            evidence = wiki.Evidence(
                id="",
                component=component,
                model=result["model"],
                harness=harness,
                source_hash=source_hash,
                ref=ref,
            )
            found.append((priority, _describe(result, events.get(key, [])), evidence))
    return found


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
            source_hash=(first.get("component") or {}).get("source_hash"),
            ref={"session_id": session_id},
        )
        text = f"live session model={model}\n  tools: {tools}\n  final reply: {final}"
        found.append((1, text, evidence))
    return found


def _fit(candidates: list[Candidate], result: Digest, budget: int) -> list[str]:
    """Number the evidence, failures first, and keep what fits; the rest is counted as omitted."""
    blocks: list[str] = []
    used = 0
    counters = {"E": 0, "S": 0}
    for _, text, item in sorted(candidates, key=lambda c: c[0]):
        prefix = "S" if "session_id" in item.ref else "E"
        label = f"{prefix}{counters[prefix] + 1}"
        block = f"[{label}] {text}"
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
    if existing:
        for slug, document in sorted(existing.items()):
            meta = document.meta
            lines.append(
                f"- {slug}: {meta.get('summary') or meta.get('title')} "
                f"(cause {meta.get('cause')}, models {', '.join(meta.get('models') or [])})"
            )
    else:
        lines.append("- none yet")
    lines += ["", "## Evidence, failures first", "", ""]
    return "\n".join(lines)


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
            "model": role.model.rsplit("/", 1)[-1] if "/" in role.model else role.model,
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
    budget: int = DEFAULT_BUDGET,
    retries: int = DEFAULT_RETRIES,
    raw_root: Path | None = None,
) -> Outcome:
    """Show the maintainer the evidence, validate its reply, and apply it or nothing."""
    found = digest(collection, component, runs=runs, budget=budget, raw_root=raw_root)
    existing = set(wiki.patterns(collection.name, component))
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
    return Outcome(applied=None, attempts=retries + 1, problems=problems, output=output)
