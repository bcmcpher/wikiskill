"""The evaluation guard for Claude Code: a `PreToolUse` hook that refuses what a task denies.

The same rules as the OpenCode guard in `harness/opencode/guard/`, ported because a Claude Code hook
is a process rather than a plugin: shell commands matching a deny pattern are refused, and a unit's
tool calls past its step budget are refused too. The wording of both refusals is shared with that
guard, because the runner classifies a unit by it.

Installed only into an evaluation run's own config directory, never into a user's. Like the OpenCode
guard it is fail-closed where it matters: configuration it cannot read blocks nothing it was not
asked to block, but a pattern that matches always refuses.

Configuration arrives in the environment, per unit:
  WIKISKILL_GUARD_DENY   JSON array of glob patterns matched against each shell command
  WIKISKILL_GUARD_TOOLS  JSON array of tool names to refuse outright (optional)
  WIKISKILL_MAX_STEPS    tool calls the unit may make before it is cut off (optional)
  WIKISKILL_GUARD_STATE  file the step count is kept in, since every call is a new process
"""

from __future__ import annotations

import contextlib
import fcntl
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

#: Tools whose argument is a shell command line, lowercased.
COMMAND_TOOLS = ("bash", "shell")

#: Argument keys those tools use for the command line.
COMMAND_KEYS = ("command", "cmd", "script")

#: Both shared with `guard.ts`, and read by the runners to classify a unit.
BLOCKED_PREFIX = "blocked by the wikiskill evaluation guard"
STEP_MARKER = "step budget of"
STEP_EXHAUSTED = BLOCKED_PREFIX + ": " + STEP_MARKER + " {budget} exhausted"


def parse_list(raw: str | None) -> list[str]:
    """A JSON array of strings from the environment, tolerating anything that is not one."""
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if not isinstance(parsed, list):
        return []
    return [entry for entry in parsed if isinstance(entry, str) and entry]


def parse_budget(raw: str | None) -> int | None:
    if not raw:
        return None
    try:
        parsed = int(raw)
    except ValueError:
        return None
    return parsed if parsed >= 1 else None


def matches(subject: str, pattern: str) -> bool:
    """Glob match anchored at both ends: `*` spans anything, newlines too; `?` one character."""
    expanded = "".join(
        "[\\s\\S]*" if char == "*" else "[\\s\\S]" if char == "?" else re.escape(char)
        for char in pattern
    )
    return re.fullmatch(expanded, subject) is not None


def commands_in(args: dict[str, Any]) -> list[str]:
    """Every shell command a call would run. Splitting over-approximates, the safe direction."""
    found: list[str] = []
    for key in COMMAND_KEYS:
        value = args.get(key)
        if not isinstance(value, str) or not value.strip():
            continue
        whole = value.strip()
        found.append(whole)
        for part in re.split(r"&&|\|\||;|\||\n", value):
            trimmed = part.strip()
            if trimmed and trimmed != whole:
                found.append(trimmed)
    return found


def denial_for(
    tool: str, args: dict[str, Any], deny: list[str], denied_tools: list[str]
) -> tuple[str, str] | None:
    """``(subject, pattern)`` for the pattern that refuses this call, or None."""
    name = (tool or "").lower()
    for denied in denied_tools:
        if matches(name, denied.lower()):
            return f"tool {name}", denied
    if name not in COMMAND_TOOLS or not deny:
        return None
    for command in commands_in(args):
        for pattern in deny:
            if matches(command, pattern):
                return command, pattern
    return None


def count_step(state: Path) -> int:
    """Add one to the unit's step count and return it, locked: subagents call concurrently."""
    state.parent.mkdir(parents=True, exist_ok=True)
    with state.open("a+", encoding="utf-8") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        handle.seek(0)
        text = handle.read().strip()
        steps = (int(text) if text.isdigit() else 0) + 1
        handle.seek(0)
        handle.truncate()
        handle.write(str(steps))
    return steps


def decide(payload: dict[str, Any], env: dict[str, str]) -> str | None:
    """Why this call is refused, or None to let it through."""
    budget = parse_budget(env.get("WIKISKILL_MAX_STEPS"))
    state = env.get("WIKISKILL_GUARD_STATE")
    # Counted before the deny check, so a model cannot buy steps by making calls it knows will fail.
    if state:
        steps = count_step(Path(state))
        if budget is not None and steps > budget:
            return STEP_EXHAUSTED.format(budget=budget)
    tool_input = payload.get("tool_input")
    found = denial_for(
        str(payload.get("tool_name") or ""),
        tool_input if isinstance(tool_input, dict) else {},
        parse_list(env.get("WIKISKILL_GUARD_DENY")),
        parse_list(env.get("WIKISKILL_GUARD_TOOLS")),
    )
    if found:
        return f"{BLOCKED_PREFIX}: {found[0]} matches deny pattern {found[1]}"
    return None


def main(stdin=None, stdout=None) -> int:
    """Read one `PreToolUse` event; print a deny decision if the call is refused. Always exits 0."""
    stdin = stdin or sys.stdin
    stdout = stdout or sys.stdout
    payload: Any = {}
    with contextlib.suppress(json.JSONDecodeError, OSError):
        payload = json.loads(stdin.read() or "{}")
    reason = decide(payload if isinstance(payload, dict) else {}, dict(os.environ))
    if reason:
        decision = {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": reason,
            }
        }
        stdout.write(json.dumps(decision) + "\n")
    return 0
