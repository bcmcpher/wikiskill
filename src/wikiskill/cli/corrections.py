"""`wikiskill corrections`: find correction signals outside a session."""

from __future__ import annotations

import argparse
import contextlib
import sys
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from ._common import FAILED, OK, add_collection_argument, named_or_every

if TYPE_CHECKING:
    from ..collection import Collection


def register(sub) -> None:
    corr = sub.add_parser("corrections", help="find correction signals outside a session")
    corr_sub = corr.add_subparsers(dest="corrections_command", required=True)
    scan = corr_sub.add_parser(
        "scan", help="record edits made to files a watched component wrote, since it wrote them"
    )
    add_collection_argument(scan, "only this collection (default: every one)")
    scan.add_argument(
        "--quiet", action="store_true", help="print nothing and always succeed (for the loggers)"
    )
    scan.set_defaults(func=cmd_corrections_scan)


def cmd_corrections_scan(args: argparse.Namespace) -> int:
    """Record edits to files components wrote. `--quiet` is how the loggers run it: in the
    background, at session start, where nothing may be printed and nothing may fail."""
    from .. import corrections as corrections_mod
    from .. import paths
    from ..rawlog import RawLogError

    found, problems = [], []
    for coll in named_or_every(args.collection):
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
    from .. import paths

    with contextlib.suppress(OSError):
        log = paths.logger_error_log(coll.name)
        log.parent.mkdir(parents=True, exist_ok=True)
        with log.open("a", encoding="utf-8") as handle:
            handle.write(f"{datetime.now(UTC).isoformat()} corrections scan: {exc}\n")
