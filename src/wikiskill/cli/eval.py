"""`wikiskill eval`: run a task suite in fresh isolated headless sessions."""

from __future__ import annotations

import argparse
import dataclasses
import os
import sys
from typing import TYPE_CHECKING

from ._common import FAILED, OK, add_collection_argument, collection_for, misuse

if TYPE_CHECKING:
    from ..collection import Collection


def register(sub) -> None:
    from .. import adapters
    from .. import suite as suite_mod
    from ..build import HARNESSES
    from ..runner import opencode as opencode_backend
    from ..runner import run as run_mod

    ev = sub.add_parser("eval", help="run a task suite in fresh isolated headless sessions")
    ev.add_argument("--suite", default=None, help="task suite file (required unless --fill)")
    ev.add_argument(
        "--harness",
        choices=HARNESSES,
        default="opencode",
        help="the harness each unit runs in (default opencode)",
    )
    add_collection_argument(ev, "collection under test (required for ROUTED)")
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
            "endpoint serving the models under test: OpenAI-compatible for OpenCode, e.g. "
            "http://localhost:11434/v1 for Ollama, or Anthropic-compatible for Claude Code, e.g. "
            "http://localhost:11434. Omit it when the harness serves the model itself"
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
        "--probe-timeout",
        type=int,
        default=None,
        metavar="SECONDS",
        help=(
            "how long preflight's tool-call probe may take, model loading included (default 120 "
            "against --base-url, 300 through the harness)"
        ),
    )
    ev.add_argument(
        "--max-output-tokens",
        type=int,
        default=opencode_backend.DEFAULT_MAX_OUTPUT_TOKENS,
        metavar="N",
        help=(
            "tokens one model turn may generate, thinking included, against --base-url (default "
            f"{opencode_backend.DEFAULT_MAX_OUTPUT_TOKENS}). Recorded in run.json"
        ),
    )
    ev.add_argument(
        "--thinking",
        choices=tuple(opencode_backend.THINKING_EFFORT),
        default="default",
        help=(
            "ask the model to think (on) or not (off), against --base-url; default leaves it to "
            "the model, and models differ. Recorded in run.json, and never pooled across settings"
        ),
    )
    ev.add_argument(
        "--repeats",
        type=int,
        default=None,
        metavar="N",
        help=(
            "run every task N times, in place of the suite's repeats. Recorded in run.json, and "
            "not part of the suite hash, so the run pools with runs of the same suite"
        ),
    )
    ev.add_argument(
        "--proposal",
        default=None,
        help=(
            "evaluate this refinement proposal's candidate, from a copy of its source in the run "
            "directory; the source itself is never written"
        ),
    )
    ev.add_argument(
        "--no-seed-cache",
        action="store_true",
        help=(
            "download OpenCode's packages, ripgrep and model catalog into every unit, rather than "
            "copying them from this machine's seed under ~/.cache/wikiskill/opencode-seed/"
        ),
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
        "--retries",
        type=int,
        default=run_mod.DEFAULT_RETRIES,
        metavar="N",
        help=(
            "run a unit again, up to N times, when the harness crashed, could not start or lost "
            f"its session (default {run_mod.DEFAULT_RETRIES}; 0 never). Timeouts and units that "
            "ran, pass or fail, are never rerun"
        ),
    )
    ev.add_argument(
        "--fill",
        default=None,
        metavar="RUN_ID",
        help=(
            "run again only the units of this finished run that have no score (infra_error, "
            "skipped), with its recorded suite, models and options, and write them into it. "
            "Refused if the suite, harness or components changed since"
        ),
    )
    ev.add_argument(
        "--preflight-only",
        action="store_true",
        help="check each model and stop, without running the suite",
    )
    ev.add_argument("--opencode", default="opencode", help="path to the opencode executable")
    ev.add_argument("--claude", default="claude", help="path to the claude executable")
    ev.add_argument(
        "--foreground-agents",
        action="store_true",
        help=(
            "(claude-code) run every subagent in the foreground, even when the model asks for the "
            "background. Recorded in run.json"
        ),
    )
    ev.set_defaults(func=cmd_eval)


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


def _eval_misuse(args: argparse.Namespace, conditions: list[str]) -> str | None:
    """Arguments that cannot describe a run, before anything is loaded or written."""
    from ..runner import base as runner_base
    from ..runner import opencode as opencode_backend

    unknown = [c for c in conditions if c not in runner_base.CONDITIONS]
    if unknown:
        return f"unknown condition(s): {', '.join(unknown)}"
    if args.proposal and not args.collection:
        return "--proposal needs --collection"
    if args.harness == "claude-code":
        ignored = [
            flag
            for flag, given in (
                ("--thinking", args.thinking != "default"),
                (
                    "--max-output-tokens",
                    args.max_output_tokens != opencode_backend.DEFAULT_MAX_OUTPUT_TOKENS,
                ),
                ("--no-seed-cache", args.no_seed_cache),
            )
            if given
        ]
        if ignored:
            return f"{', '.join(ignored)} only apply to --harness opencode"
    elif args.foreground_agents:
        return "--foreground-agents only applies to --harness claude-code"
    if args.thinking != "default" and not args.base_url:
        return (
            "--thinking needs --base-url: a model the harness serves itself keeps the harness's "
            "own settings"
        )
    return None


def cmd_eval(args: argparse.Namespace) -> int:

    if args.retries < 0:
        return misuse("--retries cannot be negative")
    if args.fill:
        return _cmd_fill(args)
    if not args.suite:
        return misuse("--suite is required, unless --fill names a run to continue")
    return _cmd_run(args)


def _cmd_run(args: argparse.Namespace) -> int:
    """`eval --suite`: a new run."""
    from .. import gate as gate_mod
    from .. import report as report_mod
    from .. import suite as suite_mod
    from ..runner import base as runner_base
    from ..runner import preflight as preflight_mod
    from ..runner import run as run_mod

    # The collection first: an adapted fixture names delegated *plugins*, and the collection is what
    # knows which agent each of them provides.
    coll = collection_for(args.collection)
    loaded = suite_mod.load(args.suite, collection=coll, split=args.split)
    for warning in loaded.warnings:
        print(f"  ? {warning}")
    conditions = [c.strip() for c in args.condition.split(",") if c.strip()]
    problem = _eval_misuse(args, conditions) or (
        "--repeats must be at least 1" if args.repeats is not None and args.repeats < 1 else None
    )
    if problem:
        return misuse(problem)

    if args.repeats is not None:
        loaded = dataclasses.replace(
            loaded,
            tasks=tuple(dataclasses.replace(task, repeats=args.repeats) for task in loaded.tasks),
        )

    models = _eval_models(args, coll)
    if not models:
        return misuse(
            "no models to run. Pass --models, or add a [targets] opencode list to the "
            "collection manifest."
        )

    tasks, problem = _eval_tasks(args, loaded)
    # A judge panel that cannot grade the run is refused before a run directory exists.
    problem = problem or _judge_refusal(coll, loaded, models, tasks)
    if problem:
        return misuse(problem)

    run_id = runner_base.new_run_id()
    layout = runner_base.RunLayout.create(coll.name if coll else loaded.name, run_id)
    if args.proposal:
        assert coll is not None, "_eval_misuse refuses --proposal without --collection"
        coll = gate_mod.candidate_collection(coll, args.proposal, layout.root)
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
    backend = _eval_backend(args, coll, endpoint, layout, loaded.root)

    print(
        f"run {run_id}  suite {loaded.name}  {args.harness}  {len(models)} model(s)  "
        f"{', '.join(conditions)}"
    )
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
            proposal=args.proposal,
            retries=args.retries,
        )
    except ValueError as exc:
        return misuse(str(exc))

    report = report_mod.write(layout, run.results, run_mod.load_manifest(layout))
    return _summary(report, run, layout)


def _summary(report: dict, run, layout) -> int:
    """The closing lines of `eval`: outcomes, events, the report, and what did not run."""
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


#: Settings a run recorded, which `--fill` takes from `run.json` and refuses on the command line.
_FILL_REFUSES = (
    ("--suite", lambda a: a.suite is not None),
    ("--models", lambda a: a.models is not None),
    ("--condition", lambda a: a.condition != "off,routed"),
    ("--task", lambda a: a.task is not None),
    ("--repeats", lambda a: a.repeats is not None),
    ("--thinking", lambda a: a.thinking != "default"),
    ("--max-output-tokens", lambda a: a.max_output_tokens != _default_output_cap()),
    ("--no-seed-cache", lambda a: a.no_seed_cache),
    ("--proposal", lambda a: a.proposal is not None),
    ("--workers", lambda a: a.workers != 1),
    ("--preflight-only", lambda a: a.preflight_only),
    ("--foreground-agents", lambda a: a.foreground_agents),
)


def _default_output_cap() -> int:
    from ..runner import opencode as opencode_backend

    return opencode_backend.DEFAULT_MAX_OUTPUT_TOKENS


def _cmd_fill(args: argparse.Namespace) -> int:
    """`eval --fill RUN_ID`: run a finished run's unscored units again, into that run.

    Everything that defines the run comes from its `run.json`; what only locates things on this
    machine (the endpoint's key, the executables, `--collection`) comes from the command line. The
    base URL defaults to the one the run's preflight recorded, and any other is refused.
    """
    from .. import gate as gate_mod
    from .. import report as report_mod
    from ..runner import preflight as preflight_mod
    from ..runner import run as run_mod

    target = _fill_target(args)
    if isinstance(target, str):
        return misuse(target)
    coll, layout, manifest, loaded = target
    if manifest.get("proposal"):
        coll = gate_mod.candidate_collection(coll, manifest["proposal"], layout.root)
    endpoint = (
        preflight_mod.Endpoint(
            base_url=args.base_url,
            api_key=os.environ.get(args.api_key_env) if args.api_key_env else None,
        )
        if args.base_url
        else None
    )
    backend = _eval_backend(args, coll, endpoint, layout, loaded.root)
    problem = run_mod.fill_refusal(manifest, loaded, backend, coll)
    if problem:
        return misuse(f"cannot fill {args.fill}: {problem}")

    todo = run_mod.unfilled(layout.read_results())
    print(f"fill {args.fill}  suite {loaded.name}  {args.harness}  {len(todo)} unit(s) to run")
    print(f"  results  {layout.root}")
    if not todo:
        print("  every unit has a score; nothing to fill")
        return OK
    try:
        run, _filled = run_mod.fill_run(
            loaded,
            backend,
            collection=coll,
            layout=layout,
            manifest=manifest,
            retries=args.retries,
            on_event=lambda line: print(f"  {line}", flush=True),
        )
    except ValueError as exc:
        return misuse(str(exc))
    report = report_mod.write(layout, run.results, run_mod.load_manifest(layout))
    return _summary(report, run, layout)


def _fill_target(args: argparse.Namespace):
    """The run `--fill` names, its manifest and suite, with `args` set from what it recorded.

    Returns ``(collection, layout, manifest, suite)``, or why the fill is refused.
    """
    from .. import paths
    from .. import suite as suite_mod
    from ..runner import base as runner_base
    from ..runner import run as run_mod

    given = [flag for flag, set_ in _FILL_REFUSES if set_(args)]
    if given:
        return f"--fill takes {', '.join(given)} from the run's run.json; drop them"
    if not args.collection:
        return "--fill needs the run's --collection, to find it"
    coll = collection_for(args.collection)
    assert coll is not None
    root = paths.evals_dir(coll.name) / args.fill
    if not root.is_dir():
        return f"no run {args.fill} in {coll.name}"
    layout = runner_base.RunLayout(collection=coll.name, run_id=args.fill, root=root)
    manifest = run_mod.load_manifest(layout)
    problem = run_mod.unfillable(manifest)
    if problem:
        return f"cannot fill {args.fill}: {problem}"

    loaded = suite_mod.load(manifest["suite_path"], collection=coll)
    repeats = manifest.get("repeats") or {}
    loaded = dataclasses.replace(
        loaded,
        tasks=tuple(
            dataclasses.replace(task, repeats=repeats.get(task.id, task.repeats))
            for task in loaded.tasks
        ),
    )
    options = manifest.get("options") or {}
    args.harness = manifest.get("harness") or args.harness
    if options.get("thinking") is not None:
        args.thinking = options["thinking"]
    if options.get("max_output_tokens") is not None:
        args.max_output_tokens = options["max_output_tokens"]
    args.no_seed_cache = options.get("seed_cache") is False
    args.foreground_agents = bool(options.get("foreground_agents"))
    recorded = sorted(
        {
            str(url)
            for result in (manifest.get("preflight") or {}).values()
            if (url := (result.get("details") or {}).get("base_url"))
        }
    )
    if args.base_url and recorded and args.base_url not in recorded:
        return f"{args.fill} ran against {', '.join(recorded)}, not {args.base_url}"
    args.base_url = args.base_url or (recorded[0] if recorded else None)
    return coll, layout, manifest, loaded


def _eval_tasks(args: argparse.Namespace, loaded) -> tuple[list | None, str | None]:
    """The tasks `--task` selects, or None for all of them, and any task the suite lacks."""
    if not args.task:
        return None, None
    wanted = set(args.task)
    tasks = [task for task in loaded.tasks if task.id in wanted]
    missing = sorted(wanted - {task.id for task in tasks})
    if missing:
        return tasks, f"no such task(s) in {loaded.name}: {', '.join(missing)}"
    return tasks, None


def _judge_refusal(coll: Collection | None, loaded, models: list[str], tasks) -> str | None:
    """Why the judge panel cannot grade the selected tasks, or None when it can."""
    from ..runner import run as run_mod
    from ..score import judge as judge_mod

    try:
        run_mod.panel_for(coll, loaded, models, tasks)
    except judge_mod.JudgeError as exc:
        return str(exc)
    return None


def _eval_backend(args: argparse.Namespace, coll: Collection | None, endpoint, layout, root):
    """The backend for `--harness`, configured from the command line."""
    limit = coll.output_limit_bytes if coll else 16 * 1024
    # A run without a collection redacts: that is the safe side.
    scrub = coll.redact if coll else True
    if args.harness == "claude-code":
        from ..runner import claude as claude_backend

        return claude_backend.ClaudeCodeBackend(
            collection=coll,
            endpoint=endpoint,
            layout=layout,
            suite_root=root,
            executable=args.claude,
            min_context=args.min_context,
            probe_timeout=args.probe_timeout,
            output_limit_bytes=limit,
            redact=scrub,
            foreground_agents=args.foreground_agents,
        )
    from ..runner import opencode as opencode_backend

    return opencode_backend.OpenCodeBackend(
        collection=coll,
        endpoint=endpoint,
        layout=layout,
        suite_root=root,
        executable=args.opencode,
        min_context=args.min_context,
        probe_timeout=args.probe_timeout,
        output_limit_bytes=limit,
        redact=scrub,
        max_output_tokens=args.max_output_tokens,
        thinking=args.thinking,
        seed_cache=not args.no_seed_cache,
    )


def _eval_models(args: argparse.Namespace, coll: Collection | None) -> list[str]:
    """Concrete `provider/model` strings, resolving manifest aliases where one is given."""
    requested = list(args.models or [])
    if not requested and coll is not None:
        requested = list(coll.targets.get(args.harness, ()))
    resolved = []
    for name in requested:
        concrete = name if "/" in name else None
        if concrete is None and coll is not None:
            concrete = coll.resolve_alias(args.harness, name)
        if concrete is None:
            print(
                f"warning: {name!r} is not a provider/model and the manifest maps no alias for it",
                file=sys.stderr,
            )
            continue
        resolved.append(concrete)
    return resolved
