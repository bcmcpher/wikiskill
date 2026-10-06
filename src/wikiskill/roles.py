"""The meta-roles' client: how the maintainer, the proposer and the judge are asked.

A role with its own `base_url` is asked over HTTP, one chat-completions request per turn. A role
without one is a model the harness serves itself, and is asked through `opencode run` in an
isolated root where the evaluation guard refuses every command.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from . import names, paths
from .collection import Collection
from .errors import WikiskillError
from .runner.preflight import Endpoint, request_json

#: Tool calls a harness-served role may make before the guard refuses the rest.
ROLE_MAX_STEPS = 3


class RoleError(WikiskillError):
    """A meta-role could not be asked, or gave no answer."""


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
        raise RoleError(f"collection {collection.name!r} configures no `[roles.{role_name}]`")
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
    guard = guard or paths.opencode_guard_plugin()
    if guard is None or not guard.is_file():
        raise RoleError(
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
                raise RoleError(
                    f"{model} did not answer within {timeout_s}s; {_stream_summary(partial)}"
                ) from exc
            except OSError as exc:
                raise RoleError(f"cannot run {executable}: {exc}") from exc
            text = _stream_text(done.stdout)
            if not text:
                tail = (done.stderr.strip().splitlines() or ["no output"])[-1]
                raise RoleError(f"{model} gave no answer through {executable}: {tail}")
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
        raise RoleError(
            f"collection {collection.name!r} configures no `[roles.{role_name}]` endpoint"
        )
    endpoint = Endpoint(
        role.base_url, api_key=os.environ.get(role.api_key_env) if role.api_key_env else None
    )

    def ask(messages: list[dict[str, str]]) -> str:
        try:
            status, body = chat(endpoint, role.model, messages, timeout=timeout_s)
        except OSError as exc:
            raise RoleError(f"the {role_name} endpoint is unreachable: {exc}") from exc
        if status != 200:
            raise RoleError(f"the {role_name} endpoint answered {status}: {str(body)[:200]}")
        for choice in (body or {}).get("choices") or []:
            content = (choice.get("message") or {}).get("content")
            if isinstance(content, str):
                return content
        raise RoleError(f"the {role_name}'s reply had no message content")

    return ask, role.model


def chat(
    endpoint: Endpoint, model: str, messages: list[dict[str, str]], *, timeout: int
) -> tuple[int, Any]:
    """One chat-completions request at temperature 0: ``(status, body)``, as `request_json` gives.

    An `OSError` goes through, because each caller words that failure its own way.
    """
    payload = {
        "model": names.bare(model),  # the last segment, as the endpoint serves it
        "messages": messages,
        "temperature": 0,
        "stream": False,
    }
    return request_json(
        f"{endpoint.root}/chat/completions",
        payload=payload,
        api_key=endpoint.api_key,
        timeout=timeout,
    )
