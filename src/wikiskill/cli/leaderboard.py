"""`wikiskill leaderboard`: pool runs of one suite, from any machines, per model and condition."""

from __future__ import annotations

import argparse
from pathlib import Path

from ._common import OK, add_collection_argument, load, misuse


def register(sub) -> None:
    board = sub.add_parser(
        "leaderboard", help="pool runs of one suite, from any machines, per model and condition"
    )
    board.add_argument(
        "run", nargs="+", help="a run directory, or a run id under --collection's evals"
    )
    add_collection_argument(board, "where to find runs given by id")
    board.add_argument(
        "--out", default=None, help="output directory (default: under the collection's evals)"
    )
    board.add_argument(
        "--by-version",
        default=None,
        metavar="COMPONENT",
        help="rank this component's versions per model and overall; runs may differ in it alone",
    )
    board.add_argument(
        "--baseline",
        default=None,
        help="with --by-version: the version the others are measured against, as `wikiskill diff` "
        "names versions (default: current)",
    )
    board.add_argument(
        "--condition",
        default=None,
        choices=("injected", "routed"),
        help="with --by-version: the condition ranked (default: injected)",
    )
    board.add_argument(
        "--critical",
        default=None,
        help="with --by-version: a YAML list of {task, verifier} checks that must never fail",
    )
    board.set_defaults(func=cmd_leaderboard)


def cmd_leaderboard(args: argparse.Namespace) -> int:
    from .. import compare as compare_mod
    from .. import leaderboard as leaderboard_mod
    from .. import paths

    by_version_only = [
        flag
        for flag, value in (
            ("--baseline", args.baseline),
            ("--condition", args.condition),
            ("--critical", args.critical),
        )
        if value
    ]
    if by_version_only and not args.by_version:
        return misuse(f"{', '.join(by_version_only)} only apply with --by-version")
    if args.by_version and not args.collection:
        return misuse("--by-version needs --collection, which names its versions")
    runs = []
    for run in args.run:
        if not Path(run).is_dir() and not args.collection:
            return misuse(f"{run} is not a directory; pass a path, or --collection")
        runs.append(compare_mod.load_run(args.collection or "", run))
    if args.by_version:
        return _by_version(args, runs)
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


def _by_version(args: argparse.Namespace, runs) -> int:
    from .. import diff as diff_mod
    from .. import version_board as board_mod

    coll = load(args.collection)
    component = args.by_version
    try:
        baseline = diff_mod.resolve(coll, component, args.baseline or diff_mod.CURRENT, loaded=runs)
        critical = board_mod.load_critical(args.critical) if args.critical else None
        board = board_mod.pool(
            runs,
            component,
            condition=args.condition or "injected",
            baseline=baseline,
            labels=board_mod.version_labels(coll, component, runs),
            critical=critical,
        )
    except (diff_mod.DiffError, board_mod.LeaderboardError) as exc:
        return misuse(str(exc))
    out = Path(args.out) if args.out else board_mod.output_dir(coll.name, board)
    md, js = board_mod.write(board, out)
    print(board_mod.render(board))
    print(f"wrote {md}")
    print(f"wrote {js}")
    return OK
