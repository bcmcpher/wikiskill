"""The harness-neutral raw event log: identity, validation, reading and append-only writing.

The log is immutable. Nothing in this module rewrites or deletes an existing line; the only write
operation appends. Readers refuse a major schema version they do not know rather than misreading it.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import time
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from . import RAW_SCHEMA_VERSION, paths

_CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
_ULID_RE = re.compile(r"^[0-7][0-9ABCDEFGHJKMNPQRSTVWXYZ]{25}$")

#: Event types defined by add-trace-logging. add-correction-capture appends to this list.
EVENT_TYPES = (
    "session_start",
    "component_activated",
    "delegation",
    "tool_call",
    "assistant_turn",
    "step_usage",
    "error",
    "session_end",
)


class RawLogError(Exception):
    """Base class for raw log failures."""


class UnsupportedSchemaVersion(RawLogError):
    """A log was written by a schema major version this reader does not support."""

    def __init__(self, found: Any, path: Path | None = None, line: int | None = None) -> None:
        where = f" in {path}" if path else ""
        where += f" at line {line}" if line else ""
        super().__init__(
            f"raw event schema_version {found!r} is not supported{where}: "
            f"this build of wikiskill reads major version {RAW_SCHEMA_VERSION}. "
            "Refusing the file rather than misreading it."
        )
        self.found = found
        self.path = path
        self.line = line


@dataclass(frozen=True)
class ValidationProblem:
    """One schema or structural complaint about one line."""

    path: Path
    line: int
    message: str
    location: str = ""

    def __str__(self) -> str:
        at = f" at {self.location}" if self.location else ""
        return f"{self.path}:{self.line}{at}: {self.message}"


# --------------------------------------------------------------------------- identity


def new_event_id(when_ms: int | None = None) -> str:
    """A ULID: 48 bits of millisecond timestamp then 80 random bits, Crockford base32."""
    ms = int(time.time() * 1000) if when_ms is None else when_ms
    value = (ms << 80) | secrets.randbits(80)
    out = []
    for shift in range(125, -1, -5):
        out.append(_CROCKFORD[(value >> shift) & 0x1F])
    return "".join(out)


def is_event_id(value: str) -> bool:
    return bool(_ULID_RE.match(value))


def now_ts() -> str:
    """RFC 3339 timestamp in UTC, millisecond precision — matches what the plugin writes."""
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def content_hash(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def file_hash(path: str | os.PathLike[str]) -> str | None:
    """SHA-256 of a component's main file, or None when it cannot be read."""
    try:
        return content_hash(Path(path).read_bytes())
    except OSError:
        return None


# --------------------------------------------------------------------------- schema


@lru_cache(maxsize=1)
def load_schema() -> dict[str, Any]:
    with paths.schema_path().open(encoding="utf-8") as handle:
        return json.load(handle)


@lru_cache(maxsize=1)
def _validator() -> Draft202012Validator:
    schema = load_schema()
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


def schema_errors(event: dict[str, Any]) -> list[str]:
    """Schema complaints about one event, innermost first, as readable strings."""
    problems = []
    for error in sorted(_validator().iter_errors(event), key=lambda e: list(e.absolute_path)):
        location = "/".join(str(part) for part in error.absolute_path) or "<event>"
        problems.append(f"{location}: {error.message}")
    return problems


def check_supported(version: Any, path: Path | None = None, line: int | None = None) -> None:
    """Raise UnsupportedSchemaVersion unless ``version`` is a major version we read."""
    if not isinstance(version, int) or isinstance(version, bool) or version != RAW_SCHEMA_VERSION:
        raise UnsupportedSchemaVersion(version, path=path, line=line)


# --------------------------------------------------------------------------- reading


def log_files(raw_root: str | os.PathLike[str]) -> list[Path]:
    """Every session log under a raw directory, oldest day first. Skips logger bookkeeping."""
    root = Path(raw_root)
    if not root.is_dir():
        return []
    return sorted(p for p in root.glob("*/*.jsonl") if not p.name.startswith("_"))


def read_events(path: str | os.PathLike[str]) -> Iterator[dict[str, Any]]:
    """Yield the events of one log file.

    Raises UnsupportedSchemaVersion on the first line carrying an unknown major version, before
    yielding anything from it, so a caller cannot half-consume a file it cannot understand.
    """
    file_path = Path(path)
    with file_path.open(encoding="utf-8") as handle:
        for number, raw_line in enumerate(handle, start=1):
            line = raw_line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError as exc:
                raise RawLogError(f"{file_path}:{number}: not valid JSON: {exc.msg}") from exc
            if not isinstance(event, dict):
                raise RawLogError(f"{file_path}:{number}: expected a JSON object")
            check_supported(event.get("schema_version"), path=file_path, line=number)
            yield event


def validate_file(path: str | os.PathLike[str]) -> list[ValidationProblem]:
    """Every schema problem in one log file. Propagates UnsupportedSchemaVersion."""
    file_path = Path(path)
    problems: list[ValidationProblem] = []
    for number, event in enumerate(read_events(file_path), start=1):
        for message in schema_errors(event):
            location, _, detail = message.partition(": ")
            problems.append(ValidationProblem(file_path, number, detail, location))
    return problems


# --------------------------------------------------------------------------- writing


def day_of(ts: str) -> str:
    """The ``YYYY-MM-DD`` directory an event belongs in, from its timestamp."""
    return ts[:10]


def session_log_path(raw_root: str | os.PathLike[str], ts: str, root_session_id: str) -> Path:
    """``raw/<YYYY-MM-DD>/<root_session_id>.jsonl`` — one file per root session."""
    safe = re.sub(r"[^A-Za-z0-9._-]", "_", root_session_id)
    return Path(raw_root) / day_of(ts) / f"{safe}.jsonl"


class RawLogWriter:
    """Append-only writer for one session log.

    Opened in ``a`` mode and flushed per event so a killed harness loses at most the current line.
    """

    def __init__(self, path: str | os.PathLike[str], *, validate: bool = True) -> None:
        self.path = Path(path)
        self.validate = validate
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def append(self, event: dict[str, Any]) -> dict[str, Any]:
        event = dict(event)
        event.setdefault("schema_version", RAW_SCHEMA_VERSION)
        event.setdefault("event_id", new_event_id())
        event.setdefault("ts", now_ts())
        check_supported(event["schema_version"], path=self.path)
        if self.validate:
            problems = schema_errors(event)
            if problems:
                raise RawLogError(
                    f"refusing to append an invalid {event.get('type')!r} event to {self.path}: "
                    + "; ".join(problems)
                )
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n")
            handle.flush()
        return event

    def extend(self, events: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
        return [self.append(event) for event in events]
