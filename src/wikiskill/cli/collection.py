"""`wikiskill collection`: declare and check watched collections."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from ._common import FAILED, OK, load


def register(sub) -> None:
    from .. import collection as collection_mod

    collection_cmd = sub.add_parser("collection", help="declare and check watched collections")
    coll = collection_cmd.add_subparsers(dest="subcommand", required=True)

    init = coll.add_parser("init", help="write a manifest for a source directory")
    init.add_argument("name")
    init.add_argument("--source", action="append", required=True, metavar="DIR")
    init.add_argument("--layout", choices=collection_mod.LAYOUTS, default=None)
    init.add_argument("--force", action="store_true", help="overwrite an existing manifest")
    init.set_defaults(func=cmd_collection_init)

    show = coll.add_parser("show", help="print a manifest as resolved")
    show.add_argument("name")
    show.add_argument("--json", action="store_true", help="print the logger's runtime view")
    show.set_defaults(func=cmd_collection_show)

    check = coll.add_parser("check", help="resolve sources and the watch list")
    check.add_argument("name")
    check.add_argument(
        "--sync", action="store_true", help="also publish the logger's runtime configuration"
    )
    check.set_defaults(func=cmd_collection_check)


# --------------------------------------------------------------------------- helpers


def _detect_layout(directory: Path) -> str:
    """Guess a source layout: components at the top level, or one level down per plugin."""
    if any((directory / d).is_dir() for d in ("skills", "skill", "commands", "command")):
        return "opencode"
    if directory.is_dir():
        for child in directory.iterdir():
            if child.is_dir() and (
                (child / ".claude-plugin").is_dir()
                or any((child / d).is_dir() for d in ("skills", "agents", "commands"))
            ):
                return "claude-plugin"
    return "opencode"


def _print_components(components, watched_names: set[str]) -> None:
    from .. import collection as collection_mod

    for kind in collection_mod.KINDS:
        of_kind = [c for c in components if c.kind == kind]
        if not of_kind:
            continue
        print(f"  {kind}s ({len(of_kind)}):")
        for component in of_kind:
            mark = "*" if component.name in watched_names else " "
            print(f"    {mark} {component.name}  {component.path}")


def _check_frontmatter(components) -> list[str]:
    """Print frontmatter read only leniently or not at all, and return the failures.

    Build reads every component's frontmatter, not only the watched ones, so a file it cannot read
    would stop ROUTED for the whole collection. Check says so rather than a run, mid-way.
    """
    from ..frontmatter import FrontmatterError, repaired_warning
    from ..frontmatter import read as read_frontmatter

    unreadable: list[str] = []
    repaired: list[str] = []
    for component in components:
        try:
            doc = read_frontmatter(component.path)
        except (FrontmatterError, OSError, UnicodeDecodeError) as exc:
            unreadable.append(str(exc))
            continue
        if doc.repaired:
            repaired.append(repaired_warning(doc))
    if repaired:
        print("  frontmatter read leniently:")
        for warning in repaired:
            print(f"    ~ {warning}")
    if unreadable:
        print("  unreadable frontmatter:")
        for problem in unreadable:
            print(f"    ! {problem}")
        return [f"{len(unreadable)} components have frontmatter build cannot read"]
    return []


def _check_plugin_paths(components) -> None:
    """Print plugin-variable paths that resolve to nothing: a warning, as Claude Code misses too."""
    from ..build import unresolved_plugin_paths

    problems: list[str] = []
    for component in components:
        if component.source.layout != "claude-plugin":
            continue
        plugin_dir = component.source.path / component.name.split("/", 1)[0]
        skill_dir = component.path.parent if component.kind == "skill" else None
        problems.extend(unresolved_plugin_paths(component.path, plugin_dir, skill_dir))
    if problems:
        print(f"  plugin paths that resolve to nothing ({len(problems)}):")
        for problem in problems:
            print(f"    ~ {problem}")


# --------------------------------------------------------------------------- handlers


def cmd_collection_init(args: argparse.Namespace) -> int:
    from .. import collection as collection_mod
    from .. import paths
    from ..collection import Source

    sources = []
    for raw in args.source:
        path = Path(raw).expanduser()
        if not path.is_dir():
            print(f"error: no such source directory: {path}", file=sys.stderr)
            return FAILED
        layout = args.layout or _detect_layout(path)
        sources.append(Source(path=path.resolve(), layout=layout))

    discovered = [c for source in sources for c in collection_mod.discover(source)]
    discovered.sort(key=lambda c: (c.kind, c.name))
    if not discovered:
        print(
            f"error: found no skills, agents or commands under "
            f"{', '.join(str(s.path) for s in sources)}",
            file=sys.stderr,
        )
        return FAILED

    target = paths.manifest_path(args.name)
    if target.exists() and not args.force:
        print(f"error: {target} already exists; pass --force to overwrite", file=sys.stderr)
        return FAILED
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        collection_mod.render_manifest(args.name, sources, discovered), encoding="utf-8"
    )

    print(f"wrote {target}")
    print(f"discovered {len(discovered)} components:")
    _print_components(discovered, set())
    print()
    print(f"Edit the watch list, then run: wikiskill collection check {args.name}")
    return OK


def cmd_collection_show(args: argparse.Namespace) -> int:
    from .. import collection as collection_mod
    from .. import paths

    coll = load(args.name)
    if args.json:
        print(json.dumps(coll.runtime_config(), indent=2))
        return OK
    print(f"collection {coll.name}  ({coll.manifest_path})")
    for source in coll.sources:
        selected = f"  plugins {', '.join(source.plugins)}" if source.plugins else ""
        print(f"  source  {source.path}  [{source.layout}]{selected}")
    for kind in collection_mod.KINDS:
        patterns = coll.watch.get(kind, ())
        if patterns:
            print(f"  watch {kind}s  {', '.join(patterns)}")
    for role_name in collection_mod.ROLES:
        role = coll.roles.get(role_name)
        if role:
            endpoint = role.base_url or "harness default"
            print(f"  role {role_name}  {role.model}  @ {endpoint}")
    for harness, table in sorted(coll.aliases.items()):
        for alias, resolved in sorted(table.items()):
            print(f"  alias {harness}  {alias} -> {resolved}")
    for harness, models in sorted(coll.targets.items()):
        print(f"  targets {harness}  {', '.join(models)}")
    print(f"  raw log  {paths.raw_dir(coll.name)}")
    print(
        f"  logging  buffer {coll.buffer_size} events, output limit "
        f"{coll.output_limit_bytes} bytes, redact {'on' if coll.redact else 'off'}"
    )
    return OK


def cmd_collection_check(args: argparse.Namespace) -> int:
    from .. import collection as collection_mod

    coll = load(args.name)
    print(f"collection {coll.name}  ({coll.manifest_path})")

    failures = []
    for source in coll.sources:
        if not source.path.is_dir():
            failures.append(f"source directory does not exist: {source.path}")
            print(f"  source  {source.path}  [{source.layout}]  MISSING")
        else:
            print(f"  source  {source.path}  [{source.layout}]  ok")

    missing_plugins = coll.unresolved_plugins()
    if missing_plugins:
        print("  unresolved plugins:")
        for entry in missing_plugins:
            print(f"    ! {entry}")
        failures.append(f"{len(missing_plugins)} selected plugins do not exist")

    discovered = coll.discover()
    watched = coll.watched(discovered)
    print(f"  discovered {len(discovered)} components, {len(watched)} watched (*):")
    _print_components(discovered, {c.name for c in watched})
    failures.extend(_check_frontmatter(discovered))
    _check_plugin_paths(discovered)

    unresolved = coll.unresolved(discovered)
    if unresolved:
        print("  unresolved watch-list entries:")
        for entry in unresolved:
            print(f"    ! {entry}")
        failures.append(f"{len(unresolved)} watch-list entries match nothing")

    if args.sync:
        runtime, published, sync_problems = collection_mod.publish_runtime_config(prefer=coll)
        names = ", ".join(c.name for c in published)
        print(f"  logger configuration written to {runtime} ({names})")
        for problem in sync_problems:
            print(f"  warning: {problem}")

    if failures:
        print()
        for failure in failures:
            print(f"error: {failure}", file=sys.stderr)
        return FAILED
    print("  ok")
    return OK
