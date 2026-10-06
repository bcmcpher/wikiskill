"""The ``wikiskill`` command line.

Skills, commands and harness hooks all reach wikiskill through this CLI, so its output is written to
be read by a person and its exit codes are meaningful: 0 success, 1 a reported failure, 2 misuse.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .. import __version__
from .. import collection as collection_mod
from .. import gate as gate_mod
from .. import graph as graph_mod
from .. import refine as refine_mod
from .. import review as review_mod
from .. import roles as roles_mod
from .. import wiki as wiki_mod
from ..collection import Collection
from ..errors import WikiskillError
from . import (
    build,
    collection,
    compare,
    corrections,
    eval,
    hook,
    install,
    leaderboard,
    log,
    note,
    review,
    suite,
)
from ._common import FAILED, MISUSE, OK
from .hook import cmd_guard, cmd_hook

__all__ = ["FAILED", "MISUSE", "OK", "build_parser", "cmd_guard", "cmd_hook", "main"]

# --------------------------------------------------------------------------- helpers


def _load(name: str) -> Collection:
    return collection_mod.load(name)


# --------------------------------------------------------------------------- parser


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

    eval.register(sub)
    build.register(sub)
    install.register(sub)

    hook.register(sub)
    note.register(sub)
    corrections.register(sub)
    compare.register(sub)
    leaderboard.register(sub)
    review.register(sub)
    for add_parser in (
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
