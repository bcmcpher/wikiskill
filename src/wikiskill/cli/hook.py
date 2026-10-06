"""`wikiskill hook` and `wikiskill guard`: the two commands a harness runs, not a person.

`wikiskill.entry` dispatches their exact shapes itself, without importing the CLI; these handlers
are what the parser sends the rest to, `--help` and argparse errors aside.
"""

from __future__ import annotations

import argparse
import sys


def register(sub) -> None:
    hook = sub.add_parser(
        "hook", help="(Claude Code) log one hook event read from stdin; always exits 0, silently"
    )
    hook.add_argument("event", nargs="?", default="", help="e.g. PostToolUse")
    hook.set_defaults(func=cmd_hook)
    guard = sub.add_parser(
        "guard",
        help="(evaluation, Claude Code) refuse a tool call a task denies; reads a PreToolUse event",
    )
    guard.set_defaults(func=cmd_guard)


def cmd_hook(args: argparse.Namespace) -> int:
    """Claude Code runs this per hook event. Silent and always 0, whatever happens inside."""
    from .. import hooks as hooks_mod

    return hooks_mod.run(args.event or "", sys.stdin.read())


def cmd_guard(_args: argparse.Namespace) -> int:
    """An evaluation's `PreToolUse` hook: prints a deny decision for a refused call."""
    from .. import guard as guard_mod

    return guard_mod.main()
