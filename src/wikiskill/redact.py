"""Redaction and output bounds for events Python writes from a harness: a port of the OpenCode
logger's `wikiskill/redact.ts`.

The two must agree, because the same skill's events are compared across harnesses; a secret masked
in one log and kept in the other would make the Claude Code log the leakier of two copies. The
patterns below are the TypeScript ones verbatim, and `tests/test_redact.py` runs the plugin's own
cases. Pure: the environment snapshot is an argument, taken once per hook process.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

#: Environment values shorter than this are too common to redact without mangling output.
MIN_ENV_VALUE = 8

#: Environment variable names whose values are never secrets and would ruin readability.
ENV_ALLOW = frozenset(
    {
        "PATH",
        "HOME",
        "PWD",
        "OLDPWD",
        "SHELL",
        "TERM",
        "LANG",
        "LC_ALL",
        "USER",
        "LOGNAME",
        "HOSTNAME",
        "TMPDIR",
        "EDITOR",
        "XDG_CONFIG_HOME",
        "XDG_DATA_HOME",
        "XDG_STATE_HOME",
        "XDG_CACHE_HOME",
    }
)

#: JavaScript's `\b` without the `u` flag: a boundary between an ASCII word character and anything
#: else. Python's is Unicode-aware, so after `é` it saw no boundary and kept the key that follows.
ASCII_BOUNDARY = r"(?:(?<![A-Za-z0-9_])(?=[A-Za-z0-9_])|(?<=[A-Za-z0-9_])(?![A-Za-z0-9_]))"


def _js(source: str, flags: int = 0) -> re.Pattern[str]:
    """Compile a `redact.ts` pattern so that `\\b` means what it means there."""
    return re.compile(source.replace(r"\b", ASCII_BOUNDARY), flags)


#: ``(kind, pattern, group)``: the group holding the secret, 0 for the whole match.
PATTERNS: tuple[tuple[str, re.Pattern[str], int], ...] = (
    (
        "private_key",
        _js(r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----"),
        0,
    ),
    ("api_key", _js(r"\b(?:sk|rk|pk)-[A-Za-z0-9_-]{16,}\b"), 0),
    ("api_key", _js(r"\bsk-ant-[A-Za-z0-9_-]{16,}\b"), 0),
    ("api_key", _js(r"\bAKIA[0-9A-Z]{16}\b"), 0),
    ("api_key", _js(r"\bgh[pousr]_[A-Za-z0-9]{16,}\b"), 0),
    ("api_key", _js(r"\bxox[abprs]-[A-Za-z0-9-]{10,}\b"), 0),
    ("token", _js(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b"), 0),
    ("token", _js(r"\b[Bb]earer\s+([A-Za-z0-9._~+/=-]{20,})"), 1),
    (
        "password",
        _js(
            r"\b(?:password|passwd|secret|api[_-]?key|access[_-]?token|auth[_-]?token)"
            r"[\"']?\s*[:=]\s*[\"']?([^\s\"',;]{6,})",
            re.IGNORECASE,
        ),
        1,
    ),
    (
        "url_credentials",
        _js(r"\b([a-z][a-z0-9+.-]*)://[^\s/:@]+:([^\s/@]+)@", re.IGNORECASE),
        2,
    ),
)


def env_secrets(env: Mapping[str, str]) -> list[str]:
    """Values worth scrubbing from a snapshot of the environment, longest first."""
    values = []
    for name, value in env.items():
        if not value or len(value) < MIN_ENV_VALUE or name in ENV_ALLOW:
            continue
        # A value that is just a path is location, not a secret.
        if value.startswith("/") and not re.search(r"[:@]", value):
            continue
        values.append(value)
    # Longest first, so a value that contains another is replaced whole.
    return sorted(values, key=len, reverse=True)


def _entries(counts: Counter[str]) -> list[dict[str, Any]]:
    return [{"kind": kind, "count": counts[kind]} for kind in sorted(counts) if counts[kind]]


def redact(text: str, env_values: Iterable[str] = ()) -> tuple[str, list[dict[str, Any]]]:
    """The text with secrets replaced by ``[REDACTED:<kind>]``, and one entry per kind found."""
    if not text:
        return text, []
    counts: Counter[str] = Counter()
    out = text
    for value in env_values:
        seen = min(out.count(value), 101)
        if seen:
            out = out.replace(value, "[REDACTED:env_value]", seen)
            counts["env_value"] += seen

    for kind, pattern, group in PATTERNS:

        def replace(match: re.Match[str], kind: str = kind, group: int = group) -> str:
            secret = match.group(group)
            if not secret:
                return match.group(0)
            counts[kind] += 1
            marker = f"[REDACTED:{kind}]"
            return match.group(0).replace(secret, marker, 1) if group else marker

        out = pattern.sub(replace, out)
    return out, _entries(counts)


def redact_value(
    value: Any, env_values: Iterable[str] = (), depth: int = 0
) -> tuple[Any, list[dict[str, Any]]]:
    """Redact every string inside a tool's arguments, preserving the structure."""
    env_values = list(env_values)
    if depth > 8:
        return "[TRUNCATED:depth]", []
    if isinstance(value, str):
        return redact(value, env_values)
    if isinstance(value, list):
        items, found = [], []
        for item in value:
            clean, redactions = redact_value(item, env_values, depth + 1)
            items.append(clean)
            found.extend(redactions)
        return items, merge(found)
    if isinstance(value, dict):
        out, found = {}, []
        for key, item in value.items():
            clean, redactions = redact_value(item, env_values, depth + 1)
            found.extend({**r, "field": r.get("field", key)} for r in redactions)
            out[key] = clean
        return out, merge(found)
    return value, []


def merge(redactions: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """One entry per kind, counts summed, fields dropped — as the TypeScript `merge` does."""
    counts: Counter[str] = Counter()
    for entry in redactions:
        counts[entry["kind"]] += entry["count"]
    return _entries(counts)


#: Characters kept of a short free-text field: a delegation's description, an activation's input.
SUMMARY_CHARS = 500


def summary(
    text: str | None,
    env_values: Iterable[str] = (),
    *,
    enabled: bool = True,
    limit: int = SUMMARY_CHARS,
) -> tuple[str | None, list[dict[str, Any]]]:
    """A short field redacted, then cut, so no cut leaves part of a secret; None when empty."""
    if not text:
        return None, []
    clean, found = redact(text, env_values) if enabled else (text, [])
    return clean[:limit] or None, found


@dataclass(frozen=True)
class Bounded:
    text: str
    length: int
    truncated: bool


def bound(text: str, limit_bytes: int) -> Bounded:
    """Cut ``text`` to ``limit_bytes`` of UTF-8 without splitting a character; keep its length."""
    data = text.encode("utf-8")
    if len(data) <= limit_bytes:
        return Bounded(text, len(text), False)
    return Bounded(data[:limit_bytes].decode("utf-8", errors="ignore"), len(text), True)
