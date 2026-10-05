"""The Claude Code logger: `wikiskill hook <event>` maps one hook payload to raw events.

Claude Code runs each hook as its own process, with the event as JSON on stdin. So what the OpenCode
logger keeps in memory — whether the session is logging yet, the pre-activation buffer, the
follow-up window — lives here in a small per-session state file, read and rewritten under a lock
because tool hooks can fire in parallel.

Shapes are those of Claude Code 2.1.289, captured in `tests/fixtures/claude-code/`:
- every payload carries `session_id`, `transcript_path` and `cwd`
- a subagent's tool calls carry the parent's `session_id` plus its own `agent_id` and `agent_type`,
  so a subagent is a child session named by its `agent_id`
- names are plugin-qualified (`govern:preregister`); the collection's are `govern/preregister`
- a slash command reaches hooks only as a `UserPromptSubmit` whose prompt starts with `/`
- a background agent's completion arrives as a `UserPromptSubmit` the user never typed
- the model, its version and token usage are only in the transcript

The contract with the session is absolute: exit 0, write nothing to stdout, make no model or network
call. Every failure goes to the logger error log and the session carries on.
"""

from __future__ import annotations

import contextlib
import fcntl
import fnmatch
import json
import os
import re
import subprocess
import sys
import time
from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from . import corrections, paths, rawlog
from .redact import bound, env_secrets, merge, redact, redact_value

HARNESS = "claude-code"

#: State files untouched for this long are deleted when a new session starts.
STATE_TTL = timedelta(days=7)

#: How much of a transcript's end is read to find the model and the harness version.
TRANSCRIPT_TAIL_BYTES = 256 * 1024

#: Message ids remembered per transcript, so a usage line split across content blocks counts once.
SEEN_MESSAGES = 500

SKILL_TOOLS = {"Skill"}
AGENT_TOOLS = {"Agent", "Task"}
READ_TOOLS = {"Read"}

#: A prompt Claude Code submits itself when a background agent finishes.
_TASK_NOTIFICATION = re.compile(r"^\s*<task-notification>")

Event = dict[str, Any]
Factory = Callable[[dict[str, Any]], Event | None]


# --------------------------------------------------------------------------- watch list


def qualified(name: str) -> str:
    """Claude Code's `plugin:name` as the collection writes it, `plugin/name`."""
    return name.replace(":", "/", 1)


def watched_name(config: dict[str, Any], kind: str, name: str) -> str | None:
    """The name `config` watches this component under, or None.

    A plugin-qualified name must match as qualified. Only when the collection names its components
    bare — an OpenCode-layout source, built into one plugin — does the plugin prefix fall away; a
    `govern/*` pattern never claims `other:preregister`. An unqualified name falls back to each
    pattern's last segment, as the OpenCode logger's `watches` does.
    """
    patterns = (config.get("watch") or {}).get(kind) or []
    full = qualified(name)
    if any(fnmatch.fnmatchcase(full, pattern) for pattern in patterns):
        return full
    bare = full.rsplit("/", 1)[-1]
    if "/" in full:
        flat = [pattern for pattern in patterns if "/" not in pattern]
        return bare if any(fnmatch.fnmatchcase(bare, pattern) for pattern in flat) else None
    if any(fnmatch.fnmatchcase(bare, pattern.rsplit("/", 1)[-1]) for pattern in patterns):
        return bare
    return None


def watched_path(config: dict[str, Any], kind: str, name: str) -> str | None:
    for component in config.get("watched") or []:
        if component.get("kind") == kind and component.get("name") == name:
            return component.get("path")
    return None


def component_at(config: dict[str, Any], candidate: str) -> dict[str, Any] | None:
    """The watched component whose main file is `candidate`, for a `Read` of it."""
    if not candidate:
        return None
    for component in config.get("watched") or []:
        path = component.get("path")
        if path and (candidate == path or _same_file(candidate, path)):
            return component
    return None


def _same_file(a: str, b: str) -> bool:
    try:
        return os.path.realpath(a) == os.path.realpath(b)
    except OSError:
        return False


def load_configs() -> list[dict[str, Any]]:
    """The collections `wikiskill collection check --sync` published: OpenCode's file too."""
    from .collection import runtime_config_path  # noqa: PLC0415 - keep the hook's import light

    try:
        published = json.loads(runtime_config_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    collections = published.get("collections") if isinstance(published, dict) else None
    return [c for c in collections or [] if isinstance(c, dict) and c.get("collection")]


# --------------------------------------------------------------------------- state


def state_path(session_id: str) -> Path:
    safe = re.sub(r"[^A-Za-z0-9._-]", "_", session_id)
    return paths.state_home() / "claude-code" / "sessions" / f"{safe}.json"


def new_state(session_id: str) -> dict[str, Any]:
    return {
        "session_id": session_id,
        "logging": [],
        "buffer": {},
        "component": None,
        "agents": {},
        "window": None,
        "idle": False,
        "harness_version": "unknown",
        "model": "unknown",
        "cwd": None,
        "offsets": {},
        "seen": [],
    }


@contextlib.contextmanager
def locked_state(session_id: str) -> Iterator[dict[str, Any]]:
    """The session's state, saved on a clean exit. A file that will not parse is an error."""
    path = state_path(session_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path.with_suffix(".lock"), "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        state = (
            json.loads(path.read_text(encoding="utf-8")) if path.exists() else new_state(session_id)
        )
        if not isinstance(state, dict):
            raise ValueError(f"{path} does not hold a JSON object")
        yield state
        staging = path.with_name(f"{path.name}.{os.getpid()}.tmp")
        staging.write_text(json.dumps(state), encoding="utf-8")
        os.replace(staging, path)


def prune_states(now: float) -> None:
    directory = paths.state_home() / "claude-code" / "sessions"
    if not directory.is_dir():
        return
    cutoff = now - STATE_TTL.total_seconds()
    for path in directory.iterdir():
        with contextlib.suppress(OSError):
            if path.stat().st_mtime < cutoff:
                path.unlink()


# --------------------------------------------------------------------------- transcript


def _transcript_lines(path: str | None, start: int = 0) -> tuple[list[dict[str, Any]], int]:
    """Complete JSON lines from byte `start`, and the offset after the last complete one."""
    if not path:
        return [], start
    try:
        with open(path, "rb") as handle:
            handle.seek(start)
            data = handle.read()
    except OSError:
        return [], start
    end = data.rfind(b"\n") + 1
    lines = []
    for raw in data[:end].splitlines():
        with contextlib.suppress(ValueError):
            entry = json.loads(raw)
            if isinstance(entry, dict):
                lines.append(entry)
    return lines, start + end


def refresh_identity(state: dict[str, Any], transcript: str | None) -> None:
    """Model and harness version from the end of the transcript, the only place they appear."""
    if not transcript:
        return
    try:
        size = os.path.getsize(transcript)
    except OSError:
        return
    start = max(0, size - TRANSCRIPT_TAIL_BYTES)
    lines, _ = _transcript_lines(transcript, start)
    for entry in reversed(lines):
        if entry.get("version") and state["harness_version"] == "unknown":
            state["harness_version"] = str(entry["version"])
        message = entry.get("message")
        if entry.get("type") == "assistant" and isinstance(message, dict) and message.get("model"):
            state["model"] = str(message["model"])
            if entry.get("version"):
                state["harness_version"] = str(entry["version"])
            return


def new_usage(
    state: dict[str, Any], transcript: str | None, *, identity: bool = True
) -> list[dict[str, Any]]:
    """Token usage for assistant messages the transcript gained since the last call.

    One message is written as one line per content block, each repeating the message's usage, so
    usage is counted once per message id.
    """
    if not transcript:
        return []
    offsets = state.setdefault("offsets", {})
    lines, offset = _transcript_lines(transcript, int(offsets.get(transcript, 0)))
    offsets[transcript] = offset
    seen = state.setdefault("seen", [])
    usages = []
    for entry in lines:
        message = entry.get("message")
        if entry.get("type") != "assistant" or not isinstance(message, dict):
            continue
        message_id = message.get("id")
        if not message_id or message_id in seen or not isinstance(message.get("usage"), dict):
            continue
        seen.append(message_id)
        usages.append(message["usage"])
        # A subagent's transcript names its own model, which is not the session's.
        if identity and message.get("model"):
            state["model"] = str(message["model"])
        if identity and entry.get("version"):
            state["harness_version"] = str(entry["version"])
    del seen[:-SEEN_MESSAGES]
    return usages


def provider(env: dict[str, str]) -> str:
    """`anthropic`, unless Claude Code is pointed at another endpoint, which is then named."""
    base = env.get("ANTHROPIC_BASE_URL", "").strip()
    if not base:
        return "anthropic"
    host = urlparse(base).netloc or base
    return "anthropic" if host.endswith("anthropic.com") else host


# --------------------------------------------------------------------------- events


class Logger:
    """One hook invocation: the configs, the session's state, and the clock."""

    def __init__(
        self,
        state: dict[str, Any],
        configs: list[dict[str, Any]],
        env: dict[str, str],
        now: float,
    ) -> None:
        self.state = state
        self.configs = configs
        self.env = env
        self.now = now
        self.secrets = env_secrets(env)
        #: Events one hook writes share a millisecond, and a ULID's random tail would sort them
        #: arbitrarily; each takes the next millisecond in its id, so they sort as written.
        self.sequence = 0

    # -- identity

    def event(
        self,
        config: dict[str, Any],
        type_: str,
        payload: dict[str, Any],
        *,
        agent_id: str | None = None,
        component: dict[str, Any] | str | None = "current",
        redactions: list[dict[str, Any]] | None = None,
        confidence: str | None = None,
    ) -> Event:
        state = self.state
        root = state["session_id"]
        if component == "current":
            component = state["agents"].get(agent_id) if agent_id else state.get("component")
        event: Event = {
            "schema_version": rawlog.RAW_SCHEMA_VERSION,
            "event_id": self.next_id(),
            "ts": datetime.fromtimestamp(self.now, UTC)
            .isoformat(timespec="milliseconds")
            .replace("+00:00", "Z"),
            "origin": "live",
            "harness": HARNESS,
            "harness_version": state.get("harness_version") or "unknown",
            "provider": provider(self.env),
            "model": state.get("model") or "unknown",
            "collection": config["collection"],
            "session_id": agent_id or root,
            "root_session_id": root,
            "parent_session_id": root if agent_id else None,
            "component": component,
            "type": type_,
            "payload": payload,
        }
        if redactions:
            event["redactions"] = redactions
        if confidence:
            event["confidence"] = confidence
        return event

    def next_id(self) -> str:
        self.sequence += 1
        return rawlog.new_event_id(int(self.now * 1000) + self.sequence)

    # -- writing

    def write(self, config: dict[str, Any], event: Event) -> None:
        path = rawlog.session_log_path(config["raw_dir"], event["ts"], event["root_session_id"])
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n")

    def emit(self, factory: Factory) -> None:
        """Write for every collection logging this session; hold for the rest until they start."""
        for config in self.configs:
            event = factory(config)
            if event is None:
                continue
            name = config["collection"]
            if name in self.state["logging"]:
                self.write(config, event)
                continue
            held = self.state["buffer"].setdefault(name, [])
            held.append(event)
            del held[: max(0, len(held) - int(config.get("buffer_size") or 200))]

    def activate(self, config: dict[str, Any]) -> None:
        name = config["collection"]
        if name in self.state["logging"]:
            return
        self.state["logging"].append(name)
        for event in self.state["buffer"].pop(name, []):
            self.write(config, event)

    def logging(self) -> bool:
        return bool(self.state["logging"])

    # -- activation and the follow-up window

    def start(
        self,
        kind: str,
        name: str,
        trigger: str,
        *,
        summary: str | None = None,
        agent_id: str | None = None,
        source_path: str | None = None,
    ) -> dict[str, Any] | None:
        """Begin logging for every collection watching this component; the component, if any."""
        watching = []
        component = None
        for config in self.configs:
            known = watched_name(config, kind, name)
            if known is None:
                continue
            path = source_path or watched_path(config, kind, known)
            component = {
                "kind": kind,
                "name": known,
                "source_hash": rawlog.file_hash(path) if path else None,
            }
            self.activate(config)
            self.write(
                config,
                self.event(
                    config,
                    "component_activated",
                    {"trigger": trigger, "source_path": path, "input_summary": summary},
                    agent_id=agent_id,
                    component=component,
                ),
            )
            watching.append((config, component))
        if not watching or component is None:
            return None

        limit = max(int(config.get("follow_up_turns") or 3) for config, _ in watching)
        repeat = self.open_window(component, limit)
        if repeat:
            for config, ref in watching:
                self.write(
                    config,
                    self.event(
                        config,
                        "repeat_activation",
                        {
                            "turns_since_previous": repeat[0],
                            "seconds_since_previous": repeat[1],
                            "trigger": trigger,
                        },
                        agent_id=agent_id,
                        component=ref,
                        confidence="high",
                    ),
                )
        if agent_id:
            self.state["agents"][agent_id] = component
        else:
            self.state["component"] = component
        self.publish()
        return component

    def open_window(self, component: dict[str, Any], limit: int) -> tuple[int, float] | None:
        """Replace the window; return the previous activation's distance if this repeats it.

        At least one user turn between them, as on OpenCode: a model loading a skill twice in one
        answer is not anyone re-running it.
        """
        previous = self.state.get("window")
        self.state["window"] = {
            "component": component,
            "turns": 0,
            "activated_at": self.now,
            "last_activity_at": self.now,
        }
        if (
            previous
            and previous["component"]["kind"] == component["kind"]
            and previous["component"]["name"] == component["name"]
            and 1 <= previous["turns"] <= limit
        ):
            return previous["turns"], max(0.0, self.now - previous["activated_at"])
        return None

    def note_activity(self) -> None:
        window = self.state.get("window")
        if window:
            window["last_activity_at"] = self.now

    def follow_up_limit(self) -> int:
        limits = [
            int(c.get("follow_up_turns") or 3)
            for c in self.configs
            if c["collection"] in self.state["logging"]
        ]
        return max(limits, default=0)

    def user_turn(self) -> tuple[dict[str, Any], int, float] | None:
        window = self.state.get("window")
        if not window:
            return None
        window["turns"] += 1
        if window["turns"] > self.follow_up_limit():
            self.state["window"] = None
            return None
        return (
            window["component"],
            window["turns"],
            max(0.0, self.now - window["last_activity_at"]),
        )

    def publish(self) -> None:
        """Tell `wikiskill note` which session is open in this directory."""
        cwd = self.state.get("cwd")
        if not cwd:
            return
        for config in self.configs:
            if config["collection"] in self.state["logging"]:
                corrections.publish_active(
                    Path(config["raw_dir"]),
                    cwd,
                    self.state["session_id"],
                    datetime.fromtimestamp(self.now, UTC),
                )

    # -- payload shaping

    def text(self, config: dict[str, Any], text: str) -> tuple[str, bool, list[dict[str, Any]]]:
        """Redacted and bounded as the collection asks."""
        clean, redactions = redact(text, self.secrets) if config.get("redact", True) else (text, [])
        limited = bound(clean, int(config.get("output_limit_bytes") or 16 * 1024))
        return limited.text, limited.truncated, redactions


# --------------------------------------------------------------------------- handlers


def _response_text(response: Any) -> str:
    """A tool's result as text: Claude Code's responses are structured, OpenCode's are strings."""
    if response is None:
        return ""
    if isinstance(response, str):
        return response
    if isinstance(response, dict):
        if isinstance(response.get("file"), dict) and "content" in response["file"]:
            return str(response["file"]["content"])
        if "stdout" in response or "stderr" in response:
            return "\n".join(str(response.get(k) or "") for k in ("stdout", "stderr")).strip()
    return json.dumps(response, ensure_ascii=False, sort_keys=True)


#: A session starting within this long of the last scan this session started does not start another.
SCAN_EVERY = 10 * 60


def start_scan() -> None:
    """`wikiskill corrections scan` in its own process group, so it outlives the hook's timeout and
    nothing it does reaches the session."""
    subprocess.Popen(
        [sys.executable, "-m", "wikiskill", "corrections", "scan", "--quiet"],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )


def on_session_start(log: Logger, payload: dict[str, Any]) -> None:
    prune_states(log.now)
    # Files edited since a component wrote them are found when work resumes, as on OpenCode.
    if log.now - float(log.state.get("scanned_at") or 0) >= SCAN_EVERY:
        log.state["scanned_at"] = log.now
        start_scan()
    log.emit(
        lambda config: log.event(
            config, "session_start", {"cwd": payload.get("cwd"), "title": None, "agent": None}
        )
    )


def on_user_prompt(log: Logger, payload: dict[str, Any]) -> None:
    prompt = str(payload.get("prompt") or "")
    if _TASK_NOTIFICATION.match(prompt):
        # Claude Code's own message that a background agent finished; nobody typed it.
        return
    if prompt.startswith("/"):
        # A slash command is the user invoking something, not reacting to it: it may activate a
        # watched command, but it is not a follow-up and does not count against the window.
        command, _, arguments = prompt[1:].partition(" ")
        log.start("command", command, "command", summary=arguments.strip()[:500] or None)
        return
    if not log.logging():
        return
    log.publish()
    turn = log.user_turn()
    if turn is None:
        return
    component, turns, seconds = turn

    def factory(config: dict[str, Any]) -> Event:
        text, truncated, redactions = log.text(config, prompt)
        return log.event(
            config,
            "user_turn",
            {
                "text": text,
                "text_length": len(prompt),
                "text_truncated": truncated,
                "turns_since_activation": turns,
                "seconds_since_component": seconds,
            },
            component=component,
            redactions=redactions,
            confidence="high" if turns <= 1 else "medium",
        )

    log.emit(factory)


def on_tool(log: Logger, payload: dict[str, Any], *, failed: bool) -> None:
    agent_id = payload.get("agent_id") or None
    tool = str(payload.get("tool_name") or "")
    raw_input = payload.get("tool_input")
    args: dict[str, Any] = raw_input if isinstance(raw_input, dict) else {}
    response = payload.get("tool_response")
    log.note_activity()

    if tool in SKILL_TOOLS and args.get("skill"):
        log.start("skill", str(args["skill"]), "skill_tool", agent_id=agent_id)
    elif tool in AGENT_TOOLS and args.get("subagent_type"):
        summary = str(args.get("description") or args.get("prompt") or "")[:500] or None
        agent = log.start(
            "agent", str(args["subagent_type"]), "task_tool", summary=summary, agent_id=agent_id
        )
        child = response.get("agentId") if isinstance(response, dict) else None
        if agent and child:
            # A background agent's own calls arrive after this one, and are the agent's work.
            log.state["agents"][child] = agent
        log.emit(
            lambda config: log.event(
                config,
                "delegation",
                {
                    "subagent_type": qualified(str(args["subagent_type"])),
                    "child_session_id": child,
                    "description": str(args.get("description") or "")[:500] or None,
                },
                agent_id=agent_id,
            )
        )
    elif tool in READ_TOOLS:
        candidate = str(args.get("file_path") or "")
        for config in log.configs:
            found = component_at(config, candidate)
            if found:
                log.start(
                    found["kind"],
                    found["name"],
                    "read",
                    agent_id=agent_id,
                    source_path=found["path"],
                )
                break

    output = _response_text(response)
    error = str(payload.get("error") or "tool call failed") if failed else None
    # Hashed now, once, while the file is as the call left it.
    produced = [] if failed else corrections.produced_files(tool, args, log.state.get("cwd"))

    def factory(config: dict[str, Any]) -> Event:
        text, truncated, redactions = log.text(config, output)
        found: list[dict[str, Any]] = list(redactions)
        clean_input: Any = args
        if config.get("redact", True):
            clean_input, more = redact_value(args, log.secrets)
            found.extend(more)
        return log.event(
            config,
            "tool_call",
            {
                "tool": tool,
                "call_id": payload.get("tool_use_id"),
                "ok": not failed,
                "input": clean_input,
                "output": text,
                "output_length": len(output),
                "output_truncated": truncated,
                "output_hash": None,
                "error": error,
                "duration_ms": payload.get("duration_ms"),
                **({"produced_files": produced} if produced else {}),
            },
            agent_id=agent_id,
            redactions=merge(found),
        )

    log.emit(factory)


def _usage_event(log: Logger, usage: dict[str, Any], agent_id: str | None) -> Factory:
    details = usage.get("output_tokens_details") or {}
    tokens = {
        "input": usage.get("input_tokens"),
        "output": usage.get("output_tokens"),
        "reasoning": details.get("thinking_tokens") if isinstance(details, dict) else None,
        "cache_read": usage.get("cache_read_input_tokens"),
        "cache_write": usage.get("cache_creation_input_tokens"),
    }
    return lambda config: log.event(
        config, "step_usage", {"tokens": tokens, "cost": None}, agent_id=agent_id
    )


def _finish(log: Logger, payload: dict[str, Any], agent_id: str | None, transcript: str | None):
    for usage in new_usage(log.state, transcript, identity=agent_id is None):
        log.emit(_usage_event(log, usage, agent_id))
    last = payload.get("last_assistant_message")
    if isinstance(last, str) and last:

        def factory(config: dict[str, Any]) -> Event:
            text, truncated, redactions = log.text(config, last)
            return log.event(
                config,
                "assistant_turn",
                {
                    "text": text,
                    "text_length": len(last),
                    "finish_reason": "truncated_by_logger" if truncated else None,
                },
                agent_id=agent_id,
                redactions=redactions,
            )

        log.emit(factory)


def on_subagent_stop(log: Logger, payload: dict[str, Any]) -> None:
    agent_id = payload.get("agent_id") or None
    _finish(log, payload, agent_id, payload.get("agent_transcript_path"))
    log.emit(
        lambda config: log.event(
            config,
            "session_end",
            {"reason": "subagent_stop", "duration_ms": None},
            agent_id=agent_id,
        )
    )


def on_stop(log: Logger, payload: dict[str, Any]) -> None:
    _finish(log, payload, None, payload.get("transcript_path"))
    # Stop ends a turn. One session_end per idle period, as the OpenCode logger records.
    if log.state.get("idle"):
        return
    log.state["idle"] = True
    log.emit(
        lambda config: log.event(config, "session_end", {"reason": "idle", "duration_ms": None})
    )


def on_session_end(log: Logger, payload: dict[str, Any]) -> None:
    reason = str(payload.get("reason") or "ended")
    log.emit(
        lambda config: log.event(config, "session_end", {"reason": reason, "duration_ms": None})
    )


HANDLERS: dict[str, Callable[[Logger, dict[str, Any]], None]] = {
    "SessionStart": on_session_start,
    "UserPromptSubmit": on_user_prompt,
    "PostToolUse": lambda log, payload: on_tool(log, payload, failed=False),
    "PostToolUseFailure": lambda log, payload: on_tool(log, payload, failed=True),
    "SubagentStop": on_subagent_stop,
    "Stop": on_stop,
    "SessionEnd": on_session_end,
}

#: Events after which the session is no longer idle.
_ACTIVE = {"UserPromptSubmit", "PostToolUse", "PostToolUseFailure"}


def handle(
    event: str,
    payload: dict[str, Any],
    *,
    env: dict[str, str] | None = None,
    configs: list[dict[str, Any]] | None = None,
    now: float | None = None,
) -> None:
    """Apply one hook payload. Raises on failure; `run` is what keeps that from the session."""
    env = dict(os.environ) if env is None else env
    if env.get("WIKISKILL_ORIGIN") == "eval":
        # An evaluation reads its own stream; logging it here as well would count it twice.
        return
    handler = HANDLERS.get(event)
    configs = load_configs() if configs is None else configs
    session_id = payload.get("session_id")
    if handler is None or not configs or not session_id:
        return
    with locked_state(str(session_id)) as state:
        state["cwd"] = payload.get("cwd") or state.get("cwd")
        if event in _ACTIVE:
            state["idle"] = False
        refresh_identity(state, payload.get("transcript_path"))
        handler(Logger(state, configs, env, time.time() if now is None else now), payload)


def error_log(configs: list[dict[str, Any]]) -> Path:
    for config in configs:
        if config.get("error_log"):
            return Path(config["error_log"])
    return paths.state_home() / "claude-code" / "errors.log"


def run(event: str, stdin: str) -> int:
    """`wikiskill hook <event>`: never raises, never prints, always 0."""
    configs: list[dict[str, Any]] = []
    try:
        configs = load_configs()
        payload = json.loads(stdin) if stdin.strip() else {}
        if isinstance(payload, dict):
            handle(event, payload, configs=configs)
    except Exception as exc:
        with contextlib.suppress(Exception):
            path = error_log(configs)
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as handle_:
                stamp = datetime.now(UTC).isoformat(timespec="seconds")
                handle_.write(f"{stamp} hook {event}: {type(exc).__name__}: {exc}\n")
    return 0


def main() -> int:
    event = sys.argv[1] if len(sys.argv) > 1 else ""
    return run(event, sys.stdin.read())
