"""The console script's fast path, and the one error base the CLI reports through."""

from __future__ import annotations

import importlib
import inspect
import io
import pkgutil
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

import wikiskill
from wikiskill import entry, guard, hooks
from wikiskill.cli import build_parser, cmd_guard, cmd_hook
from wikiskill.errors import WikiskillError

REPO = Path(__file__).resolve().parent.parent

# --------------------------------------------------------------------------- the fast path

TAKEN = [["hook"], ["hook", "PostToolUse"], ["hook", ""], ["guard"]]
LEFT_TO_THE_PARSER = [
    [],
    ["--version"],
    ["hook", "--help"],
    ["hook", "-h"],
    ["hook", "Stop", "extra"],
    ["guard", "--help"],
    ["guard", "extra"],
    ["log", "tail", "x"],
]


@pytest.mark.parametrize("argv", TAKEN)
def test_the_fast_path_takes_what_the_parser_would_send_to_the_same_handler(argv):
    command, event = entry.fast_path(argv)
    args = build_parser().parse_args(argv)
    assert args.func is (cmd_hook if command == "hook" else cmd_guard)
    if command == "hook":
        assert (args.event or "") == event


@pytest.mark.parametrize("argv", LEFT_TO_THE_PARSER)
def test_everything_else_goes_through_the_parser(argv):
    assert entry.fast_path(argv) is None


def test_hook_dispatches_its_event_and_stdin(monkeypatch):
    seen = []
    monkeypatch.setattr(hooks, "run", lambda event, stdin: seen.append((event, stdin)) or 0)
    monkeypatch.setattr(sys, "stdin", io.StringIO('{"x": 1}'))
    assert entry.main(["hook", "Stop"]) == 0
    assert seen == [("Stop", '{"x": 1}')]


def test_guard_dispatches_to_the_guard(monkeypatch):
    monkeypatch.setattr(guard, "main", lambda: 7)
    assert entry.main(["guard"]) == 7


def test_the_console_script_is_the_entry_module():
    with (REPO / "pyproject.toml").open("rb") as handle:
        scripts = tomllib.load(handle)["project"]["scripts"]
    assert scripts["wikiskill"] == "wikiskill.entry:main"


def test_a_hook_event_never_imports_the_cli(xdg):
    """The point of the fast path: a hook pays for `hooks`, not for every command's module."""
    code = (
        "import sys\n"
        "from wikiskill.entry import main\n"
        "main(['hook', 'Stop'])\n"
        "print('wikiskill.cli' in sys.modules)\n"
    )
    done = subprocess.run(
        [sys.executable, "-c", code], input="", capture_output=True, text=True, check=True
    )
    assert done.stdout.strip() == "False"


# --------------------------------------------------------------------------- one error base


def _package_exceptions() -> list[type[BaseException]]:
    found = []
    for info in pkgutil.walk_packages(wikiskill.__path__, prefix="wikiskill."):
        if info.name == "wikiskill.__main__":  # importing it runs the CLI
            continue
        module = importlib.import_module(info.name)
        for _, cls in inspect.getmembers(module, inspect.isclass):
            if cls.__module__ == module.__name__ and issubclass(cls, BaseException):
                found.append(cls)
    return found


def test_every_error_the_package_defines_derives_from_the_one_base():
    found = _package_exceptions()
    assert len(found) >= 20
    assert [cls.__qualname__ for cls in found if not issubclass(cls, WikiskillError)] == []
