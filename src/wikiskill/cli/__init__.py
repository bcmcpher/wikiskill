"""The ``wikiskill`` command line.

Skills, commands and harness hooks all reach wikiskill through this CLI, so its output is written to
be read by a person and its exit codes are meaningful: 0 success, 1 a reported failure, 2 misuse.

Each command group is a module here with a `register(subparsers)` and its handlers. A handler
imports the modules it uses when it runs, so a command loads its own and not every other's.
"""

from __future__ import annotations

import argparse
import sys

from .. import __version__
from ..errors import WikiskillError
from . import (
    build,
    collection,
    compare,
    corrections,
    diff,
    eval,
    findings,
    graph,
    hook,
    install,
    leaderboard,
    log,
    note,
    proposal,
    refine,
    report,
    review,
    suite,
)
from ._common import FAILED, MISUSE, OK
from .hook import cmd_guard, cmd_hook

__all__ = ["FAILED", "MISUSE", "OK", "build_parser", "cmd_guard", "cmd_hook", "main"]

#: In the order `wikiskill --help` lists them.
GROUPS = (
    collection,
    log,
    suite,
    eval,
    build,
    install,
    hook,
    note,
    corrections,
    compare,
    diff,
    leaderboard,
    report,
    findings,
    review,
    refine,
    proposal,
    graph,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="wikiskill",
        description="Trace what skills and subagents do with a model, across harnesses.",
    )
    parser.add_argument("--version", action="version", version=f"wikiskill {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)
    for group in GROUPS:
        group.register(sub)
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
