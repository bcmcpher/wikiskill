"""The ``wikiskill`` command line.

Skills, commands and harness hooks all reach wikiskill through this CLI, so its output is written to
be read by a person and its exit codes are meaningful: 0 success, 1 a reported failure, 2 misuse.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from pathlib import Path

from . import __version__, adapters, logtools, paths
from . import collection as collection_mod
from . import install as install_mod
from . import report as report_mod
from . import suite as suite_mod
from .build import HARNESSES, BuildError, build, dist_dir
from .collection import Collection, ManifestError, Source
from .frontmatter import FrontmatterError
from .install import SCOPES, InstallError
from .rawlog import RawLogError
from .runner import base as runner_base
from .runner import opencode as opencode_backend
from .runner import preflight as preflight_mod
from .runner import run as run_mod
from .runner.base import RunnerError
from .suite import SuiteError

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


# --------------------------------------------------------------------------- suite


def cmd_suite_check(args: argparse.Namespace) -> int:
    failed = 0
    for raw in args.file:
        path = Path(raw)
        try:
            loaded = suite_mod.load(path)
        except SuiteError as exc:
            failed += 1
            print(f"suite {exc.path or path}  FAILED")
            for problem in exc.problems:
                print(f"  ! {problem}")
            continue
        splits = Counter(task.split for task in loaded.tasks)
        spread = ", ".join(f"{name} {splits[name]}" for name in suite_mod.SPLITS if splits[name])
        print(f"suite {loaded.name}  ({loaded.path})")
        print(f"  {len(loaded.tasks)} tasks  [{spread}]")
        for task in loaded.tasks:
            route = ", ".join(task.expect.names()) or "-"
            print(
                f"    {task.id:32} x{task.repeats}  route {route}  "
                f"{len(task.verifiers)} verifiers{'  rubric' if task.rubric else ''}"
            )
        for warning in loaded.warnings:
            print(f"  ? {warning}")
        print("  ok" + (f", {len(loaded.warnings)} to look at" if loaded.warnings else ""))
    if failed:
        print(f"\n{failed} of {len(args.file)} suites failed", file=sys.stderr)
    return FAILED if failed else OK


# --------------------------------------------------------------------------- eval


def _report_preflight(backend, models: list[str], layout) -> int:
    """Check every model and say what it would cost the run, without running anything.

    Worth its own mode because the answer is what decides whether a suite is worth starting at all,
    and because on a harness-served model the check itself spends tokens.
    """
    checks = {model: backend.preflight(model) for model in models}
    for model, checked in checks.items():
        print(f"\n{model}: {'ok' if checked.ok else 'unusable'}")
        for key in ("via", "models_listed", "probe_tools", "context_tokens", "context_source"):
            if key in checked.details:
                print(f"    {key}: {checked.details[key]}")
        for problem in checked.problems:
            print(f"  - {problem}")
    layout.write_manifest(
        {
            "run_id": layout.run_id,
            "preflight_only": True,
            "preflight": {model: checked.as_dict() for model, checked in checks.items()},
        }
    )
    return OK if all(checked.ok for checked in checks.values()) else 1


def cmd_eval(args: argparse.Namespace) -> int:
    # The collection first: an adapted fixture names delegated *plugins*, and the collection is what
    # knows which agent each of them provides.
    coll = _collection_for(args.collection)
    loaded = suite_mod.load(args.suite, collection=coll, split=args.split)
    for warning in loaded.warnings:
        print(f"  ? {warning}")
    conditions = [c.strip() for c in args.condition.split(",") if c.strip()]
    unknown = [c for c in conditions if c not in runner_base.CONDITIONS]
    if unknown:
        print(f"error: unknown condition(s): {', '.join(unknown)}", file=sys.stderr)
        return MISUSE

    models = _eval_models(args, coll)
    if not models:
        print(
            "error: no models to run. Pass --models, or add a [targets] opencode list to the "
            "collection manifest.",
            file=sys.stderr,
        )
        return MISUSE

    tasks = None
    if args.task:
        wanted = set(args.task)
        tasks = [task for task in loaded.tasks if task.id in wanted]
        missing = sorted(wanted - {task.id for task in tasks})
        if missing:
            print(f"error: no such task(s) in {loaded.name}: {', '.join(missing)}", file=sys.stderr)
            return MISUSE

    run_id = runner_base.new_run_id()
    layout = runner_base.RunLayout.create(coll.name if coll else loaded.name, run_id)
    # No --base-url means the harness resolves the model itself, credential included, so there is
    # no endpoint for wikiskill to address and preflight goes through the harness instead.
    endpoint = (
        preflight_mod.Endpoint(
            base_url=args.base_url,
            api_key=os.environ.get(args.api_key_env) if args.api_key_env else None,
        )
        if args.base_url
        else None
    )
    backend = opencode_backend.OpenCodeBackend(
        collection=coll,
        endpoint=endpoint,
        layout=layout,
        suite_root=loaded.root,
        executable=args.opencode,
        min_context=args.min_context,
        output_limit_bytes=coll.output_limit_bytes if coll else 16 * 1024,
    )

    print(f"run {run_id}  suite {loaded.name}  {len(models)} model(s)  {', '.join(conditions)}")
    print(f"  results  {layout.root}")

    if args.preflight_only:
        return _report_preflight(backend, models, layout)
    try:
        run = run_mod.run_suite(
            loaded,
            backend,
            collection=coll,
            models=models,
            conditions=conditions,
            tasks=tasks,
            layout=layout,
            run_id=run_id,
            workers=args.workers,
            on_event=lambda line: print(f"  {line}", flush=True),
        )
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return MISUSE

    report = report_mod.write(layout, run.results, run_mod.load_manifest(layout))
    print()
    for outcome, count in sorted((report.get("outcomes") or {}).items()):
        print(f"  {outcome:18} {count}")
    print(f"  events written     {run.events_written}")
    print(f"  report             {layout.report_md}")
    unfinished = report.get("not_run") or []
    if unfinished:
        print(f"  not run            {len(unfinished)} (listed in the report)")
    scored_any = any(row.get("repeats") for row in report.get("rows") or [])
    return OK if scored_any else FAILED


def _eval_models(args: argparse.Namespace, coll: Collection | None) -> list[str]:
    """Concrete `provider/model` strings, resolving manifest aliases where one is given."""
    requested = list(args.models or [])
    if not requested and coll is not None:
        requested = list(coll.targets.get("opencode", ()))
    resolved = []
    for name in requested:
        concrete = name if "/" in name else None
        if concrete is None and coll is not None:
            concrete = coll.resolve_alias("opencode", name)
        if concrete is None:
            print(
                f"warning: {name!r} is not a provider/model and the manifest maps no alias for it",
                file=sys.stderr,
            )
            continue
        resolved.append(concrete)
    return resolved


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
        result = install_mod.uninstall(args.harness, args.scope, target=target, force=args.force)
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


def _add_eval_parser(sub) -> None:
    ev = sub.add_parser("eval", help="run a task suite in fresh isolated headless sessions")
    ev.add_argument("--suite", required=True, help="task suite file")
    ev.add_argument(
        "--collection", default=None, help="collection under test (required for ROUTED)"
    )
    ev.add_argument(
        "--models",
        nargs="+",
        default=None,
        metavar="MODEL",
        help="provider/model strings, or aliases from the manifest (default: its opencode targets)",
    )
    ev.add_argument(
        "--condition",
        default="off,routed",
        help="comma-separated: off, routed, injected (default off,routed)",
    )
    ev.add_argument("--task", action="append", default=None, help="run only this task id")
    ev.add_argument(
        "--split",
        default=None,
        choices=suite_mod.SPLITS,
        help=(
            "split to place tasks in when the fixture declares none, as data-science-harness's "
            f"`bench/tasks` do not (default {adapters.DEFAULT_SPLIT})"
        ),
    )
    ev.add_argument(
        "--base-url",
        default=None,
        metavar="URL",
        help=(
            "OpenAI-compatible endpoint serving the models under test, e.g. "
            "http://localhost:11434/v1 for Ollama. Omit it when the harness serves the model "
            "itself, and preflight probes through the harness instead"
        ),
    )
    ev.add_argument("--api-key-env", default=None, help="environment variable holding its API key")
    ev.add_argument(
        "--min-context",
        type=int,
        default=16384,
        help="minimum context window preflight accepts; 0 skips the check",
    )
    ev.add_argument(
        "--workers",
        type=int,
        default=1,
        metavar="N",
        help=(
            "units to run at once against one endpoint (default 1, which is what Ollama serves). "
            "Models still run one after another"
        ),
    )
    ev.add_argument(
        "--preflight-only",
        action="store_true",
        help="check each model and stop, without running the suite",
    )
    ev.add_argument("--opencode", default="opencode", help="path to the opencode executable")
    ev.set_defaults(func=cmd_eval)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="wikiskill",
        description="Trace what skills and subagents do with a model, across harnesses.",
    )
    parser.add_argument("--version", action="version", version=f"wikiskill {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

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

    suite_cmd = sub.add_parser("suite", help="validate task suites").add_subparsers(
        dest="subcommand", required=True
    )
    suite_check = suite_cmd.add_parser(
        "check", help="validate a suite and flag prompts that name their own expected route"
    )
    suite_check.add_argument("file", nargs="+", help="task suite file")
    suite_check.set_defaults(func=cmd_suite_check)

    _add_eval_parser(sub)

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
    except (
        ManifestError,
        BuildError,
        InstallError,
        RawLogError,
        FrontmatterError,
        SuiteError,
        RunnerError,
    ) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return FAILED
    except FileNotFoundError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return FAILED


if __name__ == "__main__":
    raise SystemExit(main())
