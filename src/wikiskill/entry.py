"""The `wikiskill` console script: a fast path for the two hook commands, then the full CLI.

Claude Code runs `wikiskill hook <event>` on every hook event, and an evaluation runs `wikiskill
guard` before every tool call. Importing `cli` to reach them loads every command's module first, so
the exact shapes `hook`, `hook <event>` and `guard` are dispatched here instead. So is a bare
`--version`, because building the parser imports the modules its defaults come from. Anything else,
`--help` and argparse errors included, goes through `cli.main`.
"""

from __future__ import annotations

import sys


def fast_path(argv: list[str]) -> tuple[str, str] | None:
    """The command and hook event `argv` asks for, if it is one of the shapes taken here."""
    if argv == ["guard"]:
        return "guard", ""
    if argv == ["--version"]:
        return "version", ""
    command, *rest = argv or [""]
    if command == "hook" and len(rest) <= 1:
        event = rest[0] if rest else ""
        if not event.startswith("-"):
            return "hook", event
    return None


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    found = fast_path(args)
    if found is None:
        from .cli import main as cli_main  # noqa: PLC0415 - only when the fast path does not apply

        return cli_main(args)
    command, event = found
    if command == "version":
        from . import __version__  # noqa: PLC0415 - the package itself, already imported

        print(f"wikiskill {__version__}")
        return 0
    if command == "guard":
        from . import guard  # noqa: PLC0415 - keep the hook's import light

        return guard.main()
    from . import hooks  # noqa: PLC0415 - keep the hook's import light

    return hooks.run(event, sys.stdin.read())
