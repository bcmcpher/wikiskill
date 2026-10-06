"""`wikiskill diff`: what changed between two versions of a component, in text and in results."""

from __future__ import annotations

import argparse

from ._common import OK, add_collection_argument, load, misuse


def register(sub) -> None:
    dif = sub.add_parser(
        "diff", help="compare two versions of a component: its text and its evaluated results"
    )
    dif.add_argument("component", help="the component, as the collection names it")
    dif.add_argument(
        "versions",
        nargs="*",
        metavar="version",
        help=(
            "two versions: `current`, a source_hash prefix of 7+ hex digits, `p-NNN` (a "
            "proposal's candidate), `p-NNN^` (what it was made from) or `run:<id>`"
        ),
    )
    add_collection_argument(dif, required=True)
    dif.add_argument("--run-a", default=None, help="the run of version A to compare")
    dif.add_argument("--run-b", default=None, help="the run of version B to compare")
    dif.add_argument(
        "--list", action="store_true", help="list the known versions of the component instead"
    )
    dif.set_defaults(func=cmd_diff)


def cmd_diff(args: argparse.Namespace) -> int:
    from .. import diff as diff_mod

    if args.list:
        if args.versions or args.run_a or args.run_b:
            return misuse("--list takes no versions and no --run-a/--run-b")
        return _list(args)
    if len(args.versions) != 2:
        return misuse(f"diff needs two versions, got {len(args.versions)}")
    coll = load(args.collection)
    try:
        found = diff_mod.diff(
            coll, args.component, *args.versions, run_a=args.run_a, run_b=args.run_b
        )
    except diff_mod.DiffError as exc:
        return misuse(str(exc))
    written = diff_mod.write(found)
    print(diff_mod.render(found))
    for path in written:
        print(f"wrote {path}")
    return OK


def _list(args: argparse.Namespace) -> int:
    from .. import diff as diff_mod

    coll = load(args.collection)
    try:
        found = diff_mod.versions(coll, args.component)
    except diff_mod.DiffError as exc:
        return misuse(str(exc))
    # One lookup for every version: the component, its proposals and its history are read once.
    texts = diff_mod.Texts(coll, args.component)
    recoverable = {v.source_hash: texts.recover(v.source_hash).text is not None for v in found}
    print(diff_mod.render_versions(args.component, found, recoverable), end="")
    return OK
