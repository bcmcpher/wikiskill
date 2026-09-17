"""Build wikiskill's single-source components into a harness layout.

The source tree under ``harness/source/`` is the only place these components are authored. Every
harness layout is generated from it, so a fix to a skill reaches every harness by rebuilding. Build
output is owned by this module: it is cleared and rewritten on each run, and is git-ignored.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import paths
from .collection import Collection
from .frontmatter import Document
from .frontmatter import read as read_frontmatter

HARNESSES = ("opencode",)

#: Neutral capabilities and the OpenCode permission key each one gates.
CAPABILITY_PERMISSION = {"edit": "edit", "bash": "bash", "web": "webfetch"}

#: Neutral capabilities and the OpenCode tools each one enables.
CAPABILITY_TOOLS = {"read": ("read",), "search": ("grep", "glob", "list")}

CAPABILITIES = tuple(sorted({*CAPABILITY_PERMISSION, *CAPABILITY_TOOLS}))

#: Keys that exist only in the neutral source and must not reach a harness layout.
NEUTRAL_ONLY = ("role_model", "capabilities")


class BuildError(Exception):
    """A source component cannot be built."""


@dataclass
class BuildResult:
    harness: str
    out_dir: Path
    files: list[Path] = field(default_factory=list)
    unmapped_aliases: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def relative(self) -> list[str]:
        return sorted(str(p.relative_to(self.out_dir)) for p in self.files)


def dist_dir(harness: str, root: Path | None = None) -> Path:
    base = root if root is not None else Path.cwd()
    return base / "dist" / harness


def build(
    harness: str,
    *,
    collection: Collection | None = None,
    source: Path | None = None,
    out_dir: Path | None = None,
) -> BuildResult:
    """Generate ``harness``'s layout from the neutral source tree.

    ``collection`` supplies the alias table. Without one, every ``role_model`` is left unmapped and
    the built agents inherit their caller's model — which is the same behaviour as an alias with no
    mapping, so a build never fails for want of a manifest.
    """
    if harness not in HARNESSES:
        raise BuildError(f"unknown harness {harness!r}; known: {', '.join(HARNESSES)}")
    src = Path(source) if source is not None else paths.source_tree()
    if not src.is_dir():
        raise BuildError(f"no source tree at {src}")
    target = Path(out_dir) if out_dir is not None else dist_dir(harness)

    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True, exist_ok=True)

    result = BuildResult(harness=harness, out_dir=target)
    used_aliases: list[str] = []

    for kind, directory in (("skill", "skills"), ("agent", "agents"), ("command", "commands")):
        source_kind_dir = src / directory
        if not source_kind_dir.is_dir():
            continue
        for entry in sorted(source_kind_dir.iterdir()):
            common = {"result": result, "collection": collection, "used_aliases": used_aliases}
            if kind == "skill":
                _build_skill(entry, target / directory, **common)
            else:
                _build_flat(kind, entry, target / directory, **common)

    if collection is not None:
        result.unmapped_aliases = collection.unmapped_aliases(harness, used_aliases)
    else:
        result.unmapped_aliases = sorted({a for a in used_aliases if a})
    for alias in result.unmapped_aliases:
        result.warnings.append(
            f"alias {alias!r} has no mapping for {harness}; the built component omits a model and "
            "inherits its caller's"
        )
    return result


def _build_skill(
    entry: Path,
    out_kind_dir: Path,
    *,
    result: BuildResult,
    collection: Collection | None,
    used_aliases: list[str],
) -> None:
    main = entry / "SKILL.md"
    if not entry.is_dir() or not main.is_file():
        return
    doc = read_frontmatter(main)
    meta = _harness_meta(
        "skill",
        doc,
        entry.name,
        harness=result.harness,
        collection=collection,
        used_aliases=used_aliases,
        result=result,
    )
    out_dir = out_kind_dir / entry.name
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / "SKILL.md"
    out_file.write_text(doc.render(meta), encoding="utf-8")
    result.files.append(out_file)

    # Supporting material (references/, scripts/, assets) travels with the skill unchanged.
    for extra in sorted(entry.iterdir()):
        if extra.name == "SKILL.md":
            continue
        destination = out_dir / extra.name
        if extra.is_dir():
            shutil.copytree(extra, destination)
            result.files.extend(sorted(p for p in destination.rglob("*") if p.is_file()))
        else:
            shutil.copy2(extra, destination)
            result.files.append(destination)


def _build_flat(
    kind: str,
    entry: Path,
    out_kind_dir: Path,
    *,
    result: BuildResult,
    collection: Collection | None,
    used_aliases: list[str],
) -> None:
    if not entry.is_file() or entry.suffix != ".md":
        return
    doc = read_frontmatter(entry)
    meta = _harness_meta(
        kind,
        doc,
        entry.stem,
        harness=result.harness,
        collection=collection,
        used_aliases=used_aliases,
        result=result,
    )
    out_kind_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_kind_dir / entry.name
    out_file.write_text(doc.render(meta), encoding="utf-8")
    result.files.append(out_file)


def _harness_meta(
    kind: str,
    doc: Document,
    default_name: str,
    *,
    harness: str,
    collection: Collection | None,
    used_aliases: list[str],
    result: BuildResult,
) -> dict[str, Any]:
    meta = {k: v for k, v in doc.meta.items() if k not in NEUTRAL_ONLY}
    meta.setdefault("name", default_name)
    if not meta.get("description"):
        raise BuildError(f"{doc.path}: `description` is required in neutral frontmatter")

    alias = doc.meta.get("role_model")
    if alias is not None and not isinstance(alias, str):
        raise BuildError(f"{doc.path}: `role_model` must be a string alias")
    if alias:
        used_aliases.append(alias)
    resolved = collection.resolve_alias(harness, alias) if (collection and alias) else None

    capabilities = _capabilities(doc, result)

    if harness == "opencode":
        if kind == "agent":
            meta["mode"] = "subagent"
            meta["permission"] = {
                key: ("allow" if capability in capabilities else "deny")
                for capability, key in sorted(CAPABILITY_PERMISSION.items(), key=lambda kv: kv[1])
            }
            meta["tools"] = {
                tool: capability in capabilities
                for capability, tools in sorted(CAPABILITY_TOOLS.items())
                for tool in tools
            }
        if resolved:
            meta["model"] = resolved
        elif kind == "agent":
            # No model key at all: OpenCode then runs the subagent on its caller's model.
            meta.pop("model", None)
    return meta


def _capabilities(doc: Document, result: BuildResult) -> set[str]:
    declared = doc.meta.get("capabilities", [])
    if isinstance(declared, str):
        declared = [declared]
    if not isinstance(declared, list) or not all(isinstance(c, str) for c in declared):
        raise BuildError(f"{doc.path}: `capabilities` must be an array of strings")
    unknown = sorted(set(declared) - set(CAPABILITIES))
    if unknown:
        result.warnings.append(
            f"{doc.path}: unknown capabilities ignored: {', '.join(unknown)} "
            f"(known: {', '.join(CAPABILITIES)})"
        )
    return set(declared) & set(CAPABILITIES)
