"""Install wikiskill's built components and harness logger into a harness config directory.

Two rules govern everything here. Install writes only files it owns and records exactly what it
wrote; uninstall removes exactly those recorded files and nothing beside them, so a user's own
skills sitting in the same directory survive.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from . import __version__, paths
from .build import build
from .collection import Collection
from .rawlog import content_hash

SCOPES = ("global", "project")

#: Where each harness keeps its components, per scope.
_TARGETS = {
    ("opencode", "global"): lambda: _xdg_config() / "opencode",
    ("opencode", "project"): lambda: Path.cwd() / ".opencode",
}

#: Subdirectory of the harness config directory that holds its plugins.
_PLUGIN_DIR = {"opencode": "plugin"}


class InstallError(Exception):
    """An install or uninstall cannot proceed."""


def _xdg_config() -> Path:
    raw = os.environ.get("XDG_CONFIG_HOME")
    return Path(raw).expanduser() if raw else Path.home() / ".config"


def target_dir(harness: str, scope: str) -> Path:
    try:
        return _TARGETS[(harness, scope)]()
    except KeyError:
        raise InstallError(
            f"no install target for harness {harness!r} at scope {scope!r}"
        ) from None


def record_path(harness: str, scope: str, target: Path) -> Path:
    """One record per (harness, scope, target), so two projects do not share bookkeeping."""
    slug = str(target).strip("/").replace("/", "%")
    return paths.state_home() / "installed" / f"{harness}-{scope}-{slug}.json"


@dataclass
class InstallResult:
    harness: str
    scope: str
    target: Path
    written: list[Path] = field(default_factory=list)
    unchanged: list[Path] = field(default_factory=list)
    removed: list[Path] = field(default_factory=list)
    skipped: list[Path] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    record: Path | None = None

    @property
    def changed(self) -> bool:
        return bool(self.written or self.removed)


# --------------------------------------------------------------------------- install


def install(
    harness: str,
    scope: str,
    *,
    collection: Collection | None = None,
    source: Path | None = None,
    target: Path | None = None,
    from_dist: Path | None = None,
) -> InstallResult:
    """Build, then sync the result plus the harness logger into the harness config directory.

    Re-running with unchanged sources writes nothing and reports no changes.
    """
    if scope not in SCOPES:
        raise InstallError(f"scope must be one of {', '.join(SCOPES)}")
    destination = Path(target) if target is not None else target_dir(harness, scope)
    result = InstallResult(harness=harness, scope=scope, target=destination)

    staged: dict[str, Path] = {}
    with tempfile.TemporaryDirectory(prefix="wikiskill-build-") as tmp:
        if from_dist is not None:
            built_dir = Path(from_dist)
            if not built_dir.is_dir():
                raise InstallError(f"no built layout at {built_dir}")
        else:
            built = build(
                harness, collection=collection, source=source, out_dir=Path(tmp) / harness
            )
            result.warnings.extend(built.warnings)
            built_dir = built.out_dir
        for file in sorted(p for p in built_dir.rglob("*") if p.is_file()):
            staged[str(file.relative_to(built_dir))] = file
        for relative, file in _logger_files(harness).items():
            staged[relative] = file

        previous = _load_record(harness, scope, destination)
        _sync(staged, destination, previous, result)

    # Imported here rather than at module scope: collection imports paths, paths is imported by
    # build, and build is imported here — a module-level import closes that loop.
    from .collection import publish_runtime_config  # noqa: PLC0415

    runtime, published, problems = publish_runtime_config(prefer=collection)
    if published:
        names = ", ".join(c.name for c in published)
        result.notes.append(f"logger configuration written to {runtime} ({names})")
    else:
        result.warnings.append(
            "no collection is configured, so the logger will record nothing; "
            "run `wikiskill collection init <name> --source <dir>` first"
        )
    result.warnings.extend(problems)

    result.record = _save_record(harness, scope, destination, result)
    return result


def _logger_files(harness: str) -> dict[str, Path]:
    """The harness logger's own files, keyed by their path relative to the harness config dir."""
    plugin_dir = _PLUGIN_DIR.get(harness)
    if plugin_dir is None:
        return {}
    root = _plugin_source(harness)
    if not root.is_dir():
        raise InstallError(f"no {harness} logger source at {root}")
    files = {}
    for file in sorted(root.rglob("*")):
        if not file.is_file():
            continue
        relative = file.relative_to(root)
        # Tests and package metadata are development-only and are not installed.
        if relative.parts[0] in {"test", "node_modules"} or relative.name in {
            "package.json",
            "tsconfig.json",
            "bun.lock",
            "README.md",
        }:
            continue
        files[str(Path(plugin_dir) / relative)] = file
    return files


def _plugin_source(harness: str) -> Path:
    here = Path(__file__).resolve().parent
    for candidate in (here / "_harness" / harness / "plugin",
                      here.parent.parent / "harness" / harness / "plugin"):
        if candidate.is_dir():
            return candidate
    return here.parent.parent / "harness" / harness / "plugin"


def _sync(
    staged: dict[str, Path],
    destination: Path,
    previous: dict | None,
    result: InstallResult,
) -> None:
    for relative, source_file in sorted(staged.items()):
        out = destination / relative
        payload = source_file.read_bytes()
        if out.is_file() and out.read_bytes() == payload:
            result.unchanged.append(out)
            continue
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(payload)
        shutil.copystat(source_file, out)
        result.written.append(out)

    # A component removed from the source tree must not linger in the harness directory.
    if previous:
        stale = {entry["path"] for entry in previous.get("files", [])} - {
            str(destination / relative) for relative in staged
        }
        for path_str in sorted(stale):
            stale_path = Path(path_str)
            if stale_path.is_file():
                stale_path.unlink()
                result.removed.append(stale_path)
        _prune_empty_dirs({Path(p).parent for p in stale}, destination)


# --------------------------------------------------------------------------- uninstall


def uninstall(
    harness: str,
    scope: str,
    *,
    target: Path | None = None,
    force: bool = False,
) -> InstallResult:
    """Remove exactly the files this install recorded, leaving everything else alone."""
    destination = Path(target) if target is not None else target_dir(harness, scope)
    result = InstallResult(harness=harness, scope=scope, target=destination)
    record = _load_record(harness, scope, destination)
    if record is None:
        raise InstallError(
            f"no install record for {harness} at scope {scope} under {destination}; "
            "nothing to uninstall"
        )

    directories: set[Path] = set()
    for entry in record.get("files", []):
        path = Path(entry["path"])
        if not path.is_file():
            continue
        if not force and entry.get("sha256") and content_hash(path.read_bytes()) != entry["sha256"]:
            result.skipped.append(path)
            result.warnings.append(
                f"{path} changed since install; left in place (use --force to remove it)"
            )
            continue
        path.unlink()
        result.removed.append(path)
        directories.add(path.parent)

    _prune_empty_dirs(directories, destination)

    record_file = record_path(harness, scope, destination)
    if result.skipped:
        record["files"] = [
            entry for entry in record.get("files", []) if Path(entry["path"]) in set(result.skipped)
        ]
        record_file.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
        result.record = record_file
    elif record_file.is_file():
        record_file.unlink()
    return result


def _prune_empty_dirs(directories: Iterable[Path], stop_at: Path) -> None:
    """Remove directories emptied by an uninstall, never passing above the install target."""
    stop = stop_at.resolve()
    for directory in sorted(directories, key=lambda p: len(p.parts), reverse=True):
        current = directory
        while True:
            try:
                resolved = current.resolve()
            except OSError:
                break
            if resolved == stop or stop not in resolved.parents:
                break
            try:
                current.rmdir()
            except OSError:
                break
            current = current.parent


# --------------------------------------------------------------------------- records


def _load_record(harness: str, scope: str, target: Path) -> dict | None:
    path = record_path(harness, scope, target)
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _save_record(harness: str, scope: str, target: Path, result: InstallResult) -> Path:
    path = record_path(harness, scope, target)
    path.parent.mkdir(parents=True, exist_ok=True)
    files = []
    for file in sorted(set(result.written) | set(result.unchanged)):
        files.append({"path": str(file), "sha256": content_hash(file.read_bytes())})
    path.write_text(
        json.dumps(
            {
                "harness": harness,
                "scope": scope,
                "target": str(target),
                "wikiskill_version": __version__,
                "installed_at": datetime.now(UTC).isoformat(timespec="seconds"),
                "files": files,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return path


def resolved_cli_path() -> str:
    """The absolute path of the running ``wikiskill``, for hooks that must call it explicitly."""
    found = shutil.which("wikiskill")
    if found:
        return found
    return f"{sys.executable} -m wikiskill"
