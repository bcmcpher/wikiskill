"""The ``wikiskill`` command line.

Skills, commands and harness hooks all reach wikiskill through this CLI, so its output is written to
be read by a person and its exit codes are meaningful: 0 success, 1 a reported failure, 2 misuse.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__, logtools, paths
from . import collection as collection_mod
from . import install as install_mod
from .build import HARNESSES, BuildError, build, dist_dir
from .collection import Collection, ManifestError, Source
from .frontmatter import FrontmatterError
from .install import SCOPES, InstallError
from .rawlog import RawLogError

OK, FAILED, MISUSE = 0, 1, 2


# --------------------------------------------------------------------------- helpers


def _load(name: str) -> Collection:
    return collection_mod.load(name)


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
    for kind in collection_mod.KINDS:
        of_kind = [c for c in components if c.kind == kind]
        if not of_kind:
            continue
        print(f"  {kind}s ({len(of_kind)}):")
        for component in of_kind:
            mark = "*" if component.name in watched_names else " "
            print(f"    {mark} {component.name}  {component.path}")


# --------------------------------------------------------------------------- collection


def cmd_collection_init(args: argparse.Namespace) -> int:
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
    coll = _load(args.name)
    if args.json:
        print(json.dumps(coll.runtime_config(), indent=2))
        return OK
    print(f"collection {coll.name}  ({coll.manifest_path})")
    for source in coll.sources:
        print(f"  source  {source.path}  [{source.layout}]")
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
    coll = _load(args.name)
    print(f"collection {coll.name}  ({coll.manifest_path})")

    failures = []
    for source in coll.sources:
        if not source.path.is_dir():
            failures.append(f"source directory does not exist: {source.path}")
            print(f"  source  {source.path}  [{source.layout}]  MISSING")
        else:
            print(f"  source  {source.path}  [{source.layout}]  ok")

    discovered = coll.discover()
    watched = coll.watched(discovered)
    print(f"  discovered {len(discovered)} components, {len(watched)} watched (*):")
    _print_components(discovered, {c.name for c in watched})

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


# --------------------------------------------------------------------------- log


def cmd_log_validate(args: argparse.Namespace) -> int:
    report = logtools.validate(args.name, raw_dir=args.raw_dir)
    print(f"raw log {report.raw_dir}")
    print(f"  {report.files} session logs, {report.events} events")
    print(f"  {report.activations} component_activated events")
    print(f"  {len(report.problems)} schema errors")
    for problem in report.problems[: args.limit]:
        print(f"    {problem}")
    if len(report.problems) > args.limit:
        print(f"    ... and {len(report.problems) - args.limit} more")
    for refusal in report.refused:
        print(f"  refused: {refusal}", file=sys.stderr)
    return OK if report.ok else FAILED


def cmd_log_stats(args: argparse.Namespace) -> int:
    try:
        coll: Collection | str = _load(args.name)
    except ManifestError:
        # Stats are useful even when the manifest has drifted; only the watched-path signal is lost.
        coll = args.name
    summary = logtools.stats(coll, raw_dir=args.raw_dir)
    print(f"raw log {summary.raw_dir}")
    print(f"  sessions  {summary.sessions}")
    print(f"  events    {summary.events}")
    print(f"  size      {summary.megabytes:.2f} MiB")
    if summary.days:
        print(f"  days      {summary.days[0]} .. {summary.days[-1]} ({len(summary.days)})")
    for label, counter in (
        ("type", summary.by_type),
        ("model", summary.by_model),
        ("component", summary.by_component),
    ):
        for key, value in counter.most_common():
            print(f"  {label:9} {key}  {value}")
    if summary.reads_without_activation:
        print(
            f"  {len(summary.reads_without_activation)} sessions touched a watched component's "
            "source file without recording an activation:"
        )
        for session in summary.reads_without_activation:
            print(f"    ? {session}")
    for error in summary.errors:
        print(f"  error: {error}", file=sys.stderr)
    return FAILED if summary.errors else OK


def cmd_log_tail(args: argparse.Namespace) -> int:
    try:
        for event in logtools.tail(
            args.name, raw_dir=args.raw_dir, count=args.count, follow=args.follow
        ):
            if args.json:
                print(json.dumps(event, separators=(",", ":")))
            else:
                component = event.get("component")
                if not isinstance(component, dict):
                    component = {}
                label = f"{component.get('kind', '-')}:{component.get('name', '-')}"
                # A hand-edited or truncated line still gets a row: tail is how a broken log is
                # looked at, so it must not be the thing that refuses to read one.
                print(
                    f"{event.get('ts', '-')}  {event.get('type', '-')!s:20} {label:32} "
                    f"{event.get('provider')}/{event.get('model')}"
                )
    except KeyboardInterrupt:
        return OK
    return OK


# --------------------------------------------------------------------------- build / install


def _collection_for(name: str | None) -> Collection | None:
    return _load(name) if name else None


def cmd_build(args: argparse.Namespace) -> int:
    coll = _collection_for(args.collection)
    out = Path(args.out) if args.out else dist_dir(args.harness)
    result = build(args.harness, collection=coll, out_dir=out)
    print(f"built {len(result.files)} files for {args.harness} into {result.out_dir}")
    for relative in result.relative():
        print(f"  {relative}")
    for warning in result.warnings:
        print(f"  warning: {warning}")
    return OK


def cmd_install(args: argparse.Namespace) -> int:
    target = Path(args.target).expanduser() if args.target else None
    if args.uninstall:
        result = install_mod.uninstall(
            args.harness, args.scope, target=target, force=args.force
        )
        print(f"uninstalled from {result.target}")
        for path in result.removed:
            print(f"  removed  {path}")
        for warning in result.warnings:
            print(f"  warning: {warning}")
        print(f"  {len(result.removed)} removed, {len(result.skipped)} left in place")
        return OK

    coll = _collection_for(args.collection)
    result = install_mod.install(args.harness, args.scope, collection=coll, target=target)
    print(f"installed {args.harness} components into {result.target}")
    for path in result.written:
        print(f"  wrote     {path}")
    for path in result.removed:
        print(f"  removed   {path}")
    if not result.changed:
        print("  no changes")
    print(f"  {len(result.unchanged)} unchanged")
    for note in result.notes:
        print(f"  {note}")
    for warning in result.warnings:
        print(f"  warning: {warning}")
    print(f"  record    {result.record}")
    print(f"  wikiskill {install_mod.resolved_cli_path()}")
    return OK


# --------------------------------------------------------------------------- parser


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="wikiskill",
        description="Trace what skills and subagents do with a model, across harnesses.",
    )
    parser.add_argument("--version", action="version", version=f"wikiskill {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    collection_cmd = sub.add_parser(
        "collection", help="declare and check watched collections"
    )
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

    log = sub.add_parser("log", help="inspect the raw event log").add_subparsers(
        dest="subcommand", required=True
    )
    for name, handler, helptext in (
        ("validate", cmd_log_validate, "validate every log against the raw event schema"),
        ("stats", cmd_log_stats, "summarise a collection's raw log"),
        ("tail", cmd_log_tail, "print the most recent events"),
    ):
        node = log.add_parser(name, help=helptext)
        node.add_argument("name", help="collection name")
        node.add_argument(
            "--raw-dir", type=Path, default=None, help="override the raw log location"
        )
        node.set_defaults(func=handler)
    log.choices["validate"].add_argument("--limit", type=int, default=20)
    log.choices["tail"].add_argument("-n", "--count", type=int, default=20)
    log.choices["tail"].add_argument("-f", "--follow", action="store_true")
    log.choices["tail"].add_argument("--json", action="store_true")

    build_cmd = sub.add_parser("build", help="generate a harness layout from the neutral source")
    build_cmd.add_argument("--harness", choices=HARNESSES, required=True)
    build_cmd.add_argument("--collection", default=None, help="manifest supplying the alias table")
    build_cmd.add_argument("--out", default=None, help="output directory (default dist/<harness>)")
    build_cmd.set_defaults(func=cmd_build)

    inst = sub.add_parser("install", help="install built components and the harness logger")
    inst.add_argument("--harness", choices=HARNESSES, required=True)
    inst.add_argument("--scope", choices=SCOPES, required=True)
    inst.add_argument("--collection", default=None)
    inst.add_argument("--target", default=None, help="override the harness config directory")
    inst.add_argument("--uninstall", action="store_true", help="remove exactly what was installed")
    inst.add_argument("--force", action="store_true", help="on uninstall, remove changed files too")
    inst.set_defaults(func=cmd_install)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except (ManifestError, BuildError, InstallError, RawLogError, FrontmatterError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return FAILED
    except FileNotFoundError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return FAILED


if __name__ == "__main__":
    raise SystemExit(main())
