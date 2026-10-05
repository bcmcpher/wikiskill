"""Correction signals written from the command line: explicit notes.

The logger records what it can see happen after a component runs (follow-up turns, repeated
activations). A note is the user saying so outright, which is the one correction signal with
`explicit` confidence. It is written into the session's own log, beside the activation it is
about, so a reader of that trajectory finds it without a join.

Nothing here classifies anything. A note is stored as the user wrote it; whether it is a
correction, a complaint or praise is the wiki maintainer's call.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from . import paths, rawlog
from .collection import Collection

#: Sessions seen within this window count as active when deciding which one a note belongs to.
ACTIVE_WITHIN = timedelta(hours=1)

#: Identity fields a note copies from the session it is attached to.
_IDENTITY = (
    "origin",
    "harness",
    "harness_version",
    "provider",
    "model",
    "collection",
    "session_id",
    "root_session_id",
    "parent_session_id",
)


class NoteError(rawlog.RawLogError):
    """A note could not be attached to a session."""


@dataclass
class Note:
    event: dict[str, Any]
    path: Path
    warnings: list[str] = field(default_factory=list)


def active_sessions_path(raw_dir: Path, directory: str | os.PathLike[str]) -> Path:
    """`raw/.sessions/<project-hash>.json`, as the OpenCode logger writes it."""
    digest = hashlib.sha256(str(directory).encode("utf-8")).hexdigest()[:16]
    return Path(raw_dir) / ".sessions" / f"{digest}.json"


def active_sessions(raw_dir: Path, directory: str | os.PathLike[str]) -> list[tuple[str, datetime]]:
    """Logged sessions recently active in a project directory, most recent first."""
    path = active_sessions_path(raw_dir, directory)
    try:
        published = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    sessions = published.get("sessions") if isinstance(published, dict) else None
    if not isinstance(sessions, dict):
        return []
    found = []
    for session_id, seen in sessions.items():
        try:
            when = datetime.fromisoformat(str(seen).replace("Z", "+00:00"))
        except ValueError:
            continue
        found.append((session_id, when))
    return sorted(found, key=lambda item: item[1], reverse=True)


def _candidate_directories(cwd: Path) -> list[Path]:
    """The working directory as given and as resolved: OpenCode may report either."""
    found = [cwd]
    try:
        resolved = cwd.resolve()
    except OSError:
        return found
    if resolved != cwd:
        found.append(resolved)
    return found


def find_session(raw_dir: Path, cwd: Path, now: datetime | None = None) -> tuple[str, list[str]]:
    """The session a note run from `cwd` belongs to, and warnings about the choice."""
    now = now or datetime.now(UTC)
    sessions: list[tuple[str, datetime]] = []
    for directory in _candidate_directories(cwd):
        sessions = active_sessions(raw_dir, directory)
        if sessions:
            break
    if not sessions:
        raise NoteError(
            f"no logged session is recorded for {cwd}. A session is recorded once a watched "
            "component has run in it; pass --session to name one."
        )
    warnings = []
    recent = [session for session, seen in sessions if now - seen <= ACTIVE_WITHIN]
    if len(recent) > 1:
        warnings.append(
            f"{len(recent)} logged sessions were active here in the last hour; attached the note "
            f"to the most recent, {sessions[0][0]}. Pass --session to choose another: "
            + ", ".join(recent[1:])
        )
    return sessions[0][0], warnings


def session_log(raw_dir: Path, session_id: str) -> tuple[Path, list[dict[str, Any]]]:
    """The log file holding a session's events, and those events.

    A child session writes into its root's file, so this looks for the session's own events in
    every file rather than for a file named after it.
    """
    own_name = rawlog.session_log_path(raw_dir, "0000-00-00", session_id).name
    files = rawlog.log_files(raw_dir)
    # Its own file first, if it is a root; then every other, for a child.
    for path in sorted(files, key=lambda path: path.name != own_name):
        events = list(rawlog.read_events(path))
        if any(event.get("session_id") == session_id for event in events):
            return path, events
    raise NoteError(f"no events for session {session_id!r} under {raw_dir}")


def _matches(name: str, wanted: str) -> bool:
    """`preregister` names `govern/preregister`; a full name must match exactly."""
    return name == wanted or ("/" not in wanted and name.rsplit("/", 1)[-1] == wanted)


def _parse_component(text: str) -> tuple[str | None, str]:
    kind, sep, name = text.partition(":")
    if sep and kind in ("skill", "agent", "command"):
        return kind, name
    return None, text


def _resolve_component(
    collection: Collection, events: list[dict[str, Any]], wanted: str
) -> dict[str, Any]:
    kind, name = _parse_component(wanted)
    # The version that ran in this session, when it did run here.
    for event in reversed(events):
        component = event.get("component")
        if (
            event.get("type") == "component_activated"
            and isinstance(component, dict)
            and _matches(str(component.get("name", "")), name)
            and (kind is None or component.get("kind") == kind)
        ):
            return dict(component)
    # Otherwise the version on disk now: the user is pointing at a component this session did not
    # activate, so there is no hash from the run to prefer.
    candidates = [
        c
        for c in collection.watched()
        if _matches(c.name, name) and (kind is None or c.kind == kind)
    ]
    if not candidates:
        raise NoteError(
            f"{wanted!r} is not a watched component of {collection.name!r}. "
            "Use `wikiskill collection show` to list them."
        )
    if len(candidates) > 1:
        names = ", ".join(f"{c.kind}:{c.name}" for c in candidates)
        raise NoteError(f"{wanted!r} names more than one component ({names}); be specific")
    found = candidates[0]
    return {"kind": found.kind, "name": found.name, "source_hash": rawlog.file_hash(found.path)}


def _last_activated(events: list[dict[str, Any]]) -> dict[str, Any] | None:
    # The root's file holds its children's events too; a subagent's activation counts, since the
    # user is reacting to the whole trajectory.
    for event in reversed(events):
        component = event.get("component")
        if event.get("type") == "component_activated" and isinstance(component, dict):
            return dict(component)
    return None


def write_note(
    collection: Collection,
    text: str,
    *,
    session: str | None = None,
    component: str | None = None,
    cwd: Path | None = None,
    raw_dir: Path | None = None,
) -> Note:
    """Append a `note` event to the log of the session it is about."""
    text = text.strip()
    if not text:
        raise NoteError("a note needs some text")
    root = Path(raw_dir) if raw_dir is not None else paths.raw_dir(collection.name)
    cwd = Path(cwd) if cwd is not None else Path.cwd()
    warnings: list[str] = []
    if session is None:
        session, warnings = find_session(root, cwd)
    path, events = session_log(root, session)

    own = [event for event in events if event.get("session_id") == session]
    identity = {key: own[-1].get(key) for key in _IDENTITY}
    if component:
        ref, attributed_by = _resolve_component(collection, events, component), "named"
    else:
        ref = _last_activated(events)
        attributed_by = "last_activated" if ref else "none"
        if ref is None:
            warnings.append("no component has activated in this session; the note names none")

    event = {
        **identity,
        "origin": "live",
        "component": ref,
        "type": "note",
        "confidence": "explicit",
        "payload": {"text": text, "attributed_by": attributed_by, "cwd": str(cwd)},
    }
    written = rawlog.RawLogWriter(path).append(event)
    return Note(event=written, path=path, warnings=warnings)
