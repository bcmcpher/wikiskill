"""The ``wikiskill`` command line.

Skills, commands and harness hooks all reach wikiskill through this CLI, so its output is written to
be read by a person and its exit codes are meaningful: 0 success, 1 a reported failure, 2 misuse.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

from .. import __version__, adapters, paths
from .. import collection as collection_mod
from .. import compare as compare_mod
from .. import corrections as corrections_mod
from .. import gate as gate_mod
from .. import graph as graph_mod
from .. import guard as guard_mod
from .. import hooks as hooks_mod
from .. import install as install_mod
from .. import leaderboard as leaderboard_mod
from .. import refine as refine_mod
from .. import report as report_mod
from .. import review as review_mod
from .. import roles as roles_mod
from .. import suite as suite_mod
from .. import wiki as wiki_mod
from ..build import (
    HARNESSES,
    BuildError,
    build,
    build_collection,
    dist_dir,
)
from ..collection import Collection, ManifestError
from ..errors import WikiskillError
from ..install import SCOPES
from ..rawlog import RawLogError
from ..runner import base as runner_base
from ..runner import claude as claude_backend
from ..runner import opencode as opencode_backend
from ..runner import preflight as preflight_mod
from ..runner import run as run_mod
from . import collection, log, suite
from ._common import FAILED, MISUSE, OK

DEFAULT_MAX_OUTPUT_TOKENS = opencode_backend.DEFAULT_MAX_OUTPUT_TOKENS


# --------------------------------------------------------------------------- helpers


def _load(name: str) -> Collection:
    return collection_mod.load(name)


# --------------------------------------------------------------------------- hook


def cmd_hook(args: argparse.Namespace) -> int:
    """Claude Code runs this per hook event. Silent and always 0, whatever happens inside."""
    return hooks_mod.run(args.event or "", sys.stdin.read())


def cmd_guard(_args: argparse.Namespace) -> int:
    """An evaluation's `PreToolUse` hook: prints a deny decision for a refused call."""
    return guard_mod.main()


# --------------------------------------------------------------------------- note


def _note_collections(name: str | None) -> list[Collection]:
    if name:
        return [_load(name)]
    found = []
    for manifest in sorted(paths.collections_dir().glob("*.toml")):
        try:
            found.append(_load(manifest.stem))
        except ManifestError:
            continue
    return found


def cmd_note(args: argparse.Namespace) -> int:
    text = " ".join(args.text)
    collections = _note_collections(args.collection)
    if not collections:
        print("error: no collection manifests to attach a note to", file=sys.stderr)
        return FAILED
    # Without --collection, the note goes to every collection logging the session, as the logger
    # writes every other event to each of them.
    written, problems = [], []
    for coll in collections:
        try:
            note = corrections_mod.write_note(
                coll, text, session=args.session, component=args.component
            )
        except corrections_mod.NoteError as exc:
            problems.append(f"{coll.name}: {exc}")
            continue
        written.append((coll, note))
    if not written:
        for problem in problems:
            print(f"error: {problem}", file=sys.stderr)
        return FAILED
    for coll, note in written:
        component = note.event.get("component") or {}
        label = f"{component['kind']}:{component['name']}" if component else "no component"
        print(f"note  {coll.name}  {note.event['session_id']}  {label}")
        for warning in note.warnings:
            print(f"  warning: {warning}", file=sys.stderr)
    return OK


def cmd_corrections_scan(args: argparse.Namespace) -> int:
    """Record edits to files components wrote. `--quiet` is how the loggers run it: in the
    background, at session start, where nothing may be printed and nothing may fail."""
    found, problems = [], []
    for coll in _note_collections(args.collection):
        try:
            events = corrections_mod.scan(paths.raw_dir(coll.name), redact_diffs=coll.redact)
        except (OSError, RawLogError) as exc:
            problems.append(f"{coll.name}: {exc}")
            if args.quiet:
                _log_scan_error(coll, exc)
            continue
        found.extend((coll, event) for event in events)
    if args.quiet:
        return OK
    for coll, event in found:
        component = event["component"]
        print(
            f"output_edit  {coll.name}  {component['kind']}:{component['name']}  "
            f"{event['payload']['path']}"
        )
    for problem in problems:
        print(f"error: {problem}", file=sys.stderr)
    if not found and not problems:
        print("no edits to produced files")
    return FAILED if problems else OK


def _log_scan_error(coll: Collection, exc: Exception) -> None:
    with contextlib.suppress(OSError):
        log = paths.logger_error_log(coll.name)
        log.parent.mkdir(parents=True, exist_ok=True)
        with log.open("a", encoding="utf-8") as handle:
            handle.write(f"{datetime.now(UTC).isoformat()} corrections scan: {exc}\n")


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


def _eval_misuse(args: argparse.Namespace, conditions: list[str]) -> str | None:
    """Arguments that cannot describe a run, before anything is loaded or written."""
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
                ("--max-output-tokens", args.max_output_tokens != DEFAULT_MAX_OUTPUT_TOKENS),
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
    # The collection first: an adapted fixture names delegated *plugins*, and the collection is what
    # knows which agent each of them provides.
    coll = _collection_for(args.collection)
    loaded = suite_mod.load(args.suite, collection=coll, split=args.split)
    for warning in loaded.warnings:
        print(f"  ? {warning}")
    conditions = [c.strip() for c in args.condition.split(",") if c.strip()]
    misuse = _eval_misuse(args, conditions)
    if misuse:
        print(f"error: {misuse}", file=sys.stderr)
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


def _eval_backend(args: argparse.Namespace, coll: Collection | None, endpoint, layout, root):
    """The backend for `--harness`, configured from the command line."""
    limit = coll.output_limit_bytes if coll else 16 * 1024
    if args.harness == "claude-code":
        return claude_backend.ClaudeCodeBackend(
            collection=coll,
            endpoint=endpoint,
            layout=layout,
            suite_root=root,
            executable=args.claude,
            min_context=args.min_context,
            probe_timeout=args.probe_timeout,
            output_limit_bytes=limit,
            foreground_agents=args.foreground_agents,
        )
    return opencode_backend.OpenCodeBackend(
        collection=coll,
        endpoint=endpoint,
        layout=layout,
        suite_root=root,
        executable=args.opencode,
        min_context=args.min_context,
        probe_timeout=args.probe_timeout,
        output_limit_bytes=limit,
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


# --------------------------------------------------------------------------- build / install


def _collection_for(name: str | None) -> Collection | None:
    return _load(name) if name else None


def cmd_build(args: argparse.Namespace) -> int:
    coll = _collection_for(args.collection)
    out = Path(args.out) if args.out else dist_dir(args.harness)
    if coll is None:
        result = build(args.harness, out_dir=out)
    else:
        # The collection's own sources, not wikiskill's: this is what an evaluation installs.
        try:
            result = build_collection(args.harness, coll, out)
        except BuildError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return FAILED
    print(f"built {len(result.files)} files for {args.harness} into {result.out_dir}")
    mapping = getattr(result, "mapping", {})
    if mapping:
        print("  components:")
        for qualified, flat in sorted(mapping.items()):
            print(f"    {qualified} -> {flat}")
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


def cmd_compare(args: argparse.Namespace) -> int:
    a = compare_mod.load_run(args.collection, args.run_a)
    b = compare_mod.load_run(args.collection, args.run_b)
    comparison = compare_mod.compare(a, b, component=args.component)
    out = compare_mod.output_dir(args.collection, a, b)
    md, js = compare_mod.write(comparison, out)
    print(compare_mod.render(comparison))
    print(f"wrote {md}")
    print(f"wrote {js}")
    if args.record:
        if not args.proposal:
            print("error: --record needs --proposal <id>", file=sys.stderr)
            return FAILED
        replayed = gate_mod.replay(args.collection, args.proposal, a.root, b.root)
        print(f"replayed {args.proposal}: recommendation {replayed.recommendation}")
        target = gate_mod.decide(args.collection, args.proposal, args.record, note=args.note)
        print(f"recorded {args.record} for {args.proposal} in {target}")
    return OK


def cmd_leaderboard(args: argparse.Namespace) -> int:
    runs = []
    for run in args.run:
        if not Path(run).is_dir() and not args.collection:
            print(f"error: {run} is not a directory; pass a path, or --collection", file=sys.stderr)
            return MISUSE
        runs.append(compare_mod.load_run(args.collection or "", run))
    board = leaderboard_mod.pool(runs)
    if args.out:
        out = Path(args.out)
    else:
        collection = args.collection or runs[0].manifest.get("collection") or board.suite or "runs"
        out = paths.evals_dir(collection) / "leaderboard" / leaderboard_mod.output_name(runs)
    md, js = leaderboard_mod.write(board, out)
    print(leaderboard_mod.render(board))
    print(f"wrote {md}")
    print(f"wrote {js}")
    return OK


def _sampling(args: argparse.Namespace) -> dict:
    """The sampling options `review` and `sample` share."""
    return {
        "budget": args.budget,
        "signals": args.signals,
        "clean": args.clean,
        "resample": args.resample,
    }


def cmd_sample(args: argparse.Namespace) -> int:
    coll = _load(args.collection)
    runs = [compare_mod.load_run(coll.name, run) for run in args.run] if args.run else None
    try:
        found = review_mod.digest(coll, args.component, runs=runs, **_sampling(args))
    except review_mod.NothingToReview as exc:
        print(exc)
        return OK
    sample_id, directory = review_mod.save_sample(coll, found)
    print(f"sample {sample_id}")
    print(f"  prompt        {directory / 'prompt.md'}")
    print(f"  instructions  {directory / 'instructions.md'}")
    print(
        f"  evidence      {len(found.evidence)} shown, {found.omitted} waiting, "
        f"{len(found.text)} of {found.budget} characters"
    )
    print(
        f"  apply with    wikiskill review {args.component} --collection {coll.name} "
        f"--sample {sample_id} --reply-file <reply.json>"
    )
    return OK


def cmd_review(args: argparse.Namespace) -> int:
    coll = _load(args.collection)
    runs = [compare_mod.load_run(coll.name, run) for run in args.run] if args.run else None
    if args.sample and not args.reply_file:
        print("error: --sample needs --reply-file", file=sys.stderr)
        return MISUSE
    try:
        sample = review_mod.load_sample(coll, args.sample) if args.sample else None
        if sample and sample.component != args.component:
            raise review_mod.ReviewError(
                f"sample {args.sample} is of {sample.component}, not {args.component}"
            )
        if args.dry_run:
            found = sample or review_mod.digest(coll, args.component, runs=runs, **_sampling(args))
            print(found.text)
            print(
                f"--- {len(found.text)} characters, {len(found.evidence)} pieces of evidence, "
                f"{found.omitted} omitted, runs: {', '.join(found.runs) or 'none'}"
            )
            return OK
        if args.reply_file:
            replies = iter([Path(args.reply_file).read_text(encoding="utf-8")])
            ask = lambda _messages: next(replies)  # noqa: E731
            maintainer, retries = f"reply file {args.reply_file}", 0
        else:
            ask, maintainer = roles_mod.role_asker(coll, "maintainer")
            retries = args.retries
        outcome = review_mod.review(
            coll,
            args.component,
            ask=ask,
            maintainer=maintainer,
            runs=runs,
            retries=retries,
            sample=sample,
            **_sampling(args),
        )
    except review_mod.NothingToReview as exc:
        print(exc)
        return OK
    return _report_review(args.component, coll.name, outcome)


def _report_review(component: str, collection: str, outcome) -> int:
    if outcome.applied is None:
        print(
            f"no pattern written: the reply failed validation after {outcome.attempts} "
            f"attempt(s); the failure is in {wiki_mod.wiki_root(collection) / wiki_mod.LOG}"
        )
        for problem in outcome.problems:
            print(f"  - {problem}")
        return FAILED
    applied = outcome.applied
    print(f"review of {component} applied after {outcome.attempts} attempt(s)")
    print(f"  created  {', '.join(applied.created) or 'none'}")
    print(f"  updated  {', '.join(applied.updated) or 'none'}")
    if applied.superseded:
        print(f"  retired  {', '.join(applied.superseded)}")
    note = "" if applied.committed else " (not committed)"
    print(f"  wiki     {wiki_mod.wiki_root(collection)}{note}")
    for warning in applied.warnings:
        print(f"  warning: {warning}")
    return OK


def cmd_refine(args: argparse.Namespace) -> int:
    coll = _load(args.collection)
    if args.prompt and not args.reply_file:
        print("error: --prompt needs --reply-file", file=sys.stderr)
        return MISUSE
    found = (
        refine_mod.load_prompt(coll, args.component, args.prompt)
        if args.prompt
        else refine_mod.context(coll, args.component, budget=args.budget)
    )
    if args.dry_run or args.prepare:
        return _prepare_prompt(args, coll, found)
    if args.reply_file:
        replies = iter([Path(args.reply_file).read_text(encoding="utf-8")])
        ask = lambda _messages: next(replies)  # noqa: E731
        proposer, retries = f"reply file {args.reply_file}", 0
    else:
        ask, proposer = roles_mod.role_asker(coll, "proposer")
        retries = args.retries
    proposal = refine_mod.refine(
        coll,
        args.component,
        ask=ask,
        proposer=proposer,
        retries=retries,
        found=found,
        allow_overlap=args.allow_overlap,
    )
    if proposal.action == "failed":
        print(f"no proposal: the reply failed validation after {proposal.attempts} attempt(s)")
        for problem in proposal.problems:
            print(f"  - {problem}")
        return FAILED
    if proposal.action == "no_action":
        print(f"no_action for {args.component}: {proposal.reason}")
        return OK
    directory = proposal.directory
    assert directory is not None, "a patch proposal is always written to a directory"
    print(f"proposal {directory.name} for {args.component}: {directory}")
    print(f"  patterns  {', '.join(proposal.patterns)}")
    print(f"  why       {proposal.reason}")
    print(f"  read      {directory / 'preview.md'}")
    print("  nothing has been applied")
    return OK


def _prepare_prompt(args: argparse.Namespace, coll: Collection, found) -> int:
    """Print the proposer prompt, or persist it for a proposer run elsewhere."""
    if args.dry_run:
        print(found.prompt)
        return OK
    if not found.patterns:
        print(f"no_action for {args.component}: the wiki holds no pattern for it")
        return OK
    prompt_id, directory = refine_mod.save_prompt(coll, found)
    print(f"prompt {prompt_id}")
    print(f"  prompt        {directory / 'prompt.md'}")
    print(f"  instructions  {directory / 'instructions.md'}")
    print(f"  evidence      {len(found.evidence.evidence)} shown")
    print(
        f"  apply with    wikiskill refine {args.component} --collection {coll.name} "
        f"--prompt {prompt_id} --reply-file <reply.json>"
    )
    return OK


def _add_refine_parser(sub) -> None:
    ref = sub.add_parser("refine", help="propose one patch to one component; never applies it")
    ref.add_argument("component", help="e.g. datalad/datalad-doer")
    ref.add_argument("--collection", required=True)
    ref.add_argument("--retries", type=int, default=review_mod.DEFAULT_RETRIES)
    ref.add_argument(
        "--budget", type=int, default=None, help="characters of evidence in the prompt"
    )
    ref.add_argument("--dry-run", action="store_true", help="print the prompt and stop")
    ref.add_argument(
        "--prepare",
        action="store_true",
        help="persist the prompt for a proposer run elsewhere, e.g. in-harness, and stop",
    )
    ref.add_argument(
        "--prompt", default=None, help="the --prepare id (or directory) the --reply-file answers"
    )
    ref.add_argument(
        "--reply-file", default=None, help="validate a proposer reply written elsewhere"
    )
    ref.add_argument(
        "--allow-overlap",
        action="store_true",
        help="accept text the leakage check matched; recorded with the proposal",
    )
    ref.set_defaults(func=cmd_refine)


def cmd_proposal_list(args: argparse.Namespace) -> int:
    found = gate_mod.proposals(args.collection)
    if not found:
        print(f"no proposals in {args.collection}")
    for meta in found:
        replay = meta.get("replay") or {}
        recommendation = f"  recommends {replay['recommendation']}" if replay else ""
        print(f"{meta['id']}  {meta.get('status', '?'):9}  {meta['component']}{recommendation}")
    return OK


def cmd_proposal_show(args: argparse.Namespace) -> int:
    directory = gate_mod.directory(args.collection, args.id)
    print((directory / "preview.md").read_text(encoding="utf-8"))
    if (directory / "replay.md").is_file():
        print((directory / "replay.md").read_text(encoding="utf-8"))
    return OK


def cmd_proposal_apply(args: argparse.Namespace) -> int:
    done = gate_mod.apply(args.collection, args.id, branch=args.branch)
    if args.branch:
        print(f"committed {args.id} on branch {done}; you are still on the branch you were on")
    else:
        print(f"nothing written. To apply {args.id} yourself:\n  {done}")
    return OK


def cmd_proposal_replay(args: argparse.Namespace) -> int:
    result = gate_mod.replay(
        args.collection, args.id, args.baseline, args.candidate, tolerance=args.tolerance
    )
    print(gate_mod.render(result))
    print(f"wrote {gate_mod.directory(args.collection, args.id) / 'replay.md'}")
    return OK


def cmd_proposal_decide(args: argparse.Namespace) -> int:
    target = gate_mod.decide(args.collection, args.id, args.decision, note=args.note)
    print(f"{args.id}: {gate_mod.DECISIONS[args.decision]}, recorded in {target}")
    return OK


def _add_proposal_parser(sub) -> None:
    prop = sub.add_parser("proposal", help="list, show, apply, replay and decide proposals")
    actions = prop.add_subparsers(dest="action", required=True)
    listing = actions.add_parser("list", help="every proposal, its state and recommendation")
    listing.set_defaults(func=cmd_proposal_list)
    show = actions.add_parser("show", help="print a proposal's preview and replay")
    show.add_argument("id", help="e.g. p-001")
    show.set_defaults(func=cmd_proposal_show)
    put = actions.add_parser("apply", help="say how to apply a proposal; write only with --branch")
    put.add_argument("id", help="e.g. p-001")
    put.add_argument(
        "--branch",
        action="store_true",
        help="commit it on a new branch wikiskill/<component>/<id> of the source repository",
    )
    put.set_defaults(func=cmd_proposal_apply)
    rep = actions.add_parser("replay", help="compare a baseline and a candidate run, recommend")
    rep.add_argument("id", help="e.g. p-001")
    rep.add_argument("baseline", help="a run at the proposal's source_hash")
    rep.add_argument("candidate", help="a run with `wikiskill eval --proposal <id>`")
    rep.add_argument(
        "--tolerance",
        type=float,
        default=gate_mod.DEFAULT_TOLERANCE,
        help="how far one task's pass rate may fall on one model (default 1/3)",
    )
    rep.set_defaults(func=cmd_proposal_replay)
    dec = actions.add_parser("decide", help="record the decision in skill-impact.md")
    dec.add_argument("id", help="e.g. p-001")
    dec.add_argument("decision", choices=tuple(gate_mod.DECISIONS))
    dec.add_argument("--note", default="", help="why")
    dec.set_defaults(func=cmd_proposal_decide)
    for action in (listing, show, put, rep, dec):
        action.add_argument("--collection", required=True)


def _stored_graph(collection: str) -> graph_mod.Graph:
    found = graph_mod.load(collection)
    if found is None:
        raise wiki_mod.WikiError(
            f"{collection} has no graph yet; run `wikiskill graph build --collection {collection}`"
        )
    return found


def cmd_graph_build(args: argparse.Namespace) -> int:
    found = graph_mod.build(_load(args.collection), args.run or None)
    target = graph_mod.write(found)
    print(graph_mod.render(found))
    print(f"\nwrote {target}")
    return OK


def cmd_graph_show(args: argparse.Namespace) -> int:
    found = _stored_graph(args.collection)
    if args.json:
        print(json.dumps(found.as_dict(), indent=2))
    else:
        print(graph_mod.render(found))
    return OK


def cmd_graph_neighbours(args: argparse.Namespace) -> int:
    found = _stored_graph(args.collection)
    neighbours = found.neighbours(args.component, min_conflict=args.min_conflict)
    print(graph_mod.render_neighbours(args.component, neighbours))
    return OK


def _add_graph_parser(sub) -> None:
    graph_cmd = sub.add_parser("graph", help="build and read the collection's relation graph")
    actions = graph_cmd.add_subparsers(dest="action", required=True)
    build_graph = actions.add_parser(
        "build", help="rebuild graph.json from the sources and eval runs, and commit it"
    )
    build_graph.add_argument(
        "--run",
        action="append",
        default=None,
        metavar="RUN",
        help="read only this run (repeatable; default every run of the collection)",
    )
    build_graph.set_defaults(func=cmd_graph_build)
    show = actions.add_parser("show", help="print the stored graph")
    show.add_argument("--json", action="store_true")
    show.set_defaults(func=cmd_graph_show)
    near = actions.add_parser("neighbours", help="a component's depth-1 neighbours")
    near.add_argument("component")
    near.add_argument(
        "--min-conflict",
        type=float,
        default=graph_mod.MIN_CONFLICT,
        help="smallest confusion rate that makes a neighbour (default 0.05)",
    )
    near.set_defaults(func=cmd_graph_neighbours)
    for action in (build_graph, show, near):
        action.add_argument("--collection", required=True)


def _add_review_parser(sub) -> None:
    rev = sub.add_parser("review", help="distil one component's evidence into wiki patterns")
    _add_sampling_arguments(rev)
    rev.add_argument("--retries", type=int, default=review_mod.DEFAULT_RETRIES)
    rev.add_argument("--dry-run", action="store_true", help="print the prompt and stop")
    rev.add_argument(
        "--reply-file",
        default=None,
        help="validate and apply a maintainer reply written elsewhere, e.g. in-harness",
    )
    rev.add_argument(
        "--sample",
        default=None,
        help="the `wikiskill sample` id (or directory) the --reply-file answers",
    )
    rev.set_defaults(func=cmd_review)

    sam = sub.add_parser(
        "sample", help="take and keep a review sample, for a maintainer that runs elsewhere"
    )
    _add_sampling_arguments(sam)
    sam.set_defaults(func=cmd_sample)


def _add_sampling_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("component", help="e.g. datalad/datalad-doer")
    parser.add_argument("--collection", required=True)
    parser.add_argument(
        "--run", action="append", default=None, help="only this run (default: every run of it)"
    )
    parser.add_argument(
        "--budget",
        type=int,
        default=None,
        help=(
            f"prompt characters (default {review_mod.DEFAULT_BUDGET}, less for a maintainer "
            "whose `context_tokens` is under 64k)"
        ),
    )
    parser.add_argument(
        "--signals",
        type=int,
        default=review_mod.DEFAULT_SIGNALS,
        help="most pieces of evidence with a correction or failure signal",
    )
    parser.add_argument(
        "--clean",
        type=int,
        default=review_mod.DEFAULT_CLEAN,
        help="most pieces of evidence with no signal",
    )
    parser.add_argument(
        "--resample", action="store_true", help="include evidence earlier reviews were shown"
    )


def _add_hook_parser(sub) -> None:
    hook = sub.add_parser(
        "hook", help="(Claude Code) log one hook event read from stdin; always exits 0, silently"
    )
    hook.add_argument("event", nargs="?", default="", help="e.g. PostToolUse")
    hook.set_defaults(func=cmd_hook)
    guard = sub.add_parser(
        "guard",
        help="(evaluation, Claude Code) refuse a tool call a task denies; reads a PreToolUse event",
    )
    guard.set_defaults(func=cmd_guard)


def _add_note_parser(sub) -> None:
    note = sub.add_parser(
        "note", help="record an explicit note on what a skill or agent got wrong, in its session"
    )
    note.add_argument("text", nargs="+", help="the note, as you would say it")
    note.add_argument(
        "--component",
        default=None,
        help="the component it is about, e.g. preregister or agent:datalad-doer "
        "(default: the session's last activated)",
    )
    note.add_argument(
        "--session",
        default=None,
        help="the session it is about (default: the most recent logged one in this directory)",
    )
    note.add_argument(
        "--collection", default=None, help="only this collection (default: every one logging it)"
    )
    note.set_defaults(func=cmd_note)


def _add_corrections_parser(sub) -> None:
    corr = sub.add_parser("corrections", help="find correction signals outside a session")
    corr_sub = corr.add_subparsers(dest="corrections_command", required=True)
    scan = corr_sub.add_parser(
        "scan", help="record edits made to files a watched component wrote, since it wrote them"
    )
    scan.add_argument(
        "--collection", default=None, help="only this collection (default: every one)"
    )
    scan.add_argument(
        "--quiet", action="store_true", help="print nothing and always succeed (for the loggers)"
    )
    scan.set_defaults(func=cmd_corrections_scan)


def _add_compare_parser(sub) -> None:
    cmp = sub.add_parser(
        "compare", help="compare two runs of one suite across versions of a component"
    )
    cmp.add_argument("run_a", help="the earlier run: an id under the collection's evals, or a path")
    cmp.add_argument("run_b", help="the later run")
    cmp.add_argument("--collection", required=True)
    cmp.add_argument(
        "--component", default=None, help="the component under test (default: inferred)"
    )
    cmp.add_argument(
        "--record",
        choices=("accept", "reject"),
        default=None,
        help=(
            "record these runs as the proposal's replay and this decision in the wiki's "
            "skill-impact.md; nothing is applied or reverted"
        ),
    )
    cmp.add_argument("--proposal", default=None, help="the proposal id the decision is about")
    cmp.add_argument("--note", default="", help="the reviewer's note for --record")
    cmp.set_defaults(func=cmd_compare)


def _add_leaderboard_parser(sub) -> None:
    board = sub.add_parser(
        "leaderboard", help="pool runs of one suite, from any machines, per model and condition"
    )
    board.add_argument(
        "run", nargs="+", help="a run directory, or a run id under --collection's evals"
    )
    board.add_argument("--collection", default=None, help="where to find runs given by id")
    board.add_argument(
        "--out", default=None, help="output directory (default: under the collection's evals)"
    )
    board.set_defaults(func=cmd_leaderboard)


def _add_eval_parser(sub) -> None:
    ev = sub.add_parser("eval", help="run a task suite in fresh isolated headless sessions")
    ev.add_argument("--suite", required=True, help="task suite file")
    ev.add_argument(
        "--harness",
        choices=HARNESSES,
        default="opencode",
        help="the harness each unit runs in (default opencode)",
    )
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
        default=DEFAULT_MAX_OUTPUT_TOKENS,
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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="wikiskill",
        description="Trace what skills and subagents do with a model, across harnesses.",
    )
    parser.add_argument("--version", action="version", version=f"wikiskill {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    collection.register(sub)
    log.register(sub)
    suite.register(sub)

    _add_eval_parser(sub)

    build_cmd = sub.add_parser("build", help="generate a harness layout from the neutral source")
    build_cmd.add_argument("--harness", choices=HARNESSES, required=True)
    build_cmd.add_argument(
        "--collection",
        default=None,
        help="build this collection's own sources, with its alias table, instead of wikiskill's",
    )
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

    for add_parser in (
        _add_hook_parser,
        _add_note_parser,
        _add_corrections_parser,
        _add_compare_parser,
        _add_leaderboard_parser,
        _add_review_parser,
        _add_refine_parser,
        _add_proposal_parser,
        _add_graph_parser,
    ):
        add_parser(sub)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except (WikiskillError, FileNotFoundError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return FAILED


if __name__ == "__main__":
    raise SystemExit(main())
