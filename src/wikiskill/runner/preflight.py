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

#: The tool-call probe is the first request that reaches the model, so Ollama loads the model
#: while answering it. A cold 8B model on a laptop can take a minute before it emits one token.
PROBE_TIMEOUT_S = 120

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
    extra_headers: dict[str, str] | None = None,
) -> tuple[int, Any]:
    """GET or POST JSON. Returns ``(status, body)``; body is the raw text when it is not JSON."""
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    headers = {"Accept": "application/json"}
    if data is not None:
        headers["Content-Type"] = "application/json"
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    headers.update(extra_headers or {})
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


def _probe_problems(model: str, status: int, completion: Any, details: dict[str, Any]) -> list[str]:
    """What an answered tool-call probe shows: a pass, a refusal, or prose instead of a call."""
    details["tool_probe_status"] = status
    if status != 200:
        message = ""
        if isinstance(completion, dict):
            message = str((completion.get("error") or {}).get("message") or "")
        if "support thinking" in message:
            return [
                (
                    f"{model} cannot think, and this run asks it to: {message}. Run it with "
                    "--thinking default or off."
                )
            ]
        return [
            f"{model} refused a tool-call probe with HTTP {status}"
            + (f": {message}" if message else "")
            + ". A model that cannot be given tools cannot drive a skill; choose a tool-calling "
            "model for this suite."
        ]
    if not _has_tool_call(completion):
        return [
            (
                f"{model} answered the tool-call probe with text instead of a structured tool "
                "call. Skills are driven by tool calls, so this model would score zero for reasons "
                "that have nothing to do with the skills under test."
            )
        ]
    return []


def _loaded_context(endpoint: Endpoint, model: str, *, timeout: int) -> int | None:
    """The context a loaded model is actually served with, from Ollama's `/api/ps`."""
    try:
        status, body = request_json(f"{endpoint.native_root}/api/ps", timeout=timeout)
    except (urllib.error.URLError, OSError, TimeoutError):
        return None
    if status != 200 or not isinstance(body, dict):
        return None
    for entry in body.get("models") or []:
        if not isinstance(entry, dict) or model not in (entry.get("name"), entry.get("model")):
            continue
        context = entry.get("context_length")
        if isinstance(context, int) and context > 0:
            return context
    return None


def ollama_context(endpoint: Endpoint, model: str, *, timeout: int) -> tuple[int | None, str]:
    """Ollama's effective context for a model, and where the number came from.

    A loaded model's entry in `/api/ps` is the answer itself, and the tool-call probe has just
    loaded it. Failing that, the server setting wins: a model trained for 128k tokens still only
    sees `OLLAMA_CONTEXT_LENGTH` tokens, defaulting to 4096, and the model's own maximum caps it.
    That fallback reads this process's environment, which is only right when the server shares it.
    """
    loaded = _loaded_context(endpoint, model, timeout=timeout)
    if loaded is not None:
        return loaded, "the running server"

    configured = os.environ.get("OLLAMA_CONTEXT_LENGTH")
    served = int(configured) if configured and configured.isdigit() else OLLAMA_DEFAULT_CONTEXT
    source = "OLLAMA_CONTEXT_LENGTH" if configured else "Ollama's 4096-token default"

    try:
        status, body = request_json(
            f"{endpoint.native_root}/api/show", payload={"model": model}, timeout=timeout
        )
    except (urllib.error.URLError, OSError, TimeoutError):
        # `/api/show` only ever lowers the number; without it the server setting still stands.
        return served, source
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
    probe_timeout: int = PROBE_TIMEOUT_S,
    reasoning_effort: str | None = None,
) -> PreflightResult:
    """Reachability, model listing, a tool-call probe, and context size, in that order.

    Each check that fails stops the ones that depend on it, so the report names the first real cause
    rather than four consequences of one dead endpoint. The tool-call probe gets `probe_timeout`
    rather than `timeout`, because it pays for loading the model. It asks for the same
    `reasoning_effort` the units will, so a model that cannot think fails here rather than in every
    unit.
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

    try:
        status, completion = request_json(
            f"{endpoint.root}/chat/completions",
            payload={
                "model": model,
                "messages": PROBE_MESSAGES,
                "tools": [PROBE_TOOL],
                "tool_choice": "auto",
                "temperature": 0,
                "stream": False,
                **({"reasoning_effort": reasoning_effort} if reasoning_effort else {}),
            },
            api_key=endpoint.api_key,
            timeout=probe_timeout,
        )
    except (urllib.error.URLError, OSError, TimeoutError) as exc:
        reason = getattr(exc, "reason", exc)
        details["tool_probe_status"] = None
        problems.append(
            f"{model} did not answer the tool-call probe within {probe_timeout}s ({reason}). "
            "The first request loads the model, so a large model on a slow machine may need "
            "--probe-timeout raised; otherwise check the server is still running."
        )
    else:
        problems.extend(_probe_problems(model, status, completion, details))

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


#: The same probe as `PROBE_TOOL`, in the Messages API's shape.
MESSAGES_PROBE_TOOL = {
    "name": PROBE_TOOL["function"]["name"],
    "description": PROBE_TOOL["function"]["description"],
    "input_schema": PROBE_TOOL["function"]["parameters"],
}


def messages_check(
    endpoint: Endpoint,
    model: str,
    *,
    min_context: int = MIN_CONTEXT_TOKENS,
    timeout: int = DEFAULT_TIMEOUT_S,
    probe_timeout: int = PROBE_TIMEOUT_S,
) -> PreflightResult:
    """Preflight for Claude Code on an Anthropic-compatible endpoint: a tool call, then context.

    Claude Code speaks the Messages API, so that is what is probed: a `tool_use` block in answer to
    a request with one tool. Ollama serves the Messages API itself at its native root, which is why
    the endpoint's `/v1` suffix, if given, is dropped. Its context is checked as for OpenCode.
    """
    details: dict[str, Any] = {"base_url": endpoint.native_root, "model": model, "api": "messages"}
    headers = {"anthropic-version": "2023-06-01"}
    if endpoint.api_key:
        headers["x-api-key"] = endpoint.api_key
    try:
        status, reply = request_json(
            f"{endpoint.native_root}/v1/messages",
            payload={
                "model": model,
                "max_tokens": 1024,
                "messages": PROBE_MESSAGES,
                "tools": [MESSAGES_PROBE_TOOL],
            },
            api_key=endpoint.api_key,
            timeout=probe_timeout,
            extra_headers=headers,
        )
    except (urllib.error.URLError, OSError, TimeoutError) as exc:
        reason = getattr(exc, "reason", exc)
        return PreflightResult(
            model=model,
            ok=False,
            problems=(
                (
                    f"{endpoint.native_root} did not answer a Messages API request for {model} "
                    f"within {probe_timeout}s ({reason}). Start the server, or raise "
                    "--probe-timeout for a large model on a slow machine."
                ),
            ),
            details=details,
        )

    details["tool_probe_status"] = status
    problems: list[str] = []
    if status == 404:
        message = (
            str((reply.get("error") or {}).get("message") or "") if isinstance(reply, dict) else ""
        )
        return PreflightResult(
            model=model,
            ok=False,
            problems=(
                (
                    f"{endpoint.native_root} does not serve {model!r} through the Messages API"
                    + (f" ({message})" if message else "")
                    + f". Pull it first (for Ollama, `ollama pull {model}`), or check that the "
                    "endpoint is Anthropic-compatible."
                ),
            ),
            details=details,
        )
    if status != 200:
        message = ""
        if isinstance(reply, dict):
            message = str((reply.get("error") or {}).get("message") or "")
        problems.append(
            f"{model} refused a Messages API tool-call probe with HTTP {status}"
            + (f": {message}" if message else "")
            + ". Claude Code can only drive a model that answers the Messages API with tool calls."
        )
    else:
        blocks = reply.get("content") if isinstance(reply, dict) else None
        kinds = [block.get("type") for block in blocks or [] if isinstance(block, dict)]
        details["probe_blocks"] = kinds
        if "tool_use" not in kinds:
            problems.append(
                f"{model} answered the Messages API tool-call probe without a tool_use block. "
                "Skills are driven by tool calls, so this model would score zero for reasons that "
                "have nothing to do with the skills under test."
            )

    if min_context > 0:
        if endpoint.is_ollama:
            context, source = ollama_context(endpoint, model, timeout=timeout)
        else:
            context, source = None, "unknown"
        details["context_tokens"] = context
        details["context_source"] = source
        if context is None:
            problems.append(
                f"could not establish the context window served for {model} at "
                f"{endpoint.native_root}. Re-run with --min-context 0 to accept it unchecked, once "
                f"you know it is at least {min_context} tokens."
            )
        elif context < min_context:
            problems.append(
                f"{model} is served with a {context}-token context ({source}), below the "
                f"{min_context} tokens Claude Code's system prompt and tool schemas need. Restart "
                f"the server with OLLAMA_CONTEXT_LENGTH={min_context} (or larger) and try again."
            )

    return PreflightResult(model=model, ok=not problems, problems=tuple(problems), details=details)
