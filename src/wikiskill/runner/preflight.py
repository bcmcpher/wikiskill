"""Check an endpoint before a suite runs on it.

Local open models fail in ways that look like bad skills if they are not caught first: the endpoint
is not running, the model was never pulled, it cannot emit a tool call at all, or it is served
with a context too small to hold OpenCode's system prompt and tool schemas. Each of those is an
infrastructure fact, so it is established once per model per run and reported as a skip with an
actionable message — never as a task failure.

Everything here speaks plain OpenAI-compatible HTTP over the standard library. Ollama is
special-cased only where it has to be: its effective context window is a server setting, not a model
property, so `/api/show` alone would report a model's trained context and miss the 4096-token
default that actually truncates the run.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

from .base import PreflightResult

#: OpenCode's system prompt plus tool schemas do not fit below this.
MIN_CONTEXT_TOKENS = 16384

#: What Ollama serves when `OLLAMA_CONTEXT_LENGTH` is unset.
OLLAMA_DEFAULT_CONTEXT = 4096

DEFAULT_TIMEOUT_S = 30

#: One trivial tool. A model that cannot produce a structured call for this cannot drive a skill.
PROBE_TOOL = {
    "type": "function",
    "function": {
        "name": "report_colour",
        "description": "Report the colour a user asked about.",
        "parameters": {
            "type": "object",
            "properties": {"colour": {"type": "string", "description": "The colour name."}},
            "required": ["colour"],
        },
    },
}

PROBE_MESSAGES = [
    {
        "role": "user",
        "content": "The sky is blue. Call the report_colour tool with the colour of the sky.",
    }
]


@dataclass(frozen=True)
class Endpoint:
    """One OpenAI-compatible endpoint, as the runner knows it."""

    base_url: str
    api_key: str | None = None

    @property
    def root(self) -> str:
        return self.base_url.rstrip("/")

    @property
    def is_ollama(self) -> bool:
        """Whether the native Ollama API sits beside this OpenAI-compatible one."""
        return "11434" in self.root or "ollama" in self.root.lower()

    @property
    def native_root(self) -> str:
        """Ollama's own API, one level above its OpenAI-compatible `/v1`."""
        return self.root[: -len("/v1")] if self.root.endswith("/v1") else self.root


def request_json(
    url: str,
    *,
    payload: dict[str, Any] | None = None,
    api_key: str | None = None,
    timeout: int = DEFAULT_TIMEOUT_S,
) -> tuple[int, Any]:
    """GET or POST JSON. Returns ``(status, body)``; body is the raw text when it is not JSON."""
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    headers = {"Accept": "application/json"}
    if data is not None:
        headers["Content-Type"] = "application/json"
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    request = urllib.request.Request(url, data=data, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read().decode("utf-8", "replace")
            status = response.status
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", "replace")
        status = exc.code
    try:
        return status, json.loads(body)
    except json.JSONDecodeError:
        return status, body


def _model_ids(listing: Any) -> list[str]:
    entries = listing.get("data", []) if isinstance(listing, dict) else []
    return [
        str(entry.get("id")) for entry in entries if isinstance(entry, dict) and entry.get("id")
    ]


def _has_tool_call(completion: Any) -> bool:
    """Whether a chat completion contains a real tool call, not a description of one."""
    if not isinstance(completion, dict):
        return False
    for choice in completion.get("choices", []):
        message = choice.get("message") or {}
        if message.get("tool_calls"):
            return True
        if message.get("function_call"):
            return True
    return False


def ollama_context(endpoint: Endpoint, model: str, *, timeout: int) -> tuple[int | None, str]:
    """Ollama's effective context for a model, and where the number came from.

    The server setting wins: a model trained for 128k tokens still only sees `OLLAMA_CONTEXT_LENGTH`
    tokens, defaulting to 4096. The model's own maximum caps it.
    """
    configured = os.environ.get("OLLAMA_CONTEXT_LENGTH")
    served = int(configured) if configured and configured.isdigit() else OLLAMA_DEFAULT_CONTEXT
    source = "OLLAMA_CONTEXT_LENGTH" if configured else "Ollama's 4096-token default"

    status, body = request_json(
        f"{endpoint.native_root}/api/show", payload={"model": model}, timeout=timeout
    )
    if status == 200 and isinstance(body, dict):
        info = body.get("model_info") or {}
        trained = [
            value
            for key, value in info.items()
            if key.endswith(".context_length") and isinstance(value, int)
        ]
        if trained and min(trained) < served:
            return min(trained), f"{model}'s own maximum"
    return served, source


def check(
    endpoint: Endpoint,
    model: str,
    *,
    min_context: int = MIN_CONTEXT_TOKENS,
    timeout: int = DEFAULT_TIMEOUT_S,
) -> PreflightResult:
    """Reachability, model listing, a tool-call probe, and context size, in that order.

    Each check that fails stops the ones that depend on it, so the report names the first real cause
    rather than four consequences of one dead endpoint.
    """
    problems: list[str] = []
    details: dict[str, Any] = {"base_url": endpoint.root, "model": model}

    try:
        status, listing = request_json(
            f"{endpoint.root}/models", api_key=endpoint.api_key, timeout=timeout
        )
    except (urllib.error.URLError, OSError, TimeoutError) as exc:
        reason = getattr(exc, "reason", exc)
        return PreflightResult(
            model=model,
            ok=False,
            problems=(
                (
                    f"endpoint {endpoint.root} is not reachable ({reason}). Start the server, or "
                    "point the collection's target at an endpoint that is running."
                ),
            ),
            details=details,
        )

    if status != 200:
        return PreflightResult(
            model=model,
            ok=False,
            problems=(
                (
                    f"endpoint {endpoint.root} answered HTTP {status} when asked to list models. "
                    "Check the base URL and the API key environment variable in the manifest."
                ),
            ),
            details=details,
        )

    available = _model_ids(listing)
    details["models_listed"] = len(available)
    if available and model not in available:
        family = model.split(":", maxsplit=1)[0]
        near = ", ".join(sorted(m for m in available if m.split(":")[0] == family)[:3])
        hint = f" Similar names offered: {near}." if near else ""
        return PreflightResult(
            model=model,
            ok=False,
            problems=(
                (
                    f"{endpoint.root} does not serve {model!r}. Pull it first (for Ollama, "
                    f"`ollama pull {model}`), or fix the manifest's alias table.{hint}"
                ),
            ),
            details=details,
        )

    status, completion = request_json(
        f"{endpoint.root}/chat/completions",
        payload={
            "model": model,
            "messages": PROBE_MESSAGES,
            "tools": [PROBE_TOOL],
            "tool_choice": "auto",
            "temperature": 0,
            "stream": False,
        },
        api_key=endpoint.api_key,
        timeout=timeout,
    )
    if status != 200:
        message = ""
        if isinstance(completion, dict):
            message = str((completion.get("error") or {}).get("message") or "")
        details["tool_probe_status"] = status
        problems.append(
            f"{model} refused a tool-call probe with HTTP {status}"
            + (f": {message}" if message else "")
            + ". A model that cannot be given tools cannot drive a skill; choose a tool-calling "
            "model for this suite."
        )
    elif not _has_tool_call(completion):
        details["tool_probe_status"] = status
        problems.append(
            f"{model} answered the tool-call probe with text instead of a structured tool call. "
            "Skills are driven by tool calls, so this model would score zero for reasons that have "
            "nothing to do with the skills under test."
        )
    else:
        details["tool_probe_status"] = status

    if min_context > 0:
        if endpoint.is_ollama:
            context, source = ollama_context(endpoint, model, timeout=timeout)
        else:
            context, source = None, "unknown"
        details["context_tokens"] = context
        details["context_source"] = source
        if context is None:
            problems.append(
                f"could not establish the context window served for {model} at {endpoint.root}. "
                "Re-run with --min-context 0 to accept it unchecked, once you know it is at least "
                f"{min_context} tokens."
            )
        elif context < min_context:
            problems.append(
                f"{model} is served with a {context}-token context ({source}), below the "
                f"{min_context} tokens OpenCode's system prompt and tool schemas need. Restart the "
                f"server with OLLAMA_CONTEXT_LENGTH={min_context} (or larger) and try again."
            )

    return PreflightResult(model=model, ok=not problems, problems=tuple(problems), details=details)
