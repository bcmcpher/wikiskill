"""Read-side tools over the raw log: validate, summarise, and follow."""

from __future__ import annotations

import json
import time
from collections import Counter
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import paths, rawlog
from .collection import Collection


@dataclass
class ValidationReport:
    raw_dir: Path
    files: int = 0
    events: int = 0
    activations: int = 0
    problems: list[rawlog.ValidationProblem] = field(default_factory=list)
    refused: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.problems and not self.refused


def validate(collection: Collection | str, raw_dir: Path | None = None) -> ValidationReport:
    """Validate every log of a collection against the raw event schema."""
    name = collection if isinstance(collection, str) else collection.name
    root = Path(raw_dir) if raw_dir is not None else paths.raw_dir(name)
    report = ValidationReport(raw_dir=root)
    for file in rawlog.log_files(root):
        report.files += 1
        try:
            for number, event in rawlog.numbered_events(file):
                report.events += 1
                if event.get("type") == "component_activated":
                    report.activations += 1
                for message in rawlog.schema_errors(event):
                    location, _, detail = message.partition(": ")
                    report.problems.append(rawlog.ValidationProblem(file, number, detail, location))
        except rawlog.UnsupportedSchemaVersion as exc:
            report.refused.append(str(exc))
        except rawlog.RawLogError as exc:
            report.refused.append(str(exc))
    return report


@dataclass
class Stats:
    raw_dir: Path
    sessions: int = 0
    events: int = 0
    bytes: int = 0
    days: list[str] = field(default_factory=list)
    by_type: Counter = field(default_factory=Counter)
    by_model: Counter = field(default_factory=Counter)
    by_component: Counter = field(default_factory=Counter)
    reads_without_activation: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def megabytes(self) -> float:
        return self.bytes / (1024 * 1024)


def stats(collection: Collection | str, raw_dir: Path | None = None) -> Stats:
    """Summarise a collection's raw log, including the missed-activation signal.

    A session that read a watched component's source file but never recorded an activation is worth
    surfacing: it means the model consumed the skill text some way the logger did not recognise.
    """
    name = collection if isinstance(collection, str) else collection.name
    watched_paths = set()
    if isinstance(collection, Collection):
        watched_paths = {str(c.path) for c in collection.watched()}
    root = Path(raw_dir) if raw_dir is not None else paths.raw_dir(name)
    summary = Stats(raw_dir=root)
    days = set()

    for file in rawlog.log_files(root):
        summary.sessions += 1
        summary.bytes += file.stat().st_size
        days.add(file.parent.name)
        activated = False
        touched_watched = False
        try:
            for event in rawlog.read_events(file):
                summary.events += 1
                summary.by_type[event.get("type", "?")] += 1
                summary.by_model[f"{event.get('provider')}/{event.get('model')}"] += 1
                component = event.get("component")
                if isinstance(component, dict):
                    kind = component.get("kind") or "?"
                    name = component.get("name") or "?"
                    summary.by_component[f"{kind}:{name}"] += 1
                if event.get("type") == "component_activated":
                    activated = True
                elif (
                    event.get("type") == "tool_call"
                    and watched_paths
                    and _mentions_watched(event.get("payload") or {}, watched_paths)
                ):
                    touched_watched = True
        except (rawlog.RawLogError, OSError) as exc:
            summary.errors.append(str(exc))
            continue
        if touched_watched and not activated:
            summary.reads_without_activation.append(file.stem)

    summary.days = sorted(days)
    return summary


def _mentions_watched(payload: dict[str, Any], watched_paths: set[str]) -> bool:
    """Whether a tool call's input names a watched component's source file."""
    try:
        blob = json.dumps(payload.get("input") or {})
    except (TypeError, ValueError):
        return False
    return any(path in blob for path in watched_paths)


def tail(
    collection: Collection | str,
    *,
    raw_dir: Path | None = None,
    count: int = 20,
    follow: bool = False,
    poll_seconds: float = 0.5,
) -> Iterator[dict[str, Any]]:
    """The most recent events across a collection's logs, optionally following new ones."""
    name = collection if isinstance(collection, str) else collection.name
    root = Path(raw_dir) if raw_dir is not None else paths.raw_dir(name)

    seen: set[str] = set()
    sizes: dict[Path, int] = {}
    recent: list[dict[str, Any]] = []
    for file in rawlog.log_files(root):
        for event in _events_of(file, sizes):
            recent.append(event)
            seen.add(_event_key(event))
    recent.sort(key=lambda e: e.get("event_id", ""))
    for event in recent[-count:]:
        yield event

    while follow:
        time.sleep(poll_seconds)
        fresh = []
        for file in rawlog.log_files(root):
            # Only a file that grew can hold anything new, so following a collection does not
            # re-parse every log it has ever written on each poll.
            try:
                size = file.stat().st_size
            except OSError:
                continue
            if sizes.get(file) == size:
                continue
            for event in _events_of(file, sizes):
                key = _event_key(event)
                if key not in seen:
                    seen.add(key)
                    fresh.append(event)
        fresh.sort(key=lambda e: e.get("event_id", ""))
        yield from fresh


def _events_of(file: Path, sizes: dict[Path, int]) -> list[dict[str, Any]]:
    """The events of one file, recording its size. A file that cannot be read is skipped.

    A follow loop must survive one bad log: a single truncated line or a log from a future schema
    version should not end a `tail -f` that is watching a whole collection.
    """
    try:
        events = list(rawlog.read_events(file))
        sizes[file] = file.stat().st_size
    except (rawlog.RawLogError, OSError):
        return []
    return events


def _event_key(event: dict[str, Any]) -> str:
    """What identifies an event for de-duplication, without assuming the line is well formed."""
    event_id = event.get("event_id")
    if isinstance(event_id, str) and event_id:
        return event_id
    return json.dumps(event, sort_keys=True, default=str)
