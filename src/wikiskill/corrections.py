"""Correction signals written from the command line: explicit notes and output edits.

The logger records what it can see happen after a component runs (follow-up turns, repeated
activations). A note is the user saying so outright, which is the one correction signal with
`explicit` confidence. It is written into the session's own log, beside the activation it is
about, so a reader of that trajectory finds it without a join.

An output edit is the other signal found outside the session: a file a component wrote, changed
afterwards by something no logged tool call explains. The loggers record each file a write or edit
call left on disk, with its hash (`produced_files`); `scan` compares those hashes with the files
now.

Nothing here classifies anything. A note is stored as the user wrote it; whether it is a
correction, a complaint or praise is the wiki maintainer's call.
"""

from __future__ import annotations

import contextlib
import difflib
import fcntl
import hashlib
import json
import os
import subprocess
from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from . import names, paths, rawlog
from .collection import Collection
from .redact import bound, env_secrets, redact

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


#: How long a session stays in the active-session file, and how many it keeps.
ACTIVE_TTL = timedelta(hours=24)
ACTIVE_LIMIT = 20


def active_sessions_path(raw_dir: Path, directory: str | os.PathLike[str]) -> Path:
    """`raw/.sessions/<project-hash>.json`, as the OpenCode logger writes it."""
    digest = hashlib.sha256(str(directory).encode("utf-8")).hexdigest()[:16]
    return Path(raw_dir) / ".sessions" / f"{digest}.json"


def publish_active(
    raw_dir: Path, directory: str, session_id: str, now: datetime | None = None
) -> Path:
    """Record a logged root session as active in `directory`: the Claude Code hooks' twin of the
    OpenCode logger's `noteActiveSession`, writing the same file in the same shape."""
    now = now or datetime.now(UTC)
    path = active_sessions_path(raw_dir, directory)
    sessions = {session: seen for session, seen in active_sessions(raw_dir, directory)}
    sessions[session_id] = now
    kept = sorted(
        ((s, seen) for s, seen in sessions.items() if now - seen <= ACTIVE_TTL),
        key=lambda item: item[1],
        reverse=True,
    )[:ACTIVE_LIMIT]
    path.parent.mkdir(parents=True, exist_ok=True)
    staging = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    staging.write_text(
        json.dumps(
            {
                "directory": directory,
                "sessions": {s: seen.isoformat().replace("+00:00", "Z") for s, seen in kept},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    os.replace(staging, path)
    return path


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
            and names.matches(str(component.get("name", "")), name)
            and (kind is None or component.get("kind") == kind)
        ):
            return dict(component)
    # Otherwise the version on disk now: the user is pointing at a component this session did not
    # activate, so there is no hash from the run to prefer.
    candidates = [
        c
        for c in collection.watched()
        if names.matches(c.name, name) and (kind is None or c.kind == kind)
    ]
    if not candidates:
        raise NoteError(
            f"{wanted!r} is not a watched component of {collection.name!r}. "
            "Use `wikiskill collection show` to list them."
        )
    if len(candidates) > 1:
        listed = ", ".join(f"{c.kind}:{c.name}" for c in candidates)
        raise NoteError(f"{wanted!r} names more than one component ({listed}); be specific")
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
    env: Mapping[str, str] | None = None,
) -> Note:
    """Append a `note` event to the log of the session it is about.

    The text is redacted as other logged text is, against ``env`` (this process's environment by
    default), unless the collection turns redaction off.
    """
    text = text.strip()
    if not text:
        raise NoteError("a note needs some text")
    redactions: list[dict[str, Any]] = []
    if collection.redact:
        text, redactions = redact(text, env_secrets(os.environ if env is None else env))
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
    if redactions:
        event["redactions"] = redactions
    written = rawlog.RawLogWriter(path).append(event)
    return Note(event=written, path=path, warnings=warnings)


# --------------------------------------------------------------------------- output edits

#: Tools that write files, by harness, and the argument naming the file. A patch names its files in
#: its text instead (`patch_paths`).
WRITE_TOOLS: Mapping[str, tuple[str, ...]] = {
    # OpenCode
    "write": ("filePath",),
    "edit": ("filePath",),
    "multiedit": ("filePath",),
    # Claude Code
    "Write": ("file_path",),
    "Edit": ("file_path",),
    "MultiEdit": ("file_path",),
    "NotebookEdit": ("notebook_path",),
}
PATCH_TOOLS = frozenset({"patch", "apply_patch"})

#: Tools that cannot change a file, so a later call to one explains nothing.
READ_ONLY_TOOLS = frozenset(
    {
        *("read", "grep", "glob", "list", "webfetch", "websearch", "todoread", "todowrite"),
        *("skill", "task", "lsp", "codesearch"),
        *("Read", "Grep", "Glob", "LS", "WebFetch", "WebSearch", "TodoWrite", "Skill", "Agent"),
        *("Task", "TaskOutput", "ToolSearch"),
    }
)

#: Only logs written within this window are scanned, and at most this many files compared.
SCAN_WITHIN = timedelta(days=30)
SCAN_LIMIT = 500
#: An `output_edit` diff is cut to this many bytes.
DIFF_LIMIT = 8 * 1024
#: The produced files one tool call may record.
PRODUCED_LIMIT = 50

_PATCH_HEADER = ("*** Add File: ", "*** Update File: ", "*** Delete File: ", "*** Move to: ")


def patch_paths(text: str) -> list[str]:
    """The files an `apply_patch` envelope adds, updates, deletes or moves to."""
    found = []
    for line in text.splitlines():
        for header in _PATCH_HEADER:
            if line.startswith(header) and line[len(header) :].strip():
                found.append(line[len(header) :].strip())
    return list(dict.fromkeys(found))


def produced_files(
    tool: str, args: Mapping[str, Any], cwd: str | os.PathLike[str] | None
) -> list[dict[str, Any]]:
    """The files a successful write, edit or patch call left behind, hashed as they are now.

    The Claude Code hooks call this after the tool ran; the OpenCode logger has its own copy
    (`wikiskill/produced.ts`). Relative paths are resolved against the session's directory.
    """
    if tool in WRITE_TOOLS:
        written = [str(args[key]) for key in WRITE_TOOLS[tool] if args.get(key)]
    elif tool in PATCH_TOOLS:
        text = args.get("patchText") or args.get("patch") or args.get("input") or ""
        written = patch_paths(str(text))
    else:
        return []
    base = Path(cwd) if cwd else Path.cwd()
    found = []
    for name in written[:PRODUCED_LIMIT]:
        path = Path(name).expanduser()
        if not path.is_absolute():
            path = base / path
        path = Path(os.path.normpath(path))
        found.append({"path": str(path), "hash": rawlog.file_hash(path)})
    return found


@dataclass
class _Mark:
    """One point at which wikiskill knew a file's content: a produce, or an earlier output edit."""

    order: tuple[str, str, int]
    event: dict[str, Any]
    log: Path
    hash: str | None


@dataclass
class _Seen:
    marks: dict[str, list[_Mark]] = field(default_factory=dict)
    #: Content a write call logged in full, by its hash: the `before` of a later diff.
    contents: dict[str, str] = field(default_factory=dict)
    #: Calls that may have changed a file without saying which: (order, their input as text).
    touches: list[tuple[tuple[str, str, int], str]] = field(default_factory=list)


def _order(event: dict[str, Any], log: Path, line: int) -> tuple[str, str, int]:
    """Time, then place in the log: events one process writes in a millisecond share a timestamp,
    and their ids' random tails do not say which came first; the file does."""
    return str(event.get("ts", "")), str(log), line


def _read_logs(raw_dir: Path, now: datetime) -> _Seen:
    seen = _Seen()
    cutoff = (now - SCAN_WITHIN).timestamp()
    for log in rawlog.log_files(raw_dir):
        try:
            if log.stat().st_mtime < cutoff:
                continue
            events = list(rawlog.read_events(log))
        except (OSError, rawlog.RawLogError):
            continue
        for line, event in enumerate(events):
            if event.get("origin") != "live":
                continue
            _note_event(seen, event, _order(event, log, line), log)
    return seen


def _note_event(seen: _Seen, event: dict[str, Any], order: tuple[str, str, int], log: Path) -> None:
    payload = event.get("payload") or {}
    if event.get("type") == "output_edit":
        mark = _Mark(order, event, log, payload.get("after_hash"))
        seen.marks.setdefault(str(payload.get("path")), []).append(mark)
        return
    if event.get("type") != "tool_call" or not payload.get("ok"):
        return
    produced = payload.get("produced_files") or []
    for entry in produced:
        seen.marks.setdefault(entry["path"], []).append(_Mark(order, event, log, entry["hash"]))
    args = payload.get("input") or {}
    content = args.get("content") if isinstance(args, dict) else None
    if isinstance(content, str):
        seen.contents.setdefault(rawlog.content_hash(content.encode("utf-8")), content)
    if not produced and str(payload.get("tool")) not in READ_ONLY_TOOLS:
        seen.touches.append((order, json.dumps(args, ensure_ascii=False)))


def _git_before(path: Path, before_hash: str) -> str | None:
    """The file as git has it, at HEAD or in the index, if that is the content last recorded."""
    for spec in (f"HEAD:./{path.name}", f":./{path.name}"):
        try:
            shown = subprocess.run(
                ["git", "-C", str(path.parent), "show", spec],
                capture_output=True,
                timeout=5,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            return None
        if shown.returncode == 0 and rawlog.content_hash(shown.stdout) == before_hash:
            return shown.stdout.decode("utf-8", errors="replace")
    return None


def _diff(
    path: Path, before_hash: str, contents: Mapping[str, str], secrets: list[str] | None
) -> tuple[str | None, bool, str | None]:
    """A unified diff from the recorded content to the file now: (diff, truncated, source).

    The scan only has hashes, so the `before` side is whatever content matches one: the text a
    write call logged, else git's copy. With neither, the edit is still recorded, without a diff.
    """
    before, source = contents.get(before_hash), "content"
    if before is None:
        before, source = _git_before(path, before_hash), "git"
    if before is None:
        return None, False, None
    try:
        data = path.read_bytes() if path.exists() else b""
    except OSError:
        return None, False, None
    if b"\0" in data:
        return None, False, None
    after = data.decode("utf-8", errors="replace")
    lines = difflib.unified_diff(
        before.splitlines(keepends=True),
        after.splitlines(keepends=True),
        fromfile=f"a/{path.name}",
        tofile=f"b/{path.name}",
    )
    # A last line without a newline would run into the next one; mark it as git does.
    text = "".join(
        line if line.endswith("\n") else line + "\n\\ No newline at end of file\n" for line in lines
    )
    if secrets is not None:
        text, _ = redact(text, secrets)
    limited = bound(text, DIFF_LIMIT)
    return limited.text, limited.truncated, source


def _explained(seen: _Seen, path: str, since: tuple[str, str, int]) -> bool:
    """A logged call after the last known content that may have changed the file, such as a shell
    command naming it. Nothing can say what it did, so the change is not the user's to own."""
    name = Path(path).name
    return any(order > since and name in text for order, text in seen.touches)


@contextlib.contextmanager
def _scan_lock(raw_dir: Path) -> Iterator[bool]:
    """Held for a whole scan; a second scan of the same directory finds it held and stops, rather
    than recording the same edit twice."""
    lock = raw_dir / ".sessions" / "scan.lock"
    lock.parent.mkdir(parents=True, exist_ok=True)
    with lock.open("a") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            yield False
            return
        try:
            yield True
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def scan(
    raw_dir: Path,
    *,
    redact_diffs: bool = True,
    env: Mapping[str, str] | None = None,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    """Record an `output_edit` for each produced file that changed since wikiskill last knew it.

    Returns the events written. The last known content is the latest of a logged write and an
    earlier `output_edit`, so each change is recorded once, however often this runs.
    """
    raw_dir = Path(raw_dir)
    if not raw_dir.is_dir():
        return []
    now = now or datetime.now(UTC)
    secrets = env_secrets(os.environ if env is None else env) if redact_diffs else None
    written: list[dict[str, Any]] = []
    with _scan_lock(raw_dir) as held:
        if not held:
            return []
        seen = _read_logs(raw_dir, now)
        newest = sorted(seen.marks.items(), key=lambda item: max(m.order for m in item[1]))
        for path, marks in reversed(newest[-SCAN_LIMIT:]):
            event = _edit_event(seen, Path(path), sorted(marks, key=lambda m: m.order), secrets)
            if event is not None:
                written.append(rawlog.RawLogWriter(event.pop("_log")).append(event))
    return written


def _edit_event(
    seen: _Seen, path: Path, marks: list[_Mark], secrets: list[str] | None
) -> dict[str, Any] | None:
    last = marks[-1]
    owner = next((m for m in reversed(marks) if m.event.get("component")), None)
    if last.hash is None or owner is None or _explained(seen, str(path), last.order):
        return None
    now_hash = rawlog.file_hash(path) if path.exists() else None
    if now_hash == last.hash:
        return None
    diff, truncated, source = _diff(path, last.hash, seen.contents, secrets)
    payload = owner.event.get("payload") or {}
    call_id = (
        payload.get("produced_by_call_id")
        if owner.event.get("type") == "output_edit"
        else payload.get("call_id")
    )
    return {
        **{key: owner.event.get(key) for key in _IDENTITY},
        "origin": "live",
        "component": owner.event["component"],
        "type": "output_edit",
        "confidence": "low",
        "payload": {
            "path": str(path),
            "before_hash": last.hash,
            "after_hash": now_hash,
            "diff": diff,
            "diff_truncated": truncated,
            "diff_source": source,
            "produced_by_call_id": call_id,
        },
        # Beside the run that produced it, as a note is.
        "_log": owner.log,
    }
