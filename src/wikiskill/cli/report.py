"""`wikiskill report`: rebuild a finished run's report from its own files."""

from __future__ import annotations

import argparse
from pathlib import Path

from ._common import OK, add_collection_argument, misuse


def register(sub) -> None:
    rep = sub.add_parser(
        "report", help="rebuild a finished run's report.md and report.json; runs and judges nothing"
    )
    rep.add_argument("run", help="a run directory, or a run id under --collection's evals")
    add_collection_argument(rep, "where to find a run given by id")
    rep.add_argument(
        "--models-file",
        default=None,
        help="a model catalogue (TOML): marks judges of the judged model's own family",
    )
    rep.set_defaults(func=cmd_report)


def cmd_report(args: argparse.Namespace) -> int:
    from .. import catalogue as catalogue_mod
    from .. import compare as compare_mod
    from .. import report as report_mod

    if not Path(args.run).is_dir() and not args.collection:
        return misuse(f"{args.run} is not a directory; pass a path, or --collection")
    try:
        catalogue = catalogue_mod.load_optional(args.models_file)
        run = compare_mod.load_run(args.collection or "", args.run)
    except (catalogue_mod.CatalogueError, compare_mod.CompareError) as exc:
        return misuse(str(exc))
    report_mod.rebuild(run, catalogue)
    print(f"wrote {run.root / 'report.md'}")
    print(f"wrote {run.root / 'report.json'}")
    return OK
