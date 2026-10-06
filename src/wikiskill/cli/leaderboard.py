"""`wikiskill leaderboard`: pool runs of one suite, from any machines, per model and condition."""

from __future__ import annotations

import argparse
from pathlib import Path

from ._common import OK, add_collection_argument, misuse


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
    board.set_defaults(func=cmd_leaderboard)


def cmd_leaderboard(args: argparse.Namespace) -> int:
    from .. import compare as compare_mod
    from .. import leaderboard as leaderboard_mod
    from .. import paths

    runs = []
    for run in args.run:
        if not Path(run).is_dir() and not args.collection:
            return misuse(f"{run} is not a directory; pass a path, or --collection")
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
