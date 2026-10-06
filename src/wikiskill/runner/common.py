"""Helpers both evaluation backends use: model names, event fields, and a unit's starting state."""

from __future__ import annotations

import contextlib
import os
import subprocess
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .. import redact
from .base import RunnerError, Unit

#: One setup command's budget. Setup builds a starting state; it is not where work happens.
SETUP_TIMEOUT_S = 300


# Not `names.model_id`, whose rule differs on a name ending in a slash: there `ollama/` is "", here
# it is `ollama/` from provider "unknown". The two agree on every other name.
def split_model(model: str) -> tuple[str, str]:
    """``(provider, model)``: ``("ollama", "qwen3:30b-a3b")`` for `ollama/qwen3:30b-a3b`."""
    provider, _, rest = model.partition("/")
    return (provider, rest) if rest else ("unknown", model)


def model_id(model: str) -> str:
    """`ollama/gemma4:latest` → `gemma4:latest`, as a harness's `--model` takes it."""
    return split_model(model)[1]


def string_field(source: dict[str, Any], *keys: str) -> str | None:
    """The first of ``keys`` holding a non-empty string."""
    for key in keys:
        value = source.get(key)
        if isinstance(value, str) and value:
            return value
    return None


@dataclass(frozen=True)
class Scrubber:
    """Redaction and the size bound for one unit's events, as live logging applies them.

    Redaction comes first, so a secret the bound would cut cannot survive as its first half.
    """

    enabled: bool
    secrets: tuple[str, ...]
    limit: int

    @classmethod
    def of(cls, enabled: bool, env: dict[str, str], limit: int) -> Scrubber:
        return cls(enabled, tuple(redact.env_secrets(env)) if enabled else (), limit)

    def text(self, raw: str) -> tuple[str, bool, list[dict[str, Any]]]:
        """``(text, truncated, redactions)`` for a free-text field that has a size bound."""
        clean, redactions = self.value(raw)
        bounded = redact.bound(clean, self.limit)
        return bounded.text, bounded.truncated, redactions

    def value(self, obj: Any) -> tuple[Any, list[dict[str, Any]]]:
        """``obj`` with every string in it redacted, and what was found."""
        if not self.enabled:
            return obj, []
        return redact.redact_value(obj, self.secrets)


def merged(*found: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Several fields' redactions as one event's list."""
    return redact.merge(entry for entries in found for entry in entries)


def run_setup(unit: Unit, workdir: Path, root: Path) -> None:
    """Run a task's setup commands in its workdir, logging each to `setup.log`.

    A command that fails raises `RunnerError`, which the caller records as `infra_error`: a unit
    that never reached its starting state says nothing about the model.
    """
    if not unit.task.setup:
        return
    env = {**os.environ, **unit.task.resolved_env()}
    with (root / "setup.log").open("w", encoding="utf-8") as log:
        for command in unit.task.setup:
            log.write(f"$ {command}\n")
            try:
                done = subprocess.run(
                    command,
                    shell=True,
                    cwd=workdir,
                    stdin=subprocess.DEVNULL,
                    capture_output=True,
                    text=True,
                    errors="replace",
                    timeout=SETUP_TIMEOUT_S,
                    env=env,
                    check=False,
                )
            except subprocess.TimeoutExpired as exc:
                raise RunnerError(
                    f"setup `{command}` for task {unit.task.id!r} did not finish within "
                    f"{SETUP_TIMEOUT_S}s"
                ) from exc
            except OSError as exc:
                raise RunnerError(f"setup `{command}` could not be started: {exc}") from exc
            log.write(done.stdout + done.stderr)
            if done.returncode != 0:
                tail = (done.stderr or done.stdout).strip().splitlines()[-3:]
                raise RunnerError(
                    f"setup `{command}` for task {unit.task.id!r} exited {done.returncode}"
                    + (f": {' / '.join(tail)}" if tail else "")
                )


def git_init(workdir: Path) -> None:
    """A workdir is a git repo so the harness can snapshot it, and so verifiers can diff it."""
    # A run without git still works; only the harness's own snapshotting is lost.
    with contextlib.suppress(OSError, subprocess.SubprocessError):
        subprocess.run(
            ["git", "init", "--quiet", str(workdir)],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            timeout=60,
            check=False,
        )
