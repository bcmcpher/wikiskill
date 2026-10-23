"""Deterministic verifiers: the half of scoring that does not involve a model.

A verifier decides pass or fail. A rubric judge, when it arrives (task 4.3), only scores its own
dimensions and never overrides what is decided here — that ordering is the whole point of
"verifier-first" in the `eval-scoring` spec.

Nothing here knows about a harness. A verifier is given a working directory, the session's final
text, and its transcript; whichever backend produced them is not this module's business, so the
same checks apply to `add-claude-code-adapter`'s backend unchanged.

The distinction that matters is between a check that *fails* and a check that could not be *carried
out*. A command exiting 1 when 0 was expected is a result: the model did not do the job. A command
that times out, or a workdir that is not there, says nothing about the model at all, so it raises
`VerifierError` and the runner records the unit as `infra_error` instead of scoring it.
"""

from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .. import redact
from ..errors import WikiskillError
from ..suite import Task, Verifier

#: A verifier gets its own budget rather than the session's `timeout_s`: checking the work should
#: never take as long as doing it, and a wedged check would otherwise hide behind a 900s default.
VERIFIER_TIMEOUT_S = 120

#: How much of a failing command's output is kept. Enough to see the error, not enough to bury a
#: report in a stack trace.
OUTPUT_TAIL = 2000

#: Stripped before a verifier runs. These configure the harness for the session that has already
#: finished; a verifier inheriting them would read the run's inline config as if it were its own.
#: Everything else is left alone, including `XDG_*` — a verifier is an ordinary shell command and
#: the tools it calls should find their usual homes.
_DROPPED_ENV_PREFIXES = ("OPENCODE_", "WIKISKILL_")


class VerifierError(WikiskillError):
    """A verifier could not be carried out. Infrastructure, never a verdict about the model."""


@dataclass(frozen=True)
class VerifierResult:
    """One check's verdict, with enough detail for a report to say why."""

    kind: str
    passed: bool
    detail: str
    exit_code: int | None = None
    output: str = ""

    def as_dict(self) -> dict[str, Any]:
        record: dict[str, Any] = {"kind": self.kind, "passed": self.passed, "detail": self.detail}
        if self.exit_code is not None:
            record["exit_code"] = self.exit_code
        if self.output:
            record["output"] = self.output
        return record


# --------------------------------------------------------------------------- paths


def resolve_in(workdir: Path, raw: str) -> Path:
    """A workdir-relative path, refusing anything that points outside it.

    The schema documents this rule for `file_exists`; `suite.parse` enforces it at load time. This
    is the second half of the same guard, for a `Verifier` built in code rather than read from YAML.
    """
    candidate = Path(raw)
    if candidate.is_absolute() or raw.startswith("~"):
        raise VerifierError(f"path must be relative to the workdir, got {raw!r}")
    resolved = (workdir / candidate).resolve()
    root = workdir.resolve()
    if resolved != root and root not in resolved.parents:
        raise VerifierError(f"path {raw!r} escapes the workdir")
    return resolved


def _env(withhold: tuple[str, ...] = ()) -> dict[str, str]:
    """The host's environment, less the runner's own variables and ``withhold``."""
    drop = frozenset(withhold)
    return {
        key: value
        for key, value in os.environ.items()
        if not key.startswith(_DROPPED_ENV_PREFIXES) and key not in drop
    }


# --------------------------------------------------------------------------- kinds


def _command(
    verifier: Verifier,
    workdir: Path,
    timeout_s: int,
    env: dict[str, str] | None = None,
    *,
    hide: tuple[str, ...] = (),
    withhold: tuple[str, ...] = (),
) -> VerifierResult:
    if not verifier.run:
        raise VerifierError("a command verifier needs `run`")
    try:
        done = subprocess.run(
            verifier.run,
            shell=True,
            cwd=workdir,
            capture_output=True,
            text=True,
            errors="replace",
            timeout=timeout_s,
            env={**_env(withhold), **(env or {})},
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise VerifierError(f"`{verifier.run}` timed out after {timeout_s}s") from exc
    except OSError as exc:
        raise VerifierError(f"`{verifier.run}` could not be started: {exc}") from exc

    output = done.stdout + done.stderr
    if hide:
        # Before the tail is cut, so a cut cannot leave half a secret behind, and before the strip,
        # so a value ending in whitespace is still whole. A scorer that echoes its configuration
        # must not write the secret into `results.jsonl`.
        output, _ = redact.redact(output, sorted(hide, key=len, reverse=True))
    output = output.strip()
    return VerifierResult(
        kind=verifier.kind,
        passed=done.returncode == verifier.expect_exit,
        detail=f"`{verifier.run}` exited {done.returncode}, expected {verifier.expect_exit}",
        exit_code=done.returncode,
        output=output[-OUTPUT_TAIL:],
    )


def _file_exists(verifier: Verifier, workdir: Path) -> VerifierResult:
    if not verifier.path:
        raise VerifierError("a file_exists verifier needs `path`")
    target = resolve_in(workdir, verifier.path)
    found = target.exists()
    return VerifierResult(
        kind=verifier.kind,
        passed=found,
        detail=f"{verifier.path} {'exists' if found else 'does not exist'}",
    )


def _regex(verifier: Verifier, workdir: Path, final_text: str, transcript: str) -> VerifierResult:
    if not verifier.pattern:
        raise VerifierError("a regex verifier needs `pattern`")
    try:
        pattern = re.compile(verifier.pattern)
    except re.error as exc:
        raise VerifierError(
            f"{verifier.pattern!r} is not a valid regular expression: {exc}"
        ) from exc

    if verifier.target == "file":
        if not verifier.path:
            raise VerifierError("a regex verifier with `target: file` needs `path`")
        target = resolve_in(workdir, verifier.path)
        if not target.is_file():
            # A missing file is a fail, not a crash: "the model never wrote it" is a verdict.
            return VerifierResult(
                kind=verifier.kind,
                passed=False,
                detail=f"{verifier.path} does not exist, so /{verifier.pattern}/ cannot match",
            )
        haystack = target.read_text(encoding="utf-8", errors="replace")
        where = verifier.path
    elif verifier.target == "transcript":
        haystack, where = transcript, "the transcript"
    else:
        haystack, where = final_text, "the final text"

    found = pattern.search(haystack) is not None
    return VerifierResult(
        kind=verifier.kind,
        passed=found,
        detail=f"/{verifier.pattern}/ {'found' if found else 'not found'} in {where}",
    )


# --------------------------------------------------------------------------- running


def run_verifier(
    verifier: Verifier,
    *,
    workdir: Path,
    final_text: str = "",
    transcript: str = "",
    timeout_s: int = VERIFIER_TIMEOUT_S,
    env: dict[str, str] | None = None,
    hide: tuple[str, ...] = (),
    withhold: tuple[str, ...] = (),
) -> VerifierResult:
    """Carry out one verifier and return its verdict, with `negate` applied last.

    `env` is the task's own environment, laid over the host's for a command verifier. `hide` holds
    secret values that a command's kept output must not show. ``withhold`` names host variables a
    command does not inherit: the secrets other tasks of the suite declare.
    """
    if verifier.kind == "command":
        result = _command(verifier, workdir, timeout_s, env, hide=hide, withhold=withhold)
    elif verifier.kind == "file_exists":
        result = _file_exists(verifier, workdir)
    elif verifier.kind == "regex":
        result = _regex(verifier, workdir, final_text, transcript)
    else:
        raise VerifierError(f"unknown verifier kind {verifier.kind!r}")

    if not verifier.negate:
        return result
    # The detail describes what was observed, so it stays true; only the verdict flips.
    return VerifierResult(
        kind=result.kind,
        passed=not result.passed,
        detail=f"negated: {result.detail}",
        exit_code=result.exit_code,
        output=result.output,
    )


def verify_task(
    task: Task,
    *,
    workdir: Path | None,
    final_text: str = "",
    transcript: str = "",
    timeout_s: int = VERIFIER_TIMEOUT_S,
) -> tuple[list[VerifierResult], bool | None]:
    """Every verifier a task declares, and whether all of them passed.

    The verdict is `None` when the task declares no verifiers, so "nothing was checked" never reads
    as "everything passed". Verifiers run in declaration order and all of them run: a report that
    named only the first failure would send a contributor back for a second run to find the second.
    """
    if not task.verifiers:
        return [], None
    if workdir is None or not workdir.is_dir():
        raise VerifierError(f"no working directory to verify in: {workdir}")

    # The one process of a unit that gets the task's secrets, each with its host value. Named
    # explicitly rather than left to inheritance, so the grant does not hang on what `_env` keeps.
    # Another task's secrets are not inherited: a verifier gets its own task's and no more.
    secrets = task.secret_env()
    env = {**task.resolved_env(), **secrets}
    others = tuple(name for name in task.withheld if name not in task.secrets)
    results = [
        run_verifier(
            verifier,
            workdir=workdir,
            final_text=final_text,
            transcript=transcript,
            timeout_s=timeout_s,
            env=env,
            hide=task.withheld_values(),
            withhold=others,
        )
        for verifier in task.verifiers
    ]
    return results, all(result.passed for result in results)
