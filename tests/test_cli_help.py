"""Temporary: `--help` for every command, as recorded from `cli.py` before it became a package.

The split must not move an argument, a default or a help string. This compares every command's
`--help` with `fixtures/cli_help.json`, byte for byte, and is deleted with the fixture once the
split is done. Regenerate the fixture (from the old module only) with:

    uv run --frozen python tests/test_cli_help.py
"""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
import sys
from pathlib import Path

import pytest

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "cli_help.json"
ENVIRONMENT = {"COLUMNS": "80", "NO_COLOR": "1"}
UNSET = ("FORCE_COLOR", "PYTHON_COLORS")


def commands(parser: argparse.ArgumentParser, prefix: tuple[str, ...] = ()) -> list[list[str]]:
    """Every command path the parser accepts, in the parser's own order, the top level first."""
    found = [list(prefix)]
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            for name, child in action.choices.items():
                found.extend(commands(child, (*prefix, name)))
    return found


def help_text(argv: list[str]) -> str:
    from wikiskill.cli import main

    out = io.StringIO()
    with contextlib.redirect_stdout(out), pytest.raises(SystemExit) as stopped:
        main([*argv, "--help"])
    assert stopped.value.code == 0
    return out.getvalue()


def record() -> list[dict]:
    from wikiskill.cli import build_parser

    return [{"argv": argv, "help": help_text(argv)} for argv in commands(build_parser())]


@pytest.fixture
def fixed_terminal(monkeypatch):
    for name, value in ENVIRONMENT.items():
        monkeypatch.setenv(name, value)
    for name in UNSET:
        monkeypatch.delenv(name, raising=False)


def test_the_same_commands_in_the_same_order(fixed_terminal):
    from wikiskill.cli import build_parser

    recorded = [entry["argv"] for entry in json.loads(FIXTURE.read_text(encoding="utf-8"))]
    assert commands(build_parser()) == recorded


@pytest.mark.parametrize(
    "entry",
    json.loads(FIXTURE.read_text(encoding="utf-8")) if FIXTURE.is_file() else [],
    ids=lambda entry: " ".join(entry["argv"]) or "wikiskill",
)
def test_help_is_unchanged(fixed_terminal, entry):
    assert help_text(entry["argv"]) == entry["help"]


if __name__ == "__main__":
    os.environ.update(ENVIRONMENT)
    for name in UNSET:
        os.environ.pop(name, None)
    recorded = record()
    FIXTURE.write_text(json.dumps(recorded, indent=2) + "\n", encoding="utf-8")
    print(f"recorded --help for {len(recorded)} commands in {FIXTURE}", file=sys.stderr)
