"""`wikiskill proposal`: list, show, apply, replay and decide proposals."""

from __future__ import annotations

import argparse

from ._common import OK, add_collection_argument


def register(sub) -> None:
    from .. import gate as gate_mod

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
        add_collection_argument(action, required=True)


def cmd_proposal_list(args: argparse.Namespace) -> int:
    from .. import gate as gate_mod

    found = gate_mod.proposals(args.collection)
    if not found:
        print(f"no proposals in {args.collection}")
    for meta in found:
        replay = meta.get("replay") or {}
        recommendation = f"  recommends {replay['recommendation']}" if replay else ""
        print(f"{meta['id']}  {meta.get('status', '?'):9}  {meta['component']}{recommendation}")
    return OK


def cmd_proposal_show(args: argparse.Namespace) -> int:
    from .. import gate as gate_mod

    directory = gate_mod.directory(args.collection, args.id)
    print((directory / "preview.md").read_text(encoding="utf-8"))
    if (directory / "replay.md").is_file():
        print((directory / "replay.md").read_text(encoding="utf-8"))
    return OK


def cmd_proposal_apply(args: argparse.Namespace) -> int:
    from .. import gate as gate_mod

    done = gate_mod.apply(args.collection, args.id, branch=args.branch)
    if args.branch:
        print(f"committed {args.id} on branch {done}; you are still on the branch you were on")
    else:
        print(f"nothing written. To apply {args.id} yourself:\n  {done}")
    return OK


def cmd_proposal_replay(args: argparse.Namespace) -> int:
    from .. import gate as gate_mod

    result = gate_mod.replay(
        args.collection, args.id, args.baseline, args.candidate, tolerance=args.tolerance
    )
    print(gate_mod.render(result))
    print(f"wrote {gate_mod.directory(args.collection, args.id) / 'replay.md'}")
    return OK


def cmd_proposal_decide(args: argparse.Namespace) -> int:
    from .. import gate as gate_mod

    target = gate_mod.decide(args.collection, args.id, args.decision, note=args.note)
    print(f"{args.id}: {gate_mod.DECISIONS[args.decision]}, recorded in {target}")
    return OK
