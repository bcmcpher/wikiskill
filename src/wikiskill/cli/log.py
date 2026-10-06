"""`wikiskill log`: inspect the raw event log."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from ._common import FAILED, OK, load

if TYPE_CHECKING:
    from ..collection import Collection


def register(sub) -> None:
    log = sub.add_parser("log", help="inspect the raw event log").add_subparsers(
        dest="subcommand", required=True
    )
    for name, handler, helptext in (
        ("validate", cmd_log_validate, "validate every log against the raw event schema"),
        ("stats", cmd_log_stats, "summarise a collection's raw log"),
        ("tail", cmd_log_tail, "print the most recent events"),
    ):
        node = log.add_parser(name, help=helptext)
        node.add_argument("name", help="collection name")
        node.add_argument(
            "--raw-dir", type=Path, default=None, help="override the raw log location"
        )
        node.set_defaults(func=handler)
    log.choices["validate"].add_argument("--limit", type=int, default=20)
    log.choices["tail"].add_argument("-n", "--count", type=int, default=20)
    log.choices["tail"].add_argument("-f", "--follow", action="store_true")
    log.choices["tail"].add_argument("--json", action="store_true")


def cmd_log_validate(args: argparse.Namespace) -> int:
    from .. import logtools

    report = logtools.validate(args.name, raw_dir=args.raw_dir)
    print(f"raw log {report.raw_dir}")
    print(f"  {report.files} session logs, {report.events} events")
    print(f"  {report.activations} component_activated events")
    print(f"  {len(report.problems)} schema errors")
    for problem in report.problems[: args.limit]:
        print(f"    {problem}")
    if len(report.problems) > args.limit:
        print(f"    ... and {len(report.problems) - args.limit} more")
    for refusal in report.refused:
        print(f"  refused: {refusal}", file=sys.stderr)
    return OK if report.ok else FAILED


def cmd_log_stats(args: argparse.Namespace) -> int:
    from .. import logtools
    from ..collection import ManifestError

    try:
        coll: Collection | str = load(args.name)
    except ManifestError:
        # Stats are useful even when the manifest has drifted; only the watched-path signal is lost.
        coll = args.name
    summary = logtools.stats(coll, raw_dir=args.raw_dir)
    print(f"raw log {summary.raw_dir}")
    print(f"  sessions  {summary.sessions}")
    print(f"  events    {summary.events}")
    print(f"  size      {summary.megabytes:.2f} MiB")
    if summary.days:
        print(f"  days      {summary.days[0]} .. {summary.days[-1]} ({len(summary.days)})")
    for label, counter in (
        ("type", summary.by_type),
        ("model", summary.by_model),
        ("component", summary.by_component),
    ):
        for key, value in counter.most_common():
            print(f"  {label:9} {key}  {value}")
    if summary.reads_without_activation:
        print(
            f"  {len(summary.reads_without_activation)} sessions touched a watched component's "
            "source file without recording an activation:"
        )
        for session in summary.reads_without_activation:
            print(f"    ? {session}")
    for error in summary.errors:
        print(f"  error: {error}", file=sys.stderr)
    return FAILED if summary.errors else OK


def cmd_log_tail(args: argparse.Namespace) -> int:
    from .. import logtools

    try:
        for event in logtools.tail(
            args.name, raw_dir=args.raw_dir, count=args.count, follow=args.follow
        ):
            if args.json:
                print(json.dumps(event, separators=(",", ":")))
            else:
                component = event.get("component")
                if not isinstance(component, dict):
                    component = {}
                label = f"{component.get('kind', '-')}:{component.get('name', '-')}"
                # A hand-edited or truncated line still gets a row: tail is how a broken log is
                # looked at, so it must not be the thing that refuses to read one.
                print(
                    f"{event.get('ts', '-')}  {event.get('type', '-')!s:20} {label:32} "
                    f"{event.get('provider')}/{event.get('model')}"
                )
    except KeyboardInterrupt:
        return OK
    return OK
