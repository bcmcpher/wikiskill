"""The collection manifest: what is watched, where it lives, and which model serves each role.

Loading a manifest and discovering its components is strictly read-only with respect to the source
directories. Nothing here opens a source file for writing, creates a directory under a source, or
runs a command in one.
"""

from __future__ import annotations

import fnmatch
import json
import tomllib
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import paths

LAYOUTS = ("opencode", "claude-plugin")
KINDS = ("skill", "agent", "command")
ROLES = ("judge", "maintainer", "proposer")

#: Directory names each layout may use, most conventional first.
_DIR_NAMES = {
    "skill": ("skills", "skill"),
    "agent": ("agents", "agent"),
    "command": ("commands", "command"),
}

DEFAULT_BUFFER_SIZE = 200
DEFAULT_OUTPUT_LIMIT = 16 * 1024


class ManifestError(Exception):
    """A manifest is missing, unparseable, or invalid. Carries every problem found."""

    def __init__(self, path: Path | None, problems: Sequence[str]) -> None:
        self.path = path
        self.problems = list(problems)
        where = f"{path}: " if path else ""
        joined = "\n  - ".join(self.problems)
        super().__init__(f"{where}invalid collection manifest\n  - {joined}")


@dataclass(frozen=True)
class Source:
    """One source directory and the layout its components are arranged in."""

    path: Path
    layout: str

    def dirs_for(self, kind: str) -> list[Path]:
        """Directories to scan for ``kind``, respecting the layout.

        ``opencode``      → ``<root>/skills/``
        ``claude-plugin`` → ``<root>/<plugin>/skills/`` for each plugin under the root
        """
        names = _DIR_NAMES[kind]
        if self.layout == "opencode":
            roots = [self.path]
        else:
            if not self.path.is_dir():
                return []
            roots = sorted(p for p in self.path.iterdir() if p.is_dir())
        return [root / name for root in roots for name in names if (root / name).is_dir()]


@dataclass(frozen=True)
class Component:
    """A discovered skill, agent, or command in a source tree."""

    kind: str
    name: str
    path: Path
    source: Source

    @property
    def plugin(self) -> str | None:
        return self.name.split("/", 1)[0] if "/" in self.name else None


@dataclass(frozen=True)
class Role:
    """A meta-role's own endpoint and model, independent of the models under test."""

    name: str
    model: str
    base_url: str | None = None
    api_key_env: str | None = None


@dataclass(frozen=True)
class Collection:
    name: str
    sources: tuple[Source, ...]
    watch: dict[str, tuple[str, ...]]
    roles: dict[str, Role] = field(default_factory=dict)
    aliases: dict[str, dict[str, str]] = field(default_factory=dict)
    targets: dict[str, tuple[str, ...]] = field(default_factory=dict)
    buffer_size: int = DEFAULT_BUFFER_SIZE
    output_limit_bytes: int = DEFAULT_OUTPUT_LIMIT
    redact: bool = True
    retention_days: int | None = None
    manifest_path: Path | None = None

    # ------------------------------------------------------------------ discovery

    def discover(self) -> list[Component]:
        """Every component in every source directory, read-only."""
        found: list[Component] = []
        for source in self.sources:
            found.extend(discover(source))
        return sorted(found, key=lambda c: (c.kind, c.name))

    def watched(self, components: Iterable[Component] | None = None) -> list[Component]:
        """The discovered components the watch list selects."""
        pool = list(components) if components is not None else self.discover()
        return [c for c in pool if self.matches(c.kind, c.name)]

    def matches(self, kind: str, name: str) -> bool:
        return any(fnmatch.fnmatchcase(name, pattern) for pattern in self.watch.get(kind, ()))

    def unresolved(self, components: Iterable[Component] | None = None) -> list[str]:
        """Watch-list entries that match nothing, as ``<kind>:<pattern>`` strings."""
        pool = list(components) if components is not None else self.discover()
        missing = []
        for kind in KINDS:
            for pattern in self.watch.get(kind, ()):
                if not any(c.kind == kind and fnmatch.fnmatchcase(c.name, pattern) for c in pool):
                    missing.append(f"{kind}:{pattern}")
        return missing

    # ------------------------------------------------------------------ models

    def resolve_alias(self, harness: str, alias: str) -> str | None:
        """A concrete ``provider/model`` for an alias in a harness, or None when unmapped.

        An unmapped alias is not an error: the built component omits a model and inherits its
        caller's.
        """
        return self.aliases.get(harness, {}).get(alias)

    def unmapped_aliases(self, harness: str, used: Iterable[str]) -> list[str]:
        table = self.aliases.get(harness, {})
        return sorted({alias for alias in used if alias and alias not in table})

    # ------------------------------------------------------------------ runtime view

    def runtime_config(self) -> dict[str, Any]:
        """The resolved, harness-agnostic view the OpenCode plugin reads at runtime.

        The plugin is TypeScript with no TOML parser, so Python owns manifest parsing and hands the
        plugin plain JSON.
        """
        return {
            "collection": self.name,
            "raw_dir": str(paths.raw_dir(self.name)),
            "error_log": str(paths.logger_error_log(self.name)),
            "buffer_size": self.buffer_size,
            "output_limit_bytes": self.output_limit_bytes,
            "redact": self.redact,
            "watch": {kind: list(self.watch.get(kind, ())) for kind in KINDS},
            "source_roots": [{"path": str(s.path), "layout": s.layout} for s in self.sources],
            "watched": [
                {"kind": c.kind, "name": c.name, "path": str(c.path)}
                for c in self.watched()
            ],
        }


# --------------------------------------------------------------------------- discovery


def discover(source: Source) -> list[Component]:
    """Components in one source tree. Never writes; unreadable directories are skipped."""
    found: list[Component] = []
    for kind in KINDS:
        for directory in source.dirs_for(kind):
            plugin = _plugin_of(source, directory)
            try:
                entries = sorted(directory.iterdir())
            except OSError:
                continue
            for entry in entries:
                main = _main_file(kind, entry)
                if main is None:
                    continue
                base = entry.name if kind == "skill" else entry.stem
                name = f"{plugin}/{base}" if plugin else base
                found.append(Component(kind=kind, name=name, path=main, source=source))
    return found


def _plugin_of(source: Source, directory: Path) -> str | None:
    """For a claude-plugin layout, the plugin a component directory belongs to."""
    if source.layout != "claude-plugin":
        return None
    return directory.parent.name


def _main_file(kind: str, entry: Path) -> Path | None:
    """The file whose content identifies a component version, or None if ``entry`` is not one."""
    if kind == "skill":
        main = entry / "SKILL.md"
        return main if main.is_file() else None
    return entry if entry.is_file() and entry.suffix == ".md" else None


# --------------------------------------------------------------------------- loading


def load(name: str) -> Collection:
    """Load the named collection from the wikiskill config directory."""
    return load_path(paths.manifest_path(name), expected_name=name)


def load_path(path: str | Path, *, expected_name: str | None = None) -> Collection:
    manifest = Path(path)
    if not manifest.is_file():
        raise ManifestError(manifest, [f"no manifest at {manifest}"])
    try:
        raw = tomllib.loads(manifest.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise ManifestError(manifest, [f"not valid TOML: {exc}"]) from exc
    except OSError as exc:
        raise ManifestError(manifest, [f"cannot read: {exc}"]) from exc
    return parse(raw, manifest_path=manifest, expected_name=expected_name)


def parse(
    raw: dict[str, Any],
    *,
    manifest_path: Path | None = None,
    expected_name: str | None = None,
) -> Collection:
    """Validate a parsed manifest and build a Collection, or raise with every problem."""
    problems: list[str] = []

    name = raw.get("name")
    if not isinstance(name, str) or not name.strip():
        problems.append("`name` is required and must be a non-empty string")
        name = expected_name or "unnamed"
    elif expected_name and name != expected_name:
        problems.append(f"`name` is {name!r} but the manifest file is named {expected_name!r}")

    sources = tuple(_parse_sources(raw.get("sources"), problems))
    watch = _parse_watch(raw.get("watch"), problems)
    roles = _parse_roles(raw.get("roles"), problems)
    aliases = _parse_aliases(raw.get("aliases"), problems)
    targets = _parse_targets(raw.get("targets"), problems)

    logging_table = raw.get("logging") or {}
    if not isinstance(logging_table, dict):
        problems.append("`[logging]` must be a table")
        logging_table = {}
    buffer_size = _parse_positive_int(logging_table, "buffer_size", DEFAULT_BUFFER_SIZE, problems)
    output_limit = _parse_positive_int(
        logging_table, "output_limit_bytes", DEFAULT_OUTPUT_LIMIT, problems
    )
    redact = logging_table.get("redact", True)
    if not isinstance(redact, bool):
        problems.append("`logging.redact` must be a boolean")
        redact = True
    retention = logging_table.get("retention_days")
    if retention is not None and (not isinstance(retention, int) or retention <= 0):
        problems.append("`logging.retention_days` must be a positive integer when set")
        retention = None

    unknown = set(raw) - {"name", "sources", "watch", "roles", "aliases", "targets", "logging"}
    if unknown:
        problems.append("unknown top-level keys: " + ", ".join(sorted(unknown)))

    collection = Collection(
        name=name,
        sources=sources,
        watch=watch,
        roles=roles,
        aliases=aliases,
        targets=targets,
        buffer_size=buffer_size,
        output_limit_bytes=output_limit,
        redact=redact,
        retention_days=retention,
        manifest_path=manifest_path,
    )
    problems.extend(judge_target_conflicts(collection))

    if problems:
        raise ManifestError(manifest_path, problems)
    return collection


def judge_target_conflicts(collection: Collection) -> list[str]:
    """Reject a judge that is also a model under test.

    A judge grading its own output is not a measurement, so this is an error rather than a warning.
    Comparison is on the bare model name as well as the full ``provider/model`` string, and target
    aliases are resolved first, so ``qwen3-32b`` and ``vllm/qwen3-32b`` count as the same model.
    """
    judge = collection.roles.get("judge")
    if judge is None:
        return []
    judge_forms = _model_forms(judge.model)
    conflicts = []
    for harness, models in sorted(collection.targets.items()):
        for target in models:
            resolved = collection.resolve_alias(harness, target) or target
            if judge_forms & _model_forms(resolved):
                conflicts.append(
                    f"`roles.judge.model` is {judge.model!r}, which is also a target model for "
                    f"{harness} (listed as {target!r}); the judge must not be a model under test"
                )
    return conflicts


def _model_forms(model: str) -> set[str]:
    """A model string and its bare name, lowercased, for provider-insensitive comparison."""
    lowered = model.strip().lower()
    return {lowered, lowered.rsplit("/", 1)[-1]} - {""}


# --------------------------------------------------------------------------- parse helpers


def _parse_sources(value: Any, problems: list[str]) -> list[Source]:
    if value is None:
        problems.append("`sources` is required and must list at least one source directory")
        return []
    if not isinstance(value, list) or not value:
        problems.append("`sources` must be a non-empty array of tables")
        return []
    sources = []
    for index, entry in enumerate(value):
        label = f"sources[{index}]"
        if not isinstance(entry, dict):
            problems.append(f"`{label}` must be a table with `path` and `layout`")
            continue
        path = entry.get("path")
        layout = entry.get("layout")
        if not isinstance(path, str) or not path.strip():
            problems.append(f"`{label}.path` is required")
            continue
        if layout not in LAYOUTS:
            problems.append(f"`{label}.layout` must be one of {', '.join(LAYOUTS)}")
            continue
        extra = set(entry) - {"path", "layout"}
        if extra:
            problems.append(f"`{label}` has unknown keys: {', '.join(sorted(extra))}")
        sources.append(Source(path=Path(path).expanduser(), layout=layout))
    return sources


def _parse_watch(value: Any, problems: list[str]) -> dict[str, tuple[str, ...]]:
    if value is None:
        return {kind: () for kind in KINDS}
    if not isinstance(value, dict):
        problems.append("`watch` must be a table of `skills`, `agents` and `commands` arrays")
        return {kind: () for kind in KINDS}
    watch: dict[str, tuple[str, ...]] = {}
    for kind in KINDS:
        key = f"{kind}s"
        entries = value.get(key, [])
        if not isinstance(entries, list) or not all(isinstance(e, str) for e in entries):
            problems.append(f"`watch.{key}` must be an array of strings")
            entries = []
        watch[kind] = tuple(entries)
    extra = set(value) - {f"{kind}s" for kind in KINDS}
    if extra:
        problems.append(f"`watch` has unknown keys: {', '.join(sorted(extra))}")
    if not any(watch.values()):
        problems.append(
            "`watch` selects nothing; list at least one skill, agent or command, or logging will "
            "never start"
        )
    return watch


def _parse_roles(value: Any, problems: list[str]) -> dict[str, Role]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        problems.append("`[roles]` must be a table of role tables")
        return {}
    roles = {}
    for role_name, entry in value.items():
        if role_name not in ROLES:
            problems.append(f"unknown role `roles.{role_name}`; expected one of {', '.join(ROLES)}")
            continue
        if not isinstance(entry, dict):
            problems.append(f"`roles.{role_name}` must be a table")
            continue
        model = entry.get("model")
        if not isinstance(model, str) or not model.strip():
            problems.append(f"`roles.{role_name}.model` is required")
            continue
        base_url = entry.get("base_url")
        if base_url is not None and not isinstance(base_url, str):
            problems.append(f"`roles.{role_name}.base_url` must be a string")
            base_url = None
        api_key_env = entry.get("api_key_env")
        if api_key_env is not None and not isinstance(api_key_env, str):
            problems.append(f"`roles.{role_name}.api_key_env` must be a string")
            api_key_env = None
        extra = set(entry) - {"model", "base_url", "api_key_env"}
        if extra:
            problems.append(f"`roles.{role_name}` has unknown keys: {', '.join(sorted(extra))}")
        roles[role_name] = Role(
            name=role_name, model=model, base_url=base_url, api_key_env=api_key_env
        )
    return roles


def _parse_aliases(value: Any, problems: list[str]) -> dict[str, dict[str, str]]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        problems.append("`[aliases]` must be a table of per-harness tables")
        return {}
    aliases: dict[str, dict[str, str]] = {}
    for harness, table in value.items():
        if not isinstance(table, dict) or not all(isinstance(v, str) for v in table.values()):
            problems.append(f"`aliases.{harness}` must map alias names to `provider/model` strings")
            continue
        aliases[harness] = dict(table)
    return aliases


def _parse_targets(value: Any, problems: list[str]) -> dict[str, tuple[str, ...]]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        problems.append("`[targets]` must map a harness to an array of models under test")
        return {}
    targets = {}
    for harness, models in value.items():
        if not isinstance(models, list) or not all(isinstance(m, str) for m in models):
            problems.append(f"`targets.{harness}` must be an array of strings")
            continue
        targets[harness] = tuple(models)
    return targets


def _parse_positive_int(table: dict[str, Any], key: str, default: int, problems: list[str]) -> int:
    value = table.get(key, default)
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        problems.append(f"`logging.{key}` must be a positive integer")
        return default
    return value


# --------------------------------------------------------------------------- init / sync


def render_manifest(
    name: str, sources: Sequence[Source], components: Sequence[Component]
) -> str:
    """A manifest with everything discovered commented out, for the user to opt in to.

    The watch list starts with one entry so `collection check` resolves; every other discovered
    component is listed as a comment, because opting in to logging is the user's decision.
    """
    lines = [
        f"# wikiskill collection: {name}",
        "# Written by `wikiskill collection init`. Edit the watch list, then run",
        f"# `wikiskill collection check {name}`.",
        "",
        f'name = "{name}"',
        "",
        "sources = [",
    ]
    for source in sources:
        lines.append(f'  {{ path = "{source.path}", layout = "{source.layout}" }},')
    lines += ["]", "", "[watch]"]
    for kind in KINDS:
        names = [c.name for c in components if c.kind == kind]
        key = f"{kind}s"
        if not names:
            lines.append(f"{key} = []")
            continue
        lines.append(f'{key} = ["{names[0]}"]')
        if len(names) > 1:
            lines.append("# discovered, not watched — add the ones you want logged:")
            for other in names[1:]:
                lines.append(f'#   "{other}",')
    lines += [
        "",
        "# Meta-roles run on their own endpoints, never on a model under test.",
        "# [roles.judge]",
        '# base_url = "http://localhost:11434/v1"',
        '# model = "qwen3:30b-a3b"',
        "",
        "# Abstract model aliases, resolved per harness at build time.",
        "# [aliases.opencode]",
        '# haiku = "ollama/qwen3:30b-a3b"',
        "",
        "# [logging]",
        f"# buffer_size = {DEFAULT_BUFFER_SIZE}",
        f"# output_limit_bytes = {DEFAULT_OUTPUT_LIMIT}",
        "# redact = true",
        "",
    ]
    return "\n".join(lines)


def runtime_config_path() -> Path:
    """Where the OpenCode plugin looks for its resolved configuration."""
    return paths.config_home() / "runtime.json"


def write_runtime_config(collections: Sequence[Collection]) -> Path:
    """Publish the resolved view of the given collections for the harness loggers to read.

    Prefer :func:`publish_runtime_config`: this file is the logger's *whole* world, so writing a
    subset of the configured collections silently stops logging the rest.
    """
    target = runtime_config_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": 1,
        "collections": [collection.runtime_config() for collection in collections],
    }
    target.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return target


def publish_runtime_config(
    *, prefer: Collection | None = None
) -> tuple[Path, list[Collection], list[str]]:
    """Publish every configured collection, and report the ones that could not be loaded.

    The logger reads one file and treats it as the complete list of what to watch, so this always
    rewrites it from every manifest on disk. Publishing only the collection at hand would quietly
    stop logging every other one.

    ``prefer`` supplies an already-loaded collection — the one the caller just validated — so its
    in-memory state is used rather than being re-read.
    """
    loaded: list[Collection] = []
    problems: list[str] = []
    for name in known_collections():
        if prefer is not None and name == prefer.name:
            loaded.append(prefer)
            continue
        try:
            loaded.append(load(name))
        except ManifestError as exc:
            problems.append(f"{name}: not published, its manifest is invalid ({exc.problems[0]})")
    if prefer is not None and prefer.name not in known_collections():
        loaded.append(prefer)
    return write_runtime_config(loaded), loaded, problems


def known_collections() -> list[str]:
    directory = paths.collections_dir()
    if not directory.is_dir():
        return []
    return sorted(p.stem for p in directory.glob("*.toml"))
