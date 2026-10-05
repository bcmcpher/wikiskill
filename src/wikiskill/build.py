"""Build wikiskill's single-source components into a harness layout.

The source tree under ``harness/source/`` is the only place these components are authored. Every
harness layout is generated from it, so a fix to a skill reaches every harness by rebuilding. Build
output is owned by this module: it is cleared and rewritten on each run, and is git-ignored.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import __version__, names, paths
from .collection import Collection, Source
from .errors import WikiskillError
from .frontmatter import Document, repaired_warning
from .frontmatter import read as read_frontmatter

HARNESSES = ("opencode", "claude-code")

#: Neutral capabilities and the OpenCode permission key each one gates.
CAPABILITY_PERMISSION = {"edit": "edit", "bash": "bash", "web": "webfetch"}

#: Neutral capabilities and the OpenCode tools each one enables.
CAPABILITY_TOOLS = {"read": ("read",), "search": ("grep", "glob", "list")}

CAPABILITIES = tuple(sorted({*CAPABILITY_PERMISSION, *CAPABILITY_TOOLS}))

#: Neutral capabilities and the Claude Code tools each one grants, in the order `tools:` lists them.
CLAUDE_CAPABILITY_TOOLS = {
    "read": ("Read",),
    "search": ("Grep", "Glob"),
    "bash": ("Bash",),
    "edit": ("Edit", "Write"),
    "web": ("WebFetch",),
}

#: Model values Claude Code understands itself. Unmapped, they pass through rather than drop.
CLAUDE_NATIVE_MODELS = frozenset({"haiku", "sonnet", "opus", "inherit"})

#: The hook events the Claude Code logger listens to, each run as `wikiskill hook <event>`.
CLAUDE_HOOK_EVENTS = (
    "SessionStart",
    "UserPromptSubmit",
    "PostToolUse",
    "PostToolUseFailure",
    "SubagentStop",
    "Stop",
    "SessionEnd",
)

#: Claude Code tool names, as a claude-plugin agent's `tools:` lists them, and the neutral
#: capability each needs. A plugin written for Claude Code declares tools rather than capabilities,
#: and without this translation it would build for OpenCode with everything denied.
CLAUDE_TOOL_CAPABILITY = {
    "Read": "read",
    "Grep": "search",
    "Glob": "search",
    "LS": "search",
    "Bash": "bash",
    "Edit": "edit",
    "Write": "edit",
    "MultiEdit": "edit",
    "NotebookEdit": "edit",
    "WebFetch": "web",
    "WebSearch": "web",
}

#: Keys that exist only in the neutral source and must not reach a harness layout.
NEUTRAL_ONLY = ("role_model", "capabilities")

#: Written into every build output, and required before one is cleared.
BUILD_MARKER = ".wikiskill-build"

#: Where a claude-plugin's own directory is mirrored in a built layout, one subdirectory per plugin.
PLUGINS_DIR = "plugins"

#: Never mirrored: version control and installed dependencies are not plugin content.
MIRROR_IGNORE = (".git", "node_modules", "__pycache__", ".venv")

#: `${CLAUDE_PLUGIN_ROOT}` and its unbraced form, which Claude Code also expands.
_PLUGIN_ROOT_VAR = re.compile(r"\$\{CLAUDE_PLUGIN_ROOT\}|\$CLAUDE_PLUGIN_ROOT\b")
_SKILL_DIR_VAR = re.compile(r"\$\{CLAUDE_SKILL_DIR\}|\$CLAUDE_SKILL_DIR\b")

#: A path cited through either variable, as `collection check` reads it back out of a component.
_CITED_PATH = re.compile(
    r"\$\{?(?P<var>CLAUDE_PLUGIN_ROOT|CLAUDE_SKILL_DIR)\}?(?P<path>/[A-Za-z0-9_./-]*)"
)


class BuildError(WikiskillError):
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


@dataclass
class CollectionBuildResult(BuildResult):
    #: ``plugin/name`` (or a bare name, for an opencode-layout source) → the flat name it builds to.
    mapping: dict[str, str] = field(default_factory=dict)


def dist_dir(harness: str, root: Path | None = None) -> Path:
    base = root if root is not None else Path.cwd()
    return base / "dist" / harness


def build(
    harness: str,
    *,
    collection: Collection | None = None,
    source: Path | None = None,
    out_dir: Path | None = None,
    strip_models: bool = False,
    plugin_name: str | None = "wikiskill",
    hooks: bool | None = None,
) -> BuildResult:
    """Generate ``harness``'s layout from the neutral source tree.

    ``collection`` supplies the alias table. Without one, every ``role_model`` is left unmapped and
    the built agents inherit their caller's model — which is the same behaviour as an alias with no
    mapping, so a build never fails for want of a manifest.

    For Claude Code the layout is a plugin: ``plugin_name`` names its manifest (None writes none),
    and ``hooks`` adds the logger's hooks — by default only to wikiskill's own tree, since an
    evaluation reads its stream instead and must not log twice.
    """
    if harness not in HARNESSES:
        raise BuildError(f"unknown harness {harness!r}; known: {', '.join(HARNESSES)}")
    src = Path(source) if source is not None else paths.source_tree()
    if not src.is_dir():
        raise BuildError(f"no source tree at {src}")
    target = Path(out_dir) if out_dir is not None else dist_dir(harness)

    _clear(target)
    target.mkdir(parents=True, exist_ok=True)
    (target / BUILD_MARKER).write_text(
        f"generated by wikiskill build --harness {harness}; safe to delete\n", encoding="utf-8"
    )

    result = BuildResult(harness=harness, out_dir=target)
    used_aliases: list[str] = []
    if harness == "claude-code":
        _plugin_files(target, result, plugin_name, hooks if hooks is not None else source is None)

    skills_dir = src / "skills"
    skill_names = {e.name for e in skills_dir.iterdir()} if skills_dir.is_dir() else set()
    for kind, directory in (("skill", "skills"), ("agent", "agents"), ("command", "commands")):
        source_kind_dir = src / directory
        if not source_kind_dir.is_dir():
            continue
        for entry in sorted(source_kind_dir.iterdir()):
            if harness == "claude-code" and kind == "command" and entry.stem in skill_names:
                # Claude Code names a plugin's commands and skills alike, and the command shadowed
                # the skill: `Skill(<plugin>:<name>)` loaded the command's text. The skill is
                # invocable as `/<plugin>:<name>` itself, so the command is the one to drop.
                result.warnings.append(
                    f"command {entry.stem!r} not built for claude-code: a skill has the same name, "
                    "and Claude Code would load the command in its place"
                )
                continue
            common = {
                "result": result,
                "collection": collection,
                "used_aliases": used_aliases,
                "strip_models": strip_models,
            }
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


def build_collection(
    harness: str,
    collection: Collection,
    out_dir: Path,
    *,
    strip_models: bool = False,
    installed_at: Path | None = None,
) -> CollectionBuildResult:
    """Build a collection's own sources into one harness layout.

    A claude-plugin source is one component root per plugin, but a harness layout is flat: two
    plugins that each provide a `status` skill would build to the same path, and the second would
    silently replace the first. Every root is therefore built into staging first, and the build
    fails on a collision before anything reaches ``out_dir``.

    ``strip_models`` removes every model pin, so a subagent runs on its caller's model. An
    evaluation needs that: a doer pinned to another model would mix two models in one row.

    A plugin's own files — shared `references/`, `scripts/` — are mirrored to `plugins/<plugin>/`,
    and `${CLAUDE_PLUGIN_ROOT}` in every built file becomes that mirror's absolute path. Claude Code
    expands the variable itself; OpenCode would show it to the model unexpanded. ``installed_at`` is
    where ``out_dir``'s contents will finally live, when that is somewhere else.
    """
    if harness not in HARNESSES:
        raise BuildError(f"unknown harness {harness!r}; known: {', '.join(HARNESSES)}")
    result = CollectionBuildResult(harness=harness, out_dir=out_dir)
    owners: dict[tuple[str, str], str] = {}
    unmapped: set[str] = set()

    with tempfile.TemporaryDirectory(prefix="wikiskill-build-") as tmp:
        staged_roots = []
        for index, source in enumerate(collection.sources):
            for offset, root in enumerate(component_roots(source)):
                staged = Path(tmp) / f"{index}-{offset}"
                built = build(
                    harness,
                    collection=collection,
                    source=root,
                    out_dir=staged,
                    strip_models=strip_models,
                    # One manifest for the whole collection, written below, not one per root.
                    plugin_name=None,
                    hooks=False,
                )
                plugin = root.name if source.layout == "claude-plugin" else None
                if plugin:
                    previous = owners.get(("plugins", plugin))
                    if previous is not None:
                        raise BuildError(
                            f"two sources both provide a plugin named {plugin!r} ({previous} and "
                            f"{root}); their files would share plugins/{plugin}"
                        )
                    owners[("plugins", plugin)] = str(root)
                    _mirror_plugin(root, staged / PLUGINS_DIR / plugin)
                    _expand_plugin_root(
                        staged, (installed_at or out_dir).resolve() / PLUGINS_DIR / plugin
                    )
                for kind_dir, flat in _flat_names(staged):
                    qualified = names.qualify(plugin, flat)
                    previous = owners.get((kind_dir, flat))
                    if previous is not None:
                        raise BuildError(
                            f"`{previous}` and `{qualified}` both build to {kind_dir}/{flat} for "
                            f"{harness}; a harness layout is flat, so one would replace the other"
                        )
                    owners[(kind_dir, flat)] = qualified
                    result.mapping[qualified] = flat
                unmapped.update(built.unmapped_aliases)
                result.warnings.extend(w for w in built.warnings if "has no mapping" not in w)
                staged_roots.append(staged)

        _clear(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / BUILD_MARKER).write_text(
            f"generated by wikiskill build --harness {harness} --collection {collection.name}; "
            "safe to delete\n",
            encoding="utf-8",
        )
        for staged in staged_roots:
            for path in sorted(staged.rglob("*")):
                if not path.is_file() or path.name == BUILD_MARKER:
                    continue
                destination = out_dir / path.relative_to(staged)
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(path, destination)
                result.files.append(destination)
        if harness == "claude-code":
            result.files.append(write_plugin_manifest(out_dir, collection.name))

    result.unmapped_aliases = sorted(unmapped)
    for alias in result.unmapped_aliases:
        result.warnings.append(
            f"alias {alias!r} has no mapping for {harness}; the built component omits a model and "
            "inherits its caller's"
        )
    return result


def _plugin_files(target: Path, result: BuildResult, name: str | None, hooks: bool) -> None:
    if name:
        result.files.append(write_plugin_manifest(target, name))
    if hooks:
        result.files.append(write_hooks(target))


def write_plugin_manifest(target: Path, name: str) -> Path:
    """`.claude-plugin/plugin.json`, which is what makes a directory a Claude Code plugin."""
    path = target / ".claude-plugin" / "plugin.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    manifest = {
        "name": name,
        "version": __version__,
        "description": f"Built by wikiskill {__version__} from its single-source tree",
    }
    path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return path


def write_hooks(target: Path, command: str | None = None) -> Path:
    """`hooks/hooks.json`: every logged event runs `wikiskill hook <event>` by absolute path.

    A hook runs in a non-interactive shell with a minimal PATH, where a bare `wikiskill` is not
    found, so the command is resolved now, at build or install time. The hook reads its event from
    stdin, never writes to stdout and always exits 0, so it cannot block or steer the session.
    """
    cli = command or paths.cli_command()
    entry = {
        event: [
            {
                **({"matcher": "*"} if "ToolUse" in event else {}),
                "hooks": [{"type": "command", "command": f"{cli} hook {event}", "timeout": 10}],
            }
        ]
        for event in CLAUDE_HOOK_EVENTS
    }
    path = target / "hooks" / "hooks.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"hooks": entry}, indent=2) + "\n", encoding="utf-8")
    return path


def component_roots(source: Source) -> list[Path]:
    """The directories that hold `skills/`, `agents/` and `commands/` for one source.

    An OpenCode-layout source is one such directory. A Claude-plugin source is one per selected
    plugin, which is why a collection of plugins cannot simply be built in one pass.
    """
    if source.layout != "claude-plugin":
        return [source.path]
    return [
        child
        for child in source.plugin_dirs()
        if any((child / d).is_dir() for d in ("skills", "agents", "commands"))
    ]


def _mirror_plugin(root: Path, destination: Path) -> None:
    """Copy a plugin's directory as it stands, so any `${CLAUDE_PLUGIN_ROOT}/...` finds its file."""
    shutil.copytree(root, destination, ignore=shutil.ignore_patterns(*MIRROR_IGNORE))


def _expand_plugin_root(staged: Path, plugin_root: Path) -> None:
    """Expand the plugin path variables Claude Code would, in every text file of one built plugin.

    `${CLAUDE_PLUGIN_ROOT}` becomes the plugin's mirror. `${CLAUDE_SKILL_DIR}` becomes the skill's
    own built directory, and is left alone outside one, where Claude Code has no value for it.
    """
    installed = plugin_root.parent.parent
    for path in sorted(staged.rglob("*")):
        if not path.is_file() or path.name == BUILD_MARKER:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        if "CLAUDE_PLUGIN_ROOT" not in text and "CLAUDE_SKILL_DIR" not in text:
            continue
        expanded = _PLUGIN_ROOT_VAR.sub(str(plugin_root), text)
        relative = path.relative_to(staged).parts
        if len(relative) > 2 and relative[0] == "skills":
            expanded = _SKILL_DIR_VAR.sub(str(installed / "skills" / relative[1]), expanded)
        if expanded != text:
            path.write_text(expanded, encoding="utf-8")


def unresolved_plugin_paths(main: Path, plugin_dir: Path, skill_dir: Path | None) -> list[str]:
    """Paths a component cites through a plugin variable that name no file in its plugin.

    Claude Code expands `${CLAUDE_PLUGIN_ROOT}` to the plugin's directory and `${CLAUDE_SKILL_DIR}`
    to the skill's, so a path written as if one were the other finds nothing in either harness. One
    that climbs out of the plugin is reported too, since an installed plugin has no neighbours.
    """
    try:
        text = main.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []
    problems = []
    for match in _CITED_PATH.finditer(text):
        variable, relative = match["var"], match["path"].rstrip(".,;:")
        base = plugin_dir if variable == "CLAUDE_PLUGIN_ROOT" else skill_dir
        if base is None or not relative.strip("/"):
            continue
        cited = Path(os.path.normpath(base / relative.lstrip("/")))
        if not cited.is_relative_to(plugin_dir):
            problems.append(f"{main}: ${{{variable}}}{relative} leaves the plugin")
        elif not cited.exists():
            problems.append(f"{main}: ${{{variable}}}{relative} names no file")
    return sorted(set(problems))


def _flat_names(staged: Path) -> list[tuple[str, str]]:
    """Each built component as ``(kind directory, flat name)``."""
    names = []
    for kind_dir in ("skills", "agents", "commands"):
        directory = staged / kind_dir
        if not directory.is_dir():
            continue
        for entry in sorted(directory.iterdir()):
            names.append((kind_dir, entry.name if entry.is_dir() else entry.stem))
    return names


def _clear(target: Path) -> None:
    """Empty a build directory, refusing anything that is not one.

    ``--out`` is a plausible place to point at a real harness config directory, which is where
    ``install`` puts these same files. Rebuilding is destructive, so a directory is only cleared
    when it is empty or carries the marker a previous build left.
    """
    if not target.exists():
        return
    if not target.is_dir():
        raise BuildError(f"{target} is not a directory")
    entries = [e for e in target.iterdir() if e.name != BUILD_MARKER]
    if entries and not (target / BUILD_MARKER).is_file():
        raise BuildError(
            f"{target} is not a build directory and would be erased: it holds "
            f"{len(entries)} entr{'y' if len(entries) == 1 else 'ies'} and no {BUILD_MARKER} "
            "marker. Point --out at an empty or previously built directory."
        )
    shutil.rmtree(target)


def _build_skill(
    entry: Path,
    out_kind_dir: Path,
    *,
    result: BuildResult,
    collection: Collection | None,
    used_aliases: list[str],
    strip_models: bool = False,
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
        strip_models=strip_models,
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
    strip_models: bool = False,
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
        strip_models=strip_models,
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
    strip_models: bool = False,
) -> dict[str, Any]:
    if doc.repaired:
        result.warnings.append(repaired_warning(doc))
    meta = {k: v for k, v in doc.meta.items() if k not in NEUTRAL_ONLY}
    meta.setdefault("name", default_name)
    if not meta.get("description"):
        raise BuildError(f"{doc.path}: `description` is required in neutral frontmatter")

    alias, concrete = _model_alias(doc)
    resolved = collection.resolve_alias(harness, alias) if (collection and alias) else None
    if harness == "claude-code" and not resolved and alias in CLAUDE_NATIVE_MODELS:
        # `haiku` means something to Claude Code without any alias table.
        resolved = alias
    if alias and not concrete and not resolved:
        used_aliases.append(alias)
    resolved = resolved or concrete

    capabilities = _capabilities(doc, result)
    # A Claude `tools:` list has been read into capabilities; OpenCode's `tools` is a map this
    # build writes itself, so the source's form must not reach the output.
    if not isinstance(meta.get("tools"), dict):
        meta.pop("tools", None)

    if harness == "opencode":
        _opencode_agent(meta, kind, capabilities)
    elif harness == "claude-code":
        _claude_agent(meta, kind, capabilities)
    if resolved and not strip_models:
        meta["model"] = resolved
    else:
        # No model key at all: the harness then runs the component on its caller's model.
        meta.pop("model", None)
    return meta


def _opencode_agent(meta: dict[str, Any], kind: str, capabilities: set[str]) -> None:
    if kind != "agent":
        return
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


def _claude_agent(meta: dict[str, Any], kind: str, capabilities: set[str]) -> None:
    # OpenCode's keys, from a source written for it, mean nothing to Claude Code.
    meta.pop("mode", None)
    meta.pop("permission", None)
    if isinstance(meta.get("tools"), dict):
        meta.pop("tools")
    if kind != "agent":
        return
    # Deny by default: a tool no capability grants is simply not listed.
    meta["tools"] = ", ".join(
        tool
        for capability, tools in CLAUDE_CAPABILITY_TOOLS.items()
        if capability in capabilities
        for tool in tools
    )


def _model_alias(doc: Document) -> tuple[str | None, str | None]:
    """The alias a component declares, and a concrete model it names outright.

    ``role_model`` is the neutral source's key. A claude-plugin component says ``model:`` instead —
    ``haiku``, ``sonnet`` — which is an alias too, resolved through the same table. A ``model:``
    that is already ``provider/model`` is concrete, and passes through when no alias maps it.
    """
    alias = doc.meta.get("role_model")
    if alias is not None:
        if not isinstance(alias, str):
            raise BuildError(f"{doc.path}: `role_model` must be a string alias")
        return alias or None, None
    model = doc.meta.get("model")
    if model is None:
        return None, None
    if not isinstance(model, str):
        raise BuildError(f"{doc.path}: `model` must be a string")
    if "/" in model:
        return model, model
    return model or None, None


def _capabilities(doc: Document, result: BuildResult) -> set[str]:
    if "capabilities" not in doc.meta and "tools" in doc.meta:
        return _capabilities_from_tools(doc, result)
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


def _capabilities_from_tools(doc: Document, result: BuildResult) -> set[str]:
    """Neutral capabilities from a Claude Code ``tools:`` declaration, string or list."""
    declared = doc.meta.get("tools")
    if isinstance(declared, str):
        names = [part.strip() for part in declared.split(",")]
    elif isinstance(declared, list) and all(isinstance(t, str) for t in declared):
        names = [t.strip() for t in declared]
    elif isinstance(declared, dict):
        # Already an OpenCode tool map: nothing to translate, and no capability to infer.
        return set()
    else:
        raise BuildError(f"{doc.path}: `tools` must be a comma-separated string or an array")
    names = [n for n in names if n]
    # `mcp__server__tool` names grant nothing a neutral capability describes.
    unknown = sorted(n for n in names if n not in CLAUDE_TOOL_CAPABILITY and "__" not in n)
    if unknown:
        result.warnings.append(
            f"{doc.path}: tools with no OpenCode capability ignored: {', '.join(unknown)}"
        )
    return {CLAUDE_TOOL_CAPABILITY[n] for n in names if n in CLAUDE_TOOL_CAPABILITY}
