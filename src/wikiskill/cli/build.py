"""`wikiskill build`: generate a harness layout from the neutral source."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from ._common import FAILED, OK, add_collection_argument, collection_for


def register(sub) -> None:
    from ..build import HARNESSES

    build_cmd = sub.add_parser("build", help="generate a harness layout from the neutral source")
    build_cmd.add_argument("--harness", choices=HARNESSES, required=True)
    add_collection_argument(
        build_cmd,
        "build this collection's own sources, with its alias table, instead of wikiskill's",
    )
    build_cmd.add_argument("--out", default=None, help="output directory (default dist/<harness>)")
    build_cmd.set_defaults(func=cmd_build)


def cmd_build(args: argparse.Namespace) -> int:
    from ..build import BuildError, build, build_collection, dist_dir

    coll = collection_for(args.collection)
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
