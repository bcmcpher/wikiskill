"""The OpenCode evaluation backend: isolate, run headless, export, normalise.

Isolation is the whole point. A run must not see the developer's global config, project config,
Claude Code skills, MCP servers or plugins, because any of those would change what the model is
offered and quietly invalidate the comparison. OpenCode has no switch for "ignore global config", so
each run gets its own XDG directories, an inline config passed through
`OPENCODE_CONFIG_CONTENT`, and a throwaway git-initialised working directory.

What the model then did is read back twice: the `run --format json` stream says how the run ended,
and `opencode export` gives the full session — including every child session a `task` delegation
spawned — which is what becomes raw events.
"""

from __future__ import annotations

import contextlib
import json
import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

from .. import RAW_SCHEMA_VERSION, build, paths, rawlog
from ..collection import Collection
from .base import INJECTED, OFF, ROUTED, Backend, PreflightResult, RunnerError, Trajectory, Unit
from .preflight import MIN_CONTEXT_TOKENS, Endpoint, check

#: Commands no evaluation may run, whatever a suite says. A task's own `guard.deny` adds to these.
BASE_DENY = (
    "git push*",
    "*git push*",
    "datalad push*",
    "sudo *",
    "ssh *",
    "rm -rf /*",
    "npm publish*",
    "pip install*",
    "uv publish*",
    "curl *",
    "wget *",
)

#: Tool parts whose error text means the harness or the guard refused the call, not that it failed.
_BLOCKED_MARKERS = ("wikiskill evaluation guard", "permission denied by", "rejected", "not allowed")

#: Shapes a model emits when it describes a tool call instead of making one.
_TOOL_SHAPED = ('"tool_call"', '"function_call"', "<tool_call>", '"tool_name"', '"arguments":')

_SKILL_TOOLS = {"skill", "skills"}
_TASK_TOOLS = {"task", "agent"}


def _ts(ms: int | float | None) -> str:
    """An RFC 3339 timestamp from harness epoch milliseconds, matching what the plugin writes."""
    when = time.time() if not ms else float(ms) / 1000.0
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(when)) + f".{int((when % 1) * 1000):03d}Z"


def _string_field(source: dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = source.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def _bound(text: str, limit: int) -> tuple[str, bool]:
    encoded = text.encode("utf-8")
    if len(encoded) <= limit:
        return text, False
    return encoded[:limit].decode("utf-8", "ignore"), True


class OpenCodeBackend(Backend):
    """Runs a unit in a fresh, isolated headless OpenCode session."""

    harness = "opencode"

    def __init__(
        self,
        *,
        collection: Collection | None,
        endpoint: Endpoint,
        layout,
        suite_root: Path,
        executable: str = "opencode",
        min_context: int = MIN_CONTEXT_TOKENS,
        output_limit_bytes: int = 16 * 1024,
        guard_plugin: Path | None = None,
    ) -> None:
        self.collection = collection
        self.endpoint = endpoint
        self.layout = layout
        self.suite_root = suite_root
        self.executable = executable
        self.min_context = min_context
        self.output_limit_bytes = output_limit_bytes
        self.guard_plugin = guard_plugin or _default_guard_plugin()
        self._version: str | None = None

    # ------------------------------------------------------------------ identity

    def version(self) -> str:
        if self._version is None:
            try:
                done = subprocess.run(
                    [self.executable, "--version"],
                    capture_output=True,
                    text=True,
                    timeout=30,
                    check=False,
                )
                self._version = done.stdout.strip() or "unknown"
            except (OSError, subprocess.SubprocessError) as exc:
                raise RunnerError(
                    f"cannot run {self.executable!r}: {exc}. Install OpenCode, or pass "
                    "--opencode with a path to it."
                ) from exc
        return self._version

    def preflight(self, model: str) -> PreflightResult:
        return check(self.endpoint, _model_id(model), min_context=self.min_context)

    # ------------------------------------------------------------------ isolation

    def prepare(self, unit: Unit) -> Path:
        """Build the unit's isolated root and return its working directory."""
        root = self.layout.unit_dir(unit)
        for name in ("config", "data", "state", "cache"):
            (root / name).mkdir(parents=True, exist_ok=True)
        workdir = root / "work"
        if workdir.exists():
            shutil.rmtree(workdir)
        fixtures = self.suite_root / unit.task.fixtures if unit.task.fixtures else None
        if fixtures and fixtures.is_dir():
            shutil.copytree(fixtures, workdir)
        else:
            if fixtures:
                raise RunnerError(
                    f"task {unit.task.id!r} names a fixture directory that is not there: {fixtures}"
                )
            workdir.mkdir(parents=True)
        _git_init(workdir)

        (root / "config.json").write_text(
            json.dumps(self.config_for(unit), indent=2) + "\n", encoding="utf-8"
        )
        if unit.condition == ROUTED and self.collection is not None:
            self._install_collection(root)
        return workdir

    def _install_collection(self, root: Path) -> None:
        """Put the components under test into this run's own config, and nothing else.

        ROUTED means "the collection is discoverable the way it normally would be", so every
        component the collection declares is installed — not only the watched ones. A near-miss
        neighbour that is missing would make a routing result meaningless: the model cannot choose
        wrongly between two skills when only one of them is there.

        The source repository is never touched: each source tree is built into the run's own staging
        directory and copied from there.
        """
        collection = self.collection
        if collection is None:
            return
        target = root / "config" / "opencode"
        target.mkdir(parents=True, exist_ok=True)

        installed = 0
        for index, source in enumerate(collection.sources):
            for offset, component_root in enumerate(_component_roots(source)):
                staged = root / "built" / f"{index}-{offset}"
                built = build.build(
                    "opencode", collection=collection, source=component_root, out_dir=staged
                )
                installed += _merge_tree(staged, target)
                if built.warnings:
                    (root / "build-warnings.txt").write_text(
                        "\n".join(built.warnings) + "\n", encoding="utf-8"
                    )
        if not installed:
            raise RunnerError(
                f"collection {collection.name!r} produced no installable components, so ROUTED "
                "would be identical to OFF"
            )

    def config_for(self, unit: Unit) -> dict[str, Any]:
        """The inline config a unit runs under. Only the target provider, and no MCP at all."""
        provider_id, model_id = _split_model(unit.model)
        config: dict[str, Any] = {
            "$schema": "https://opencode.ai/config.json",
            "autoupdate": False,
            "share": "disabled",
            "mcp": {},
            "provider": {
                provider_id: {
                    "npm": "@ai-sdk/openai-compatible",
                    "name": provider_id,
                    "options": {"baseURL": self.endpoint.root},
                    "models": {model_id: {"name": model_id}},
                }
            },
            "permission": {
                "edit": "allow",
                "webfetch": "deny",
                "external_directory": "deny",
                "bash": {"*": "allow"},
            },
        }
        if self.guard_plugin is not None:
            config["plugin"] = [str(self.guard_plugin)]
        return config

    def env_for(self, unit: Unit, root: Path) -> dict[str, str]:
        """The environment one unit runs in: isolated XDG, inline config, discovery switched off."""
        env = dict(os.environ)
        env.update(
            {
                "XDG_CONFIG_HOME": str(root / "config"),
                "XDG_DATA_HOME": str(root / "data"),
                "XDG_STATE_HOME": str(root / "state"),
                "XDG_CACHE_HOME": str(root / "cache"),
                "OPENCODE_CONFIG_CONTENT": json.dumps(self.config_for(unit)),
                "OPENCODE_DISABLE_PROJECT_CONFIG": "true",
                "OPENCODE_DISABLE_CLAUDE_CODE": "1",
                "WIKISKILL_GUARD_DENY": json.dumps(list(BASE_DENY) + list(unit.task.guard_deny)),
                # The logger plugin is inert without a runtime config, and this run has none: eval
                # events come from `normalize`, so nothing writes the log twice.
                "WIKISKILL_ORIGIN": "eval",
            }
        )
        env.pop("OPENCODE_CONFIG", None)
        return env

    def debug(self, unit: Unit, *args: str) -> Any:
        """Run `opencode debug ...` inside a unit's own environment and parse its JSON.

        This is how a run proves its isolation rather than asserting it: the config and skill list
        recorded in the manifest are the ones the model was actually given.
        """
        root = self.layout.unit_dir(unit)
        try:
            done = subprocess.run(
                [self.executable, "debug", *args],
                capture_output=True,
                text=True,
                timeout=120,
                env=self.env_for(unit, root),
                check=False,
            )
            return json.loads(done.stdout) if done.stdout.strip() else {"error": done.stderr[-500:]}
        except (OSError, subprocess.SubprocessError, json.JSONDecodeError) as exc:
            return {"error": str(exc)}

    def isolation_proof(self, unit: Unit) -> dict[str, Any]:
        """The loaded configuration and skill list for one unit, for the run manifest.

        Taken whether or not that unit ever ran: a run whose models all failed preflight should
        still say what the model *would* have been given, because that is what makes the next
        attempt debuggable.
        """
        try:
            self.prepare(unit)
        except (RunnerError, OSError) as exc:
            return {"condition": unit.condition, "error": str(exc)}
        config = self.debug(unit, "config")
        skills = self.debug(unit, "skill")
        names: list[str] = []
        if isinstance(skills, list):
            names = [
                str(entry.get("name") if isinstance(entry, dict) else entry) for entry in skills
            ]
        elif isinstance(skills, dict) and isinstance(skills.get("skills"), list):
            names = [str(entry.get("name", entry)) for entry in skills["skills"]]
        return {
            "condition": unit.condition,
            "config": config,
            "skills": names,
            "mcp": (config.get("mcp") if isinstance(config, dict) else None) or {},
        }

    # ------------------------------------------------------------------ execution

    def execute(self, unit: Unit) -> Trajectory:
        if unit.condition == INJECTED:
            raise RunnerError(
                "the INJECTED condition is not implemented yet (add-explicit-eval task 3.2); run "
                "with --condition off,routed"
            )
        root = self.layout.unit_dir(unit)
        try:
            workdir = self.prepare(unit)
        except (RunnerError, OSError) as exc:
            return Trajectory(unit=unit, outcome="infra_error", error=str(exc), reason=str(exc))

        command = [
            self.executable,
            "run",
            "--format",
            "json",
            "--dir",
            str(workdir),
            "-m",
            unit.model,
            unit.task.prompt,
        ]
        started = time.time()
        try:
            done = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=unit.task.timeout_s,
                env=self.env_for(unit, root),
                check=False,
            )
            stdout, stderr, exit_code = done.stdout, done.stderr, done.returncode
        except subprocess.TimeoutExpired:
            reason = f"timed out after {unit.task.timeout_s}s"
            return Trajectory(
                unit=unit,
                outcome="infra_error",
                error=reason,
                reason=reason,
                duration_ms=int((time.time() - started) * 1000),
                workdir=workdir,
            )
        except OSError as exc:
            return Trajectory(unit=unit, outcome="infra_error", error=str(exc), reason=str(exc))

        duration_ms = int((time.time() - started) * 1000)
        (root / "run.ndjson").write_text(stdout, encoding="utf-8")
        if stderr:
            (root / "run.stderr").write_text(stderr, encoding="utf-8")

        stream = _parse_stream(stdout)
        session_id = _session_id(stream)
        if session_id is None:
            reason = (
                f"{self.executable} produced no session (exit {exit_code}). "
                + (stderr.strip().splitlines() or ["no stderr"])[-1]
            )
            return Trajectory(
                unit=unit,
                outcome="infra_error",
                error=reason,
                reason=reason,
                duration_ms=duration_ms,
                exit_code=exit_code,
                workdir=workdir,
            )

        sessions = self.export_sessions(session_id, root)
        (root / "sessions.json").write_text(json.dumps(sessions, indent=2), encoding="utf-8")

        trajectory = Trajectory(
            unit=unit,
            outcome="completed",
            sessions=sessions,
            session_id=session_id,
            duration_ms=duration_ms,
            exit_code=exit_code,
            workdir=workdir,
        )
        trajectory.activations = activations(sessions)
        trajectory.tokens = _token_totals(sessions)
        trajectory.final_text = _final_text(sessions)
        trajectory.outcome, trajectory.error = classify(stream, sessions)
        return trajectory

    def export_sessions(self, session_id: str, root: Path) -> list[dict[str, Any]]:
        """The root session and every child session a delegation spawned, breadth first."""
        env = dict(os.environ)
        env.update(
            {
                "XDG_CONFIG_HOME": str(root / "config"),
                "XDG_DATA_HOME": str(root / "data"),
                "XDG_STATE_HOME": str(root / "state"),
                "XDG_CACHE_HOME": str(root / "cache"),
                "OPENCODE_DISABLE_PROJECT_CONFIG": "true",
                "OPENCODE_DISABLE_CLAUDE_CODE": "1",
            }
        )
        seen: set[str] = set()
        pending = [session_id]
        exported: list[dict[str, Any]] = []
        while pending:
            current = pending.pop(0)
            if current in seen:
                continue
            seen.add(current)
            try:
                done = subprocess.run(
                    [self.executable, "export", current],
                    capture_output=True,
                    text=True,
                    timeout=120,
                    env=env,
                    check=False,
                )
                session = json.loads(done.stdout) if done.stdout.strip() else None
            except (OSError, subprocess.SubprocessError, json.JSONDecodeError):
                session = None
            if not isinstance(session, dict):
                continue
            exported.append(session)
            pending.extend(child for child in _child_session_ids(session) if child not in seen)
        return exported

    # ------------------------------------------------------------------ normalisation

    def normalize(self, trajectory: Trajectory) -> list[dict[str, Any]]:
        """Raw events for one trajectory, in the order things happened.

        Every event carries `origin: eval` and the unit's provenance, so an evaluation reads back
        from the raw log per task, condition and repeat without a side file.
        """
        unit = trajectory.unit
        provider, model = _split_model(unit.model)
        root_session = trajectory.session_id or ""
        collection = self.collection.name if self.collection else unit.suite
        events: list[dict[str, Any]] = []

        for session in trajectory.sessions:
            info = session.get("info") or {}
            session_id = str(info.get("id") or root_session)
            parent_id = info.get("parentID") or None
            component: dict[str, Any] | None = None

            def make(
                event_type: str,
                payload: dict[str, Any],
                ts: str,
                *,
                session_id: str = session_id,
                parent_id: str | None = parent_id,
                component: dict[str, Any] | None = None,
                info: dict[str, Any] = info,
            ) -> dict[str, Any]:
                return {
                    "schema_version": RAW_SCHEMA_VERSION,
                    "event_id": rawlog.new_event_id(),
                    "ts": ts,
                    "origin": "eval",
                    "eval": unit.provenance(),
                    "harness": self.harness,
                    "harness_version": str(info.get("version") or self.version()),
                    "provider": provider,
                    "model": model,
                    "collection": collection,
                    "session_id": session_id,
                    "root_session_id": root_session or session_id,
                    "parent_session_id": parent_id,
                    "component": component,
                    "type": event_type,
                    "payload": payload,
                }

            created = _ts((info.get("time") or {}).get("created"))
            events.append(
                make(
                    "session_start",
                    {
                        "cwd": info.get("directory"),
                        "title": info.get("title"),
                        "agent": info.get("agent"),
                    },
                    created,
                )
            )

            for message in session.get("messages") or []:
                message_info = message.get("info") or {}
                role = message_info.get("role")
                message_ts = _ts((message_info.get("time") or {}).get("created"))
                for part in message.get("parts") or []:
                    for event, activated in self._part_events(
                        part, role, message_ts, make, component
                    ):
                        if activated is not None:
                            component = activated
                        events.append(event)
                error = message_info.get("error")
                if isinstance(error, dict):
                    message_text = _string_field(error.get("data") or {}, "message") or str(
                        error.get("name") or "error"
                    )
                    events.append(
                        make(
                            "error",
                            {"message": message_text, "where": "session", "fatal": True},
                            message_ts,
                            component=component,
                        )
                    )

            ended = _ts((info.get("time") or {}).get("updated"))
            events.append(
                make(
                    "session_end",
                    {"reason": "export", "duration_ms": trajectory.duration_ms or None},
                    ended,
                    component=component,
                )
            )
        return events

    def _part_events(self, part, role, message_ts, make, component):
        """Events for one part, each with the component it should be attributed to."""
        kind = part.get("type")
        produced: list[tuple[dict[str, Any], dict[str, Any] | None]] = []

        if kind == "text" and role == "assistant":
            text = part.get("text") or ""
            limited, truncated = _bound(text, self.output_limit_bytes)
            produced.append(
                (
                    make(
                        "assistant_turn",
                        {
                            "text": limited,
                            "text_length": len(text),
                            "finish_reason": "truncated_by_logger" if truncated else None,
                        },
                        _ts((part.get("time") or {}).get("end"))
                        if part.get("time")
                        else message_ts,
                        component=component,
                    ),
                    None,
                )
            )
        elif kind == "step-finish":
            tokens = part.get("tokens") or {}
            cache = tokens.get("cache") or {}
            produced.append(
                (
                    make(
                        "step_usage",
                        {
                            "tokens": {
                                "input": tokens.get("input"),
                                "output": tokens.get("output"),
                                "reasoning": tokens.get("reasoning"),
                                "cache_read": cache.get("read"),
                                "cache_write": cache.get("write"),
                            },
                            "cost": part.get("cost"),
                        },
                        message_ts,
                        component=component,
                    ),
                    None,
                )
            )
        elif kind == "tool":
            produced.extend(self._tool_events(part, message_ts, make, component))
        return produced

    def _tool_events(self, part, message_ts, make, component):
        """An activation, a delegation and the call itself, in the order they happened."""
        state = part.get("state") or {}
        status = state.get("status")
        if status not in ("completed", "error"):
            return []
        tool = str(part.get("tool") or "").lower()
        args = state.get("input") or {}
        metadata = state.get("metadata") or {}
        times = state.get("time") or {}
        ts = _ts(times.get("end") or times.get("start")) if times else message_ts
        produced: list[tuple[dict[str, Any], dict[str, Any] | None]] = []
        activated = None

        hint = self._activation(tool, args, metadata)
        if hint:
            activated = {"kind": hint[0], "name": hint[1], "source_hash": hint[2]}
            produced.append(
                (
                    make(
                        "component_activated",
                        {
                            "trigger": hint[3],
                            "source_path": hint[4],
                            "input_summary": (
                                _string_field(args, "description", "prompt", "query") or None
                            ),
                        },
                        ts,
                        component=activated,
                    ),
                    activated,
                )
            )
            component = activated

        if tool in _TASK_TOOLS:
            produced.append(
                (
                    make(
                        "delegation",
                        {
                            "subagent_type": _string_field(
                                args, "subagent_type", "subagentType", "agent", "name"
                            )
                            or "unknown",
                            "child_session_id": _string_field(
                                metadata, "sessionID", "sessionId", "session_id"
                            ),
                            "description": _string_field(args, "description", "prompt"),
                        },
                        ts,
                        component=component,
                    ),
                    None,
                )
            )

        output_value = state.get("output")
        raw_output = output_value if isinstance(output_value, str) else ""
        limited, truncated = _bound(raw_output, self.output_limit_bytes)
        start, end = times.get("start"), times.get("end")
        duration = int(end - start) if isinstance(start, int) and isinstance(end, int) else None
        produced.append(
            (
                make(
                    "tool_call",
                    {
                        "tool": str(part.get("tool") or "unknown"),
                        "call_id": part.get("callID"),
                        "ok": status == "completed",
                        "input": args or None,
                        "output": limited,
                        "output_length": len(raw_output),
                        "output_truncated": truncated,
                        "output_hash": None,
                        "error": state.get("error") if status == "error" else None,
                        "duration_ms": duration,
                    },
                    ts,
                    component=component,
                ),
                activated,
            )
        )
        return produced

    def _activation(self, tool, args, metadata):
        """``(kind, name, source_hash, trigger, source_path)`` when a call activated a component."""
        if tool in _SKILL_TOOLS:
            name = _string_field(args, "name", "skill", "skill_name")
            if name and self._watched("skill", name):
                directory = _string_field(metadata, "dir", "directory", "path")
                source = f"{directory}/SKILL.md" if directory else None
                return (
                    "skill",
                    name,
                    rawlog.file_hash(source) if source else None,
                    "skill_tool",
                    source,
                )
        elif tool in _TASK_TOOLS:
            name = _string_field(args, "subagent_type", "subagentType", "agent", "name")
            if name and self._watched("agent", name):
                source = _string_field(metadata, "path", "agentPath", "file")
                return (
                    "agent",
                    name,
                    rawlog.file_hash(source) if source else None,
                    "task_tool",
                    source,
                )
        return None

    def _watched(self, kind: str, name: str) -> bool:
        """During an evaluation every component of the collection counts, watch list or not.

        A suite names the route it expects; refusing to record an activation because the manifest's
        watch list is narrower would make the run unscorable.
        """
        if self.collection is None:
            return False
        if self.collection.matches(kind, name):
            return True
        bare = name.rsplit("/", maxsplit=1)[-1]
        return any(
            component.kind == kind and component.name.split("/")[-1] == bare
            for component in self.collection.discover()
        )


# --------------------------------------------------------------------------- stream reading


def _parse_stream(stdout: str) -> list[dict[str, Any]]:
    """`run --format json` is NDJSON: one event object per line, and nothing else."""
    events = []
    for raw_line in stdout.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        try:
            parsed = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            events.append(parsed)
    return events


def _session_id(stream: list[dict[str, Any]]) -> str | None:
    for event in stream:
        for key in ("sessionID", "sessionId", "session_id"):
            value = event.get(key)
            if isinstance(value, str) and value:
                return value
        info = event.get("info")
        if isinstance(info, dict) and isinstance(info.get("sessionID"), str):
            return info["sessionID"]
    return None


def _child_session_ids(session: dict[str, Any]) -> list[str]:
    """Child sessions a `task` delegation spawned, taken from the tool part's metadata."""
    found = []
    parent = str((session.get("info") or {}).get("id") or "")
    for message in session.get("messages") or []:
        for part in message.get("parts") or []:
            if part.get("type") != "tool":
                continue
            metadata = (part.get("state") or {}).get("metadata") or {}
            child = _string_field(metadata, "sessionID", "sessionId", "session_id")
            if child and child != parent:
                found.append(child)
    return found


def _iter_parts(sessions: list[dict[str, Any]]):
    for session in sessions:
        for message in session.get("messages") or []:
            yield message, (message.get("parts") or [])


def activations(sessions: list[dict[str, Any]]) -> list[dict[str, str]]:
    """Every component the model loaded or delegated to, in the order it did so.

    Taken from the calls themselves rather than from the collection's watch list: a route the suite
    expects may name a component the manifest does not watch, and a routing miss is only visible if
    the component that was chosen instead is recorded too.
    """
    found: list[dict[str, str]] = []
    for _, parts in _iter_parts(sessions):
        for part in parts:
            if part.get("type") != "tool":
                continue
            state = part.get("state") or {}
            if state.get("status") not in ("completed", "error"):
                continue
            tool = str(part.get("tool") or "").lower()
            args = state.get("input") or {}
            if tool in _SKILL_TOOLS:
                name = _string_field(args, "name", "skill", "skill_name")
                if name:
                    found.append({"kind": "skill", "name": name})
            elif tool in _TASK_TOOLS:
                name = _string_field(args, "subagent_type", "subagentType", "agent", "name")
                if name:
                    found.append({"kind": "agent", "name": name})
    return found


def _token_totals(sessions: list[dict[str, Any]]) -> dict[str, int]:
    totals = {"input": 0, "output": 0, "reasoning": 0}
    for _, parts in _iter_parts(sessions):
        for part in parts:
            if part.get("type") != "step-finish":
                continue
            tokens = part.get("tokens") or {}
            for key in totals:
                value = tokens.get(key)
                if isinstance(value, int):
                    totals[key] += value
    return totals


def _final_text(sessions: list[dict[str, Any]]) -> str:
    text = ""
    for session in sessions[:1]:
        for message in session.get("messages") or []:
            if (message.get("info") or {}).get("role") != "assistant":
                continue
            for part in message.get("parts") or []:
                if part.get("type") == "text" and isinstance(part.get("text"), str):
                    text = part["text"]
    return text


def classify(
    stream: list[dict[str, Any]], sessions: list[dict[str, Any]]
) -> tuple[str, str | None]:
    """How a unit ended, and the harness's own words for it.

    Behaviour and infrastructure are told apart here, before anything is scored: a model that cannot
    be given tools is an `api_error`, not a skill that failed.
    """
    error_text = None
    for event in stream:
        if event.get("type") != "error":
            continue
        data = (event.get("error") or {}).get("data") or {}
        error_text = _string_field(data, "message") or str((event.get("error") or {}).get("name"))

    tool_parts = [
        part for _, parts in _iter_parts(sessions) for part in parts if part.get("type") == "tool"
    ]
    for part in tool_parts:
        state = part.get("state") or {}
        message = str(state.get("error") or "").lower()
        if any(marker in message for marker in _BLOCKED_MARKERS):
            return "permission_blocked", state.get("error")

    if error_text:
        return "api_error", error_text

    if not tool_parts:
        final = _final_text(sessions)
        if any(marker in final for marker in _TOOL_SHAPED):
            return "tool_call_as_text", "the assistant described a tool call instead of making one"
    return "completed", None


# --------------------------------------------------------------------------- helpers


def _split_model(model: str) -> tuple[str, str]:
    provider, _, rest = model.partition("/")
    return (provider, rest) if rest else ("unknown", model)


def _model_id(model: str) -> str:
    return _split_model(model)[1]


def _component_roots(source) -> list[Path]:
    """The directories that hold `skills/`, `agents/` and `commands/` for one source.

    An OpenCode-layout source is one such directory. A Claude-plugin source is one per plugin, which
    is why a collection of plugins cannot simply be built in one pass.
    """
    if source.layout != "claude-plugin":
        return [source.path]
    if not source.path.is_dir():
        return []
    return [
        child
        for child in sorted(source.path.iterdir())
        if child.is_dir() and any((child / d).is_dir() for d in ("skills", "agents", "commands"))
    ]


def _merge_tree(staged: Path, target: Path) -> int:
    """Copy a built tree into the run's config, skipping build bookkeeping. Returns files copied."""
    copied = 0
    for path in sorted(staged.rglob("*")):
        if not path.is_file() or path.name == build.BUILD_MARKER:
            continue
        destination = target / path.relative_to(staged)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, destination)
        copied += 1
    return copied


def _git_init(workdir: Path) -> None:
    """A workdir is a git repo so the harness can snapshot it, and so verifiers can diff it."""
    # A run without git still works; only the harness's own snapshotting is lost.
    with contextlib.suppress(OSError, subprocess.SubprocessError):
        subprocess.run(
            ["git", "init", "--quiet", str(workdir)],
            capture_output=True,
            timeout=60,
            check=False,
        )


def _default_guard_plugin() -> Path | None:
    """The guard plugin, whether running from a checkout or an installed wheel."""
    found = paths.packaged_data("opencode-guard") / "wikiskill-guard.ts"
    return found if found.is_file() else None


__all__ = ["BASE_DENY", "OFF", "ROUTED", "OpenCodeBackend", "classify"]
