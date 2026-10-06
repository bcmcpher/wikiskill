"""`wikiskill suite`: validate task suites."""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

from ._common import FAILED, OK


def register(sub) -> None:
    suite_cmd = sub.add_parser("suite", help="validate task suites").add_subparsers(
        dest="subcommand", required=True
    )
    suite_check = suite_cmd.add_parser(
        "check", help="validate a suite and flag prompts that name their own expected route"
    )
    suite_check.add_argument("file", nargs="+", help="task suite file")
    suite_check.set_defaults(func=cmd_suite_check)


def cmd_suite_check(args: argparse.Namespace) -> int:
    from .. import suite as suite_mod
    from ..suite import SuiteError

    failed = 0
    for raw in args.file:
        path = Path(raw)
        try:
            loaded = suite_mod.load(path)
        except SuiteError as exc:
            failed += 1
            print(f"suite {exc.path or path}  FAILED")
            for problem in exc.problems:
                print(f"  ! {problem}")
            continue
        splits = Counter(task.split for task in loaded.tasks)
        spread = ", ".join(f"{name} {splits[name]}" for name in suite_mod.SPLITS if splits[name])
        print(f"suite {loaded.name}  ({loaded.path})")
        print(f"  {len(loaded.tasks)} tasks  [{spread}]")
        for task in loaded.tasks:
            route = ", ".join(task.expect.names()) or "-"
            print(
                f"    {task.id:32} x{task.repeats}  route {route}  "
                f"{len(task.verifiers)} verifiers{'  rubric' if task.rubric else ''}"
            )
        for warning in loaded.warnings:
            print(f"  ? {warning}")
        print("  ok" + (f", {len(loaded.warnings)} to look at" if loaded.warnings else ""))
    if failed:
        print(f"\n{failed} of {len(args.file)} suites failed", file=sys.stderr)
    return FAILED if failed else OK
