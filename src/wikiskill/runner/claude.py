"""The Claude Code evaluation backend: isolate, run `claude -p` headless, read its stream-json.

Isolation works differently from OpenCode's. Claude Code reads its whole configuration from one
directory, so each unit gets its own `CLAUDE_CONFIG_DIR` holding a `settings.json` that wikiskill
writes, and nothing else: no user plugins, skills, memory, hooks or credentials. That alone is not
an empty harness. Claude Code still offers skills and plugins of its own from a fresh directory
(`design`, `doctor`, three `cc-plugin-*@builtin` plugins in 2.1.289), so the settings switch those
off, and every unit checks what its session was actually offered: a skill outside the collection
makes the unit an `infra_error`, never a routing result.

What the model did is read from the `--output-format stream-json` stream alone. A subagent's
messages carry the `parent_tool_use_id` of the `Agent` call that started it, so there is no second
export step. A subagent the model runs in the background finishes after the first `result`; its
completion starts another turn with a second `result`, which holds the real answer. `claude -p`
exits only after that, so the unit is over at the last `result`.

Open models are reached through any Anthropic-compatible endpoint: Ollama serves the Messages API
itself. Claude Code invents a price for a model it does not know, so no cost cap applies to them;
the unit's `timeout_s` and the guard's step budget bound a run instead.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

from .. import RAW_SCHEMA_VERSION, build, guard, names, paths, rawlog, redact
from ..collection import Collection
from ..hooks import qualified
from . import common
from .base import INJECTED, OFF, ROUTED, Backend, PreflightResult, RunnerError, Trajectory, Unit
from .opencode import BASE_DENY
from .preflight import MIN_CONTEXT_TOKENS, Endpoint, messages_check

#: Plugins Claude Code loads from a fresh config directory. Switched off by name; anything newer is
#: caught by the per-unit isolation check instead of slipping through.
BUILTIN_PLUGINS = (
    "cc-plugin-agents-md@builtin",
    "cc-plugin-telemetry@builtin",
    "cc-plugin-plugin-authoring@builtin",
)

#: Skills Claude Code offers that `disableBundledSkills` leaves on.
BUILTIN_SKILLS = ("design", "doctor")

#: Tools a unit may use without asking. Everything else is refused, because `-p` cannot ask.
ALLOWED_TOOLS = (
    "Bash",
    "Read",
    "Edit",
    "Write",
    "MultiEdit",
    "NotebookEdit",
    "Glob",
    "Grep",
    "LS",
    "TodoWrite",
    "Skill",
    "Agent",
    "Task",
)

#: Never: an evaluation does not reach the network on the model's behalf.
DENIED_TOOLS = ("WebFetch", "WebSearch")

#: Environment a unit must not inherit from the session that started it, Claude Code included.
_INHERITED_PREFIXES = ("CLAUDE_CODE_", "ANTHROPIC_")
_INHERITED_NAMES = ("CLAUDECODE", "CLAUDE_CONFIG_DIR")

_SKILL_TOOLS = {"skill"}
_AGENT_TOOLS = {"agent", "task"}

#: Error text that means the harness refused an activation, rather than the model misnaming it.
_REFUSAL_MARKERS = (
    guard.BLOCKED_PREFIX,
    "disabled via skilloverrides",
    "permission",
    "denied",
    "not allowed",
)

#: Shapes a model emits when it describes a tool call instead of making one.
_TOOL_SHAPED = ('"tool_call"', '"function_call"', "<tool_call>", '"tool_name"', '"arguments":')

#: The prefix Claude Code puts before a loaded skill's text, naming the directory it came from.
_SKILL_BASE = "Base directory for this skill:"


class ClaudeCodeBackend(Backend):
    """Runs a unit in a fresh, isolated headless Claude Code session."""

    harness = "claude-code"

    def __init__(
        self,
        *,
        collection: Collection | None,
        endpoint: Endpoint | None,
        layout,
        suite_root: Path,
        executable: str = "claude",
        min_context: int = MIN_CONTEXT_TOKENS,
        probe_timeout: int | None = None,
        output_limit_bytes: int = 16 * 1024,
        foreground_agents: bool = False,
    ) -> None:
        self.collection = collection
        self.endpoint = endpoint
        self.layout = layout
        self.suite_root = suite_root
        self.executable = executable
        self.min_context = min_context
        self.probe_timeout = probe_timeout
        self.output_limit_bytes = output_limit_bytes
        #: Subagents run in the background when the model asks for it, as they would for a user.
        #: Forcing them into the foreground is a different harness behaviour, so it is recorded.
        self.foreground_agents = foreground_agents
        self._version: str | None = None
        #: condition → its isolation proof, completed with what the first unit was offered.
        self._proofs: dict[str, dict[str, Any]] = {}

    def run_options(self) -> dict[str, Any]:
        return {"foreground_agents": self.foreground_agents}

    # ------------------------------------------------------------------ identity

    def version(self) -> str:
        if self._version is None:
            try:
                done = subprocess.run(
                    [self.executable, "--version"],
                    stdin=subprocess.DEVNULL,
                    capture_output=True,
                    text=True,
                    timeout=30,
                    check=False,
                )
            except (OSError, subprocess.SubprocessError) as exc:
                raise RunnerError(
                    f"cannot run {self.executable!r}: {exc}. Install Claude Code, or pass "
                    "--claude with a path to it."
                ) from exc
            # The first word of output like `2.1.289 (Claude Code)`.
            self._version = (done.stdout.split() or ["unknown"])[0]
        return self._version

    def preflight(self, model: str) -> PreflightResult:
        """An open model must make a real Messages API tool call; a hosted one needs a key.

        Without an endpoint the model is Anthropic's, and the unit's empty config directory holds
        no login, so `ANTHROPIC_API_KEY` is the only credential that reaches it.
        """
        if self.endpoint is not None:
            return messages_check(
                self.endpoint,
                common.model_id(model),
                min_context=self.min_context,
                **({"probe_timeout": self.probe_timeout} if self.probe_timeout else {}),
            )
        details = {"via": "anthropic", "model": model}
        if not os.environ.get("ANTHROPIC_API_KEY"):
            return PreflightResult(
                model=model,
                ok=False,
                problems=(
                    (
                        f"{model} is served by Anthropic, and an evaluation's config directory "
                        "holds no login. Set ANTHROPIC_API_KEY, or pass --base-url for an open "
                        "model."
                    ),
                ),
                details=details,
            )
        return PreflightResult(model=model, ok=True, details=details)

    # ------------------------------------------------------------------ isolation

    def prepare(self, unit: Unit) -> Path:
        """Build the unit's config directory, plugin and working directory; return the latter."""
        root = self.layout.unit_dir(unit)
        config_dir = root / "claude"
        if config_dir.exists():
            shutil.rmtree(config_dir)
        config_dir.mkdir(parents=True)

        workdir = self.prepare_workdir(unit, root)

        if unit.condition in (ROUTED, INJECTED) and self.collection is not None:
            self._build_plugin(root)
        (config_dir / "settings.json").write_text(
            json.dumps(self.settings_for(unit), indent=2) + "\n", encoding="utf-8"
        )
        return workdir

    def _build_plugin(self, root: Path) -> None:
        """The whole collection as one plugin, loaded with `--plugin-dir`, pins stripped."""
        collection = self.collection
        if collection is None:
            return
        plugin = root / "plugin"
        try:
            built = build.build_collection("claude-code", collection, plugin, strip_models=True)
        except build.BuildError as exc:
            raise RunnerError(f"collection {collection.name!r} cannot be installed: {exc}") from exc
        if built.warnings:
            (root / "build-warnings.txt").write_text(
                "\n".join(built.warnings) + "\n", encoding="utf-8"
            )
        if not any((plugin / kind).is_dir() for kind in ("skills", "agents", "commands")):
            raise RunnerError(
                f"collection {collection.name!r} produced no installable components, so ROUTED "
                "would be identical to OFF"
            )

    def settings_for(self, unit: Unit) -> dict[str, Any]:
        """The only settings a unit's Claude Code reads: `--setting-sources user` in its own dir."""
        deny: list[str] = list(DENIED_TOOLS)
        injected = _injected_skill(unit)
        if injected and self.collection is not None:
            # The skill's text is in the system prompt, so the model must not also load it: that
            # would be ROUTED with a head start. `skillOverrides` does not reach a plugin's skill
            # in 2.1.289, so it stays listed; a permission rule refuses the call instead.
            deny.append(f"Skill({self.collection.name}:{injected})")
        cli = paths.cli_command()
        return {
            "enabledPlugins": {name: False for name in BUILTIN_PLUGINS},
            "disableBundledSkills": True,
            "skillOverrides": {name: "off" for name in BUILTIN_SKILLS},
            "permissions": {"allow": list(ALLOWED_TOOLS), "deny": deny},
            "hooks": {
                "PreToolUse": [
                    {
                        "matcher": "*",
                        "hooks": [{"type": "command", "command": f"{cli} guard", "timeout": 10}],
                    }
                ]
            },
        }

    def env_for(self, unit: Unit, root: Path) -> dict[str, str]:
        """The unit's environment: its config dir, its endpoint, its guard, nothing inherited."""
        env = {
            key: value
            for key, value in os.environ.items()
            if not key.startswith(_INHERITED_PREFIXES) and key not in _INHERITED_NAMES
        }
        # The suite's own variables first, so nothing it sets can undo the isolation below.
        env.update(unit.task.resolved_env())
        env.update(
            {
                "CLAUDE_CONFIG_DIR": str(root / "claude"),
                "CLAUDE_CODE_DISABLE_CLAUDE_API_SKILL": "1",
                "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",
                "DISABLE_AUTOUPDATER": "1",
                "WIKISKILL_GUARD_DENY": json.dumps(list(BASE_DENY) + list(unit.task.guard_deny)),
                "WIKISKILL_MAX_STEPS": str(unit.task.max_steps) if unit.task.max_steps else "",
                "WIKISKILL_GUARD_STATE": str(root / "guard-steps"),
                "WIKISKILL_ORIGIN": "eval",
            }
        )
        if self.foreground_agents:
            env["CLAUDE_CODE_DISABLE_BACKGROUND_TASKS"] = "1"
        model_id = common.model_id(unit.model)
        if self.endpoint is not None:
            env["ANTHROPIC_BASE_URL"] = self.endpoint.native_root
            env["ANTHROPIC_AUTH_TOKEN"] = self.endpoint.api_key or "wikiskill"
            # Every model Claude Code would pick by itself — subagents, background helpers — is the
            # one under test, or a row would mix two models, and the endpoint serves only this one.
            for tier in ("HAIKU", "SONNET", "OPUS"):
                env[f"ANTHROPIC_DEFAULT_{tier}_MODEL"] = model_id
            env["CLAUDE_CODE_SUBAGENT_MODEL"] = model_id
        elif os.environ.get("ANTHROPIC_API_KEY"):
            env["ANTHROPIC_API_KEY"] = os.environ["ANTHROPIC_API_KEY"]
        return env

    def command_for(self, unit: Unit, root: Path) -> list[str]:
        command = [
            self.executable,
            "-p",
            "--output-format",
            "stream-json",
            "--verbose",
            "--model",
            common.model_id(unit.model),
            "--setting-sources",
            "user",
            "--strict-mcp-config",
            "--permission-mode",
            "dontAsk",
        ]
        plugin = root / "plugin"
        if unit.condition in (ROUTED, INJECTED) and plugin.is_dir():
            # `--add-dir` too, so a loaded skill can read the files beside it.
            command += ["--plugin-dir", str(plugin), "--add-dir", str(plugin)]
        injected = _injected_skill(unit)
        if injected:
            text = plugin / "skills" / injected / "SKILL.md"
            if not text.is_file():
                raise RunnerError(
                    f"INJECTED needs the text of {unit.task.expect.primary!r}, and the collection "
                    f"built no skill at {text}"
                )
            command += ["--append-system-prompt", text.read_text(encoding="utf-8")]
        agent = _injected_agent(unit)
        if agent and self.collection is not None:
            command += ["--agent", f"{self.collection.name}:{agent}"]
        # `--add-dir` and `--plugin-dir` take any number of values, so without `--` the prompt
        # would be read as one more directory.
        command += ["--", unit.task.prompt]
        return command

    def isolation_proof(self, unit: Unit) -> dict[str, Any]:
        """The settings and flags a condition runs under. What the session was offered is added
        when the first unit of the condition runs, since only a running session reports it."""
        try:
            self.prepare(unit)
            root = self.layout.unit_dir(unit)
            command = self.command_for(unit, root)
        except (RunnerError, OSError) as exc:
            return {"condition": unit.condition, "error": str(exc)}
        proof = {
            "condition": unit.condition,
            "settings": self.settings_for(unit),
            # The prompt and an injected skill's text are the task's, not the isolation's.
            "flags": [part for part in command[1:-2] if "\n" not in part],
            "env": sorted(
                key
                for key in self.env_for(unit, root)
                if key.startswith(("CLAUDE_", "ANTHROPIC_", "WIKISKILL_"))
            ),
            "offered": None,
        }
        self._proofs[unit.condition] = proof
        return proof

    # ------------------------------------------------------------------ execution

    def execute(self, unit: Unit) -> Trajectory:
        root = self.layout.unit_dir(unit)
        try:
            workdir = self.prepare(unit)
            command = self.command_for(unit, root)
        except (RunnerError, OSError) as exc:
            return Trajectory(unit=unit, outcome="infra_error", error=str(exc), reason=str(exc))

        started = time.time()
        stream_path = root / "stream.jsonl"
        try:
            with stream_path.open("w", encoding="utf-8") as handle:
                done = subprocess.run(
                    command,
                    cwd=workdir,
                    stdin=subprocess.DEVNULL,
                    stdout=handle,
                    stderr=subprocess.PIPE,
                    text=True,
                    timeout=unit.task.timeout_s,
                    env=self.env_for(unit, root),
                    check=False,
                )
            stderr, exit_code = done.stderr, done.returncode
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
        if stderr:
            (root / "run.stderr").write_text(stderr, encoding="utf-8")
        stream = parse_stream(stream_path.read_text(encoding="utf-8"))
        session_id = session_of(stream)
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

        offered = offered_in(stream)
        proof = self._proofs.get(unit.condition)
        if proof is not None and proof.get("offered") is None:
            proof["offered"] = offered
        trajectory = Trajectory(
            unit=unit,
            outcome="completed",
            sessions=[{"stream": stream}],
            session_id=session_id,
            duration_ms=duration_ms,
            exit_code=exit_code,
            workdir=workdir,
            activations=activations(stream),
            tokens=token_totals(stream),
            final_text=final_text(stream),
            transcript=transcript(stream),
        )
        trajectory.outcome, trajectory.error = classify(stream)
        problem = isolation_leak(unit, offered, self.collection) or injection_failed(
            unit, trajectory.activations
        )
        if problem:
            trajectory.outcome, trajectory.error, trajectory.reason = (
                "infra_error",
                problem,
                problem,
            )
        return trajectory

    # ------------------------------------------------------------------ normalisation

    def normalize(self, trajectory: Trajectory) -> list[dict[str, Any]]:
        """Raw events for one trajectory, in stream order, root and subagent sessions alike."""
        return _Normaliser(self, trajectory).events()

    def in_collection(self, kind: str, name: str) -> bool:
        """During an evaluation every component of the collection counts, watched or not."""
        if self.collection is None:
            return False
        bare = names.bare(name)
        return any(
            component.kind == kind and names.bare(component.name) == bare
            for component in self.collection.discover()
        )


class _Normaliser:
    """One trajectory's stream turned into raw events, keeping the state that takes: which session
    each message belongs to, which component it is attributed to, and calls awaiting results."""

    def __init__(self, backend: ClaudeCodeBackend, trajectory: Trajectory) -> None:
        self.backend = backend
        self.trajectory = trajectory
        self.unit = trajectory.unit
        self.provider, self.model = common.split_model(self.unit.model)
        stream = (trajectory.sessions[0] if trajectory.sessions else {}).get("stream") or []
        self.stream: list[dict[str, Any]] = stream
        self.root = trajectory.session_id or session_of(stream) or ""
        self.collection = backend.collection.name if backend.collection else self.unit.suite
        self.children = child_sessions(stream)
        self.sources = skill_sources(stream)
        self.version = _init_version(stream) or backend.version()
        self.out: list[dict[str, Any]] = []
        self.component: dict[str, dict[str, Any] | None] = {}
        self.started: list[str] = []
        self.pending: dict[str, tuple[dict[str, Any], str]] = {}
        self.ts = rawlog.now_ts()

    def make(self, event_type: str, payload: dict[str, Any], session: str) -> dict[str, Any]:
        return {
            "schema_version": RAW_SCHEMA_VERSION,
            "event_id": rawlog.new_event_id(),
            "ts": self.ts,
            "origin": "eval",
            "eval": self.unit.provenance(),
            "harness": self.backend.harness,
            "harness_version": self.version,
            "provider": self.provider,
            "model": self.model,
            "collection": self.collection,
            "session_id": session,
            "root_session_id": self.root,
            "parent_session_id": None if session == self.root else self.root,
            "component": self.component.get(session),
            "type": event_type,
            "payload": payload,
        }

    def emit(self, event_type: str, payload: dict[str, Any], session: str) -> None:
        self.out.append(self.make(event_type, payload, session))

    def begin(self, session: str, payload: dict[str, Any]) -> None:
        if session not in self.started:
            self.started.append(session)
            self.emit("session_start", payload, session)

    def events(self) -> list[dict[str, Any]]:
        for event in self.stream:
            self.ts = common.string_field(event, "timestamp") or self.ts
            kind = event.get("type")
            if kind == "system" and event.get("subtype") == "init":
                self.begin(self.root, {"cwd": event.get("cwd"), "title": None, "agent": None})
            elif kind == "result":
                self.turn_usage(event)
            elif kind in ("assistant", "user"):
                # A tool-use id, or null on the root session's own messages.
                parent: str | None = event.get("parent_tool_use_id")
                session = self.children.get(parent, parent) if parent else self.root
                self.begin(
                    session,
                    {
                        "cwd": None,
                        "title": event.get("task_description"),
                        "agent": event.get("subagent_type"),
                    },
                )
                content = _message(event).get("content")
                blocks = (
                    [b for b in content if isinstance(b, dict)] if isinstance(content, list) else []
                )
                if kind == "assistant":
                    self.assistant(blocks, session)
                else:
                    self.answers(blocks, session)
        for session in self.started:
            root = session == self.root
            self.emit(
                "session_end",
                {
                    "reason": "result" if root else "subagent_stop",
                    "duration_ms": (self.trajectory.duration_ms or None) if root else None,
                },
                session,
            )
        return self.out

    def assistant(self, blocks: list[dict[str, Any]], session: str) -> None:
        for block in blocks:
            if block.get("type") == "text" and block.get("text"):
                text = str(block["text"])
                bounded = redact.bound(text, self.backend.output_limit_bytes)
                self.emit(
                    "assistant_turn",
                    {
                        "text": bounded.text,
                        "text_length": len(text),
                        "finish_reason": "truncated_by_logger" if bounded.truncated else None,
                    },
                    session,
                )
            elif block.get("type") == "tool_use" and block.get("id"):
                self.pending[str(block["id"])] = (block, self.ts)

    def turn_usage(self, result: dict[str, Any]) -> None:
        """One `step_usage` per turn. A message's own usage stops at its first block, so its output
        is always 0; a `result` has the turn's real totals."""
        usage = result.get("usage")
        if not isinstance(usage, dict):
            return
        tokens = {
            "input": usage.get("input_tokens"),
            "output": usage.get("output_tokens"),
            "reasoning": None,
            "cache_read": usage.get("cache_read_input_tokens"),
            "cache_write": usage.get("cache_creation_input_tokens"),
        }
        # Claude Code invents a price for a model it does not know, so none is recorded.
        self.emit("step_usage", {"tokens": tokens, "cost": None}, self.root)

    def answers(self, blocks: list[dict[str, Any]], session: str) -> None:
        for block in blocks:
            if block.get("type") != "tool_result":
                continue
            found = self.pending.pop(str(block.get("tool_use_id")), None)
            if found is not None:
                self.tool(found[0], found[1], block, session)

    def tool(self, use: dict[str, Any], called: str, result: dict[str, Any], session: str):
        """An activation, a delegation and the call itself, for one answered tool call."""
        name = str(use.get("name") or "unknown")
        args = _call_input(use)
        failed = bool(result.get("is_error"))
        output = _result_text(result.get("content"))
        answered, self.ts = self.ts, called

        target = _activation_name(name.lower(), args)
        if target and not failed and self.backend.in_collection(*target):
            source = self.sources.get(str(use.get("id"))) if target[0] == "skill" else None
            self.component[session] = {
                "kind": target[0],
                "name": target[1],
                "source_hash": rawlog.file_hash(source) if source else None,
            }
            self.emit(
                "component_activated",
                {
                    "trigger": "skill_tool" if target[0] == "skill" else "task_tool",
                    "source_path": source,
                    "input_summary": (
                        common.string_field(args, "description", "prompt", "args") or None
                    ),
                },
                session,
            )
        if name.lower() in _AGENT_TOOLS and not failed:
            self.emit(
                "delegation",
                {
                    "subagent_type": qualified(
                        common.string_field(args, "subagent_type") or "unknown"
                    ),
                    "child_session_id": self.children.get(str(use.get("id"))),
                    "description": common.string_field(args, "description", "prompt"),
                },
                session,
            )

        self.ts = answered
        bounded = redact.bound(output, self.backend.output_limit_bytes)
        self.emit(
            "tool_call",
            {
                "tool": name,
                "call_id": use.get("id"),
                "ok": not failed,
                "input": args or None,
                "output": bounded.text,
                "output_length": len(output),
                "output_truncated": bounded.truncated,
                "output_hash": None,
                "error": output if failed else None,
                "duration_ms": None,
            },
            session,
        )


# --------------------------------------------------------------------------- stream reading


def _message(event: dict[str, Any]) -> dict[str, Any]:
    """An event's model message. `system/permission_denied` carries a string `message` instead."""
    message = event.get("message")
    return message if isinstance(message, dict) else {}


def parse_stream(text: str) -> list[dict[str, Any]]:
    """stream-json is NDJSON. Claude Code's progress ticks are dropped here: thousands per run."""
    events = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        try:
            parsed = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict) and parsed.get("subtype") != "thinking_tokens":
            events.append(parsed)
    return events


def session_of(stream: list[dict[str, Any]]) -> str | None:
    for event in stream:
        value = event.get("session_id")
        if isinstance(value, str) and value:
            return value
    return None


def _init_version(stream: list[dict[str, Any]]) -> str | None:
    for event in stream:
        if event.get("type") == "system" and event.get("subtype") == "init":
            version = event.get("claude_code_version")
            return str(version) if version else None
    return None


def offered_in(stream: list[dict[str, Any]]) -> dict[str, Any]:
    """What the first `init` says the session was given: skills, agents, plugins and tools."""
    for event in stream:
        if event.get("type") == "system" and event.get("subtype") == "init":
            return {
                "skills": list(event.get("skills") or []),
                "agents": list(event.get("agents") or []),
                "plugins": [
                    str(plugin.get("name") if isinstance(plugin, dict) else plugin)
                    for plugin in event.get("plugins") or []
                ],
                "tools": list(event.get("tools") or []),
                "mcp_servers": list(event.get("mcp_servers") or []),
            }
    return {}


def isolation_leak(
    unit: Unit, offered: dict[str, Any], collection: Collection | None
) -> str | None:
    """Why a session was not isolated, or None. Only the collection's own may be offered."""
    if not offered:
        return None
    own = collection.name if collection is not None and unit.condition != OFF else None
    skills = [
        name
        for name in offered.get("skills") or []
        if not (own and str(name).startswith(f"{own}:"))
    ]
    plugins = [name for name in offered.get("plugins") or [] if name != own]
    mcp = offered.get("mcp_servers") or []
    if not (skills or plugins or mcp):
        return None
    parts = []
    if skills:
        parts.append(f"skills {', '.join(map(str, skills))}")
    if plugins:
        parts.append(f"plugins {', '.join(map(str, plugins))}")
    if mcp:
        parts.append(f"{len(mcp)} MCP server(s)")
    return (
        f"Claude Code offered {'; '.join(parts)} outside the collection under {unit.condition}, so "
        "this unit would not measure the collection alone. Switch them off in "
        "`runner/claude.py` (BUILTIN_SKILLS, BUILTIN_PLUGINS)."
    )


def injection_failed(unit: Unit, found: list[dict[str, Any]]) -> str | None:
    """Why an INJECTED unit measured something else, or None.

    The skill's text is in the prompt and loading it is refused. A load that went through means the
    refusal did not hold, and the unit was ROUTED with a head start.
    """
    injected = _injected_skill(unit)
    if not injected:
        return None
    loaded = [
        entry
        for entry in found
        if entry["kind"] == "skill"
        and names.bare(entry["name"]) == injected
        and not entry.get("blocked")
    ]
    if loaded:
        return (
            f"INJECTED put {injected!r} in the system prompt and denied loading it, but the model "
            "loaded it anyway, so this unit is not INJECTED"
        )
    return None


def child_sessions(stream: list[dict[str, Any]]) -> dict[str, str]:
    """`Agent` call id → the subagent's id, which hooks also name its child session by."""
    found: dict[str, str] = {}
    for event in stream:
        if event.get("type") == "system" and event.get("subtype") == "task_started":
            call, task = event.get("tool_use_id"), event.get("task_id")
            if isinstance(call, str) and isinstance(task, str):
                found.setdefault(call, task)
        if event.get("type") != "user":
            continue
        result = event.get("tool_use_result")
        agent = result.get("agentId") if isinstance(result, dict) else None
        if not isinstance(agent, str):
            continue
        for block in _message(event).get("content") or []:
            if isinstance(block, dict) and block.get("type") == "tool_result":
                found.setdefault(str(block.get("tool_use_id")), agent)
    return found


def _calls(stream: list[dict[str, Any]]):
    """Every tool call with its result, in the order the results arrived."""
    uses: dict[str, dict[str, Any]] = {}
    for event in stream:
        content = _message(event).get("content")
        if not isinstance(content, list):
            continue
        for block in content:
            if not isinstance(block, dict):
                continue
            if event.get("type") == "assistant" and block.get("type") == "tool_use":
                uses[str(block.get("id"))] = block
            elif event.get("type") == "user" and block.get("type") == "tool_result":
                use = uses.pop(str(block.get("tool_use_id")), None)
                if use is not None:
                    yield use, block


def _call_input(use: dict[str, Any]) -> dict[str, Any]:
    """A tool call's arguments, or none when its `input` is not an object."""
    args = use.get("input")
    return args if isinstance(args, dict) else {}


def _activation_name(tool: str, args: dict[str, Any]) -> tuple[str, str] | None:
    """``(kind, plugin/name)`` for a Skill or Agent call. Claude Code writes `plugin:name`."""
    if tool in _SKILL_TOOLS:
        name = common.string_field(args, "skill", "name", "command")
        return ("skill", qualified(name.lstrip("/"))) if name else None
    if tool in _AGENT_TOOLS:
        name = common.string_field(args, "subagent_type")
        return ("agent", qualified(name)) if name else None
    return None


def activations(stream: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Every component the model loaded or delegated to, in order.

    A call the harness refused is kept with `blocked: true`, as for OpenCode. A call that failed
    for another reason — an agent name that does not exist, a missing argument — activated nothing
    and is dropped: `Agent type 'counter' not found` is not a route to `counter`.
    """
    found: list[dict[str, Any]] = []
    for use, result in _calls(stream):
        target = _activation_name(str(use.get("name") or "").lower(), _call_input(use))
        if target is None:
            continue
        entry: dict[str, Any] = {"kind": target[0], "name": target[1]}
        if result.get("is_error"):
            if not _refused(_result_text(result.get("content"))):
                continue
            entry["blocked"] = True
        found.append(entry)
    return found


def _refused(text: str) -> bool:
    lowered = text.lower()
    return any(marker in lowered for marker in _REFUSAL_MARKERS)


def _result_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(
            str(part.get("text"))
            for part in content
            if isinstance(part, dict) and part.get("type") == "text" and part.get("text")
        )
    return ""


def skill_sources(stream: list[dict[str, Any]]) -> dict[str, str]:
    """`Skill` call id → the SKILL.md it loaded.

    The call's own result says only `Launching skill: <name>`. The next message in the same session
    carries the skill's text, headed with the directory it came from.
    """
    found: dict[str, str] = {}
    waiting: dict[Any, str] = {}
    skill_calls = {
        str(use.get("id")) for use, _ in _calls(stream) if str(use.get("name")).lower() == "skill"
    }
    for event in stream:
        if event.get("type") != "user":
            continue
        thread = event.get("parent_tool_use_id")
        for block in _message(event).get("content") or []:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "tool_result" and str(block.get("tool_use_id")) in skill_calls:
                waiting[thread] = str(block.get("tool_use_id"))
            elif block.get("type") == "text" and thread in waiting:
                text = str(block.get("text") or "")
                if text.startswith(_SKILL_BASE):
                    directory = text[len(_SKILL_BASE) :].splitlines()[0].strip()
                    found[waiting.pop(thread)] = f"{directory}/SKILL.md"
    return found


def results(stream: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [event for event in stream if event.get("type") == "result"]


def final_text(stream: list[dict[str, Any]]) -> str:
    """The last `result`'s text: a background subagent's completion produces a later one."""
    found = results(stream)
    return str(found[-1].get("result") or "") if found else ""


def transcript(stream: list[dict[str, Any]]) -> str:
    """Every assistant text block, subagents' included."""
    chunks = []
    for event in stream:
        if event.get("type") != "assistant":
            continue
        for block in _message(event).get("content") or []:
            if isinstance(block, dict) and block.get("type") == "text" and block.get("text"):
                chunks.append(str(block["text"]))
    return "\n".join(chunks)


def token_totals(stream: list[dict[str, Any]]) -> dict[str, int]:
    """The session's tokens, subagents included, from the last `result`'s `modelUsage`.

    The stream's own messages are no use for this: each reports its usage as of its first block,
    so `output_tokens` is always 0 there. `modelUsage` is cumulative over the whole session.
    """
    totals = {"input": 0, "output": 0, "reasoning": 0}
    found = results(stream)
    usage = found[-1].get("modelUsage") if found else None
    if isinstance(usage, dict) and usage:
        for entry in usage.values():
            if not isinstance(entry, dict):
                continue
            for key, field in (
                ("input", "inputTokens"),
                ("output", "outputTokens"),
                ("reasoning", "thinkingTokens"),
            ):
                value = entry.get(field)
                if isinstance(value, int):
                    totals[key] += value
        return totals
    for result in found:
        turn = result.get("usage") or {}
        for key, field in (("input", "input_tokens"), ("output", "output_tokens")):
            value = turn.get(field)
            if isinstance(value, int):
                totals[key] += value
    return totals


def classify(stream: list[dict[str, Any]]) -> tuple[str, str | None]:
    """How a unit ended, and the harness's own words for it."""
    calls = list(_calls(stream))
    for _, result in calls:
        text = _result_text(result.get("content"))
        if guard.BLOCKED_PREFIX in text:
            return ("step_exhausted" if guard.STEP_MARKER in text else "permission_blocked"), text

    found = results(stream)
    if not found:
        return "infra_error", "the session ended without a result"
    ended = _ended_badly(found[-1])
    if ended:
        return ended
    if not calls and any(marker in final_text(stream) for marker in _TOOL_SHAPED):
        return "tool_call_as_text", "the assistant described a tool call instead of making one"
    return "completed", None


def _ended_badly(result: dict[str, Any]) -> tuple[str, str] | None:
    """The outcome a failed `result` stands for, or None when it succeeded."""
    subtype = str(result.get("subtype") or "")
    if subtype == "error_max_turns":
        return "step_exhausted", f"Claude Code stopped after {result.get('num_turns')} turns"
    if result.get("is_error") or subtype.startswith("error"):
        status = result.get("api_error_status")
        message = str(result.get("result") or subtype or "error")
        return "api_error", f"{message} (HTTP {status})" if status else message
    return None


# --------------------------------------------------------------------------- helpers


def _injected_skill(unit: Unit) -> str:
    expect = unit.task.expect
    if unit.condition != INJECTED or not expect.skill:
        return ""
    return names.bare(expect.skill)


def _injected_agent(unit: Unit) -> str:
    expect = unit.task.expect
    if unit.condition != INJECTED or expect.skill:
        return ""
    return names.bare(expect.agent)


__all__ = ["ClaudeCodeBackend", "activations", "classify", "parse_stream"]
