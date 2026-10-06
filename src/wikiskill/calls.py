"""What a tool call activated or delegated to: one place for every harness's tool and field names.

Both runners, the judge's view of delegations, and the Claude Code hook ask the same question of a
tool call: is it a skill or an agent, and which one? The answer depends on the harness only through
names, and those names live here. Stdlib only, because the hook imports it on every tool call.
"""

from __future__ import annotations

from typing import Any

CLAUDE_CODE, OPENCODE = "claude-code", "opencode"

#: Tool names, matched without case.
SKILL_TOOLS = frozenset({"skill", "skills"})
AGENT_TOOLS = frozenset({"agent", "task"})

#: Where each harness's tool input names the component, in the order they are tried.
FIELDS: dict[str, dict[str, tuple[str, ...]]] = {
    CLAUDE_CODE: {"skill": ("skill", "name", "command"), "agent": ("subagent_type",)},
    OPENCODE: {
        "skill": ("name", "skill", "skill_name"),
        "agent": ("subagent_type", "subagentType", "agent", "name"),
    },
}
#: For events whose harness is not known: every field any harness uses.
ANY_HARNESS = {
    "skill": ("skill", "name", "command", "skill_name"),
    "agent": ("subagent_type", "subagentType", "agent", "name"),
}


def qualified(name: str) -> str:
    """Claude Code's `plugin:name` as the collection writes it, `plugin/name`."""
    return name.replace(":", "/", 1)


def _field(args: dict[str, Any], keys: tuple[str, ...]) -> str | None:
    for key in keys:
        value = args.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def kind_of(tool: str) -> str | None:
    """`skill` or `agent` for a tool that activates one, else None."""
    name = tool.lower()
    if name in SKILL_TOOLS:
        return "skill"
    if name in AGENT_TOOLS:
        return "agent"
    return None


def target(tool: str, args: Any, harness: str | None = None) -> tuple[str, str] | None:
    """``(kind, name)`` for a call that activates a skill or delegates to an agent, else None.

    The name is as the harness wrote it; callers that need the collection's `plugin/name` apply
    `qualified`.
    """
    kind = kind_of(tool)
    if kind is None or not isinstance(args, dict):
        return None
    fields = (FIELDS.get(harness or "") or ANY_HARNESS)[kind]
    name = _field(args, fields)
    if not name:
        return None
    return kind, name


def delegation(tool: str, args: Any, harness: str | None = None) -> dict[str, str] | None:
    """The agent a call delegated to and what it passed on, or None when it delegated nothing."""
    found = target(tool, args, harness)
    if found is None or found[0] != "agent":
        return None
    return {
        "agent": found[1],
        "description": str(args.get("description") or ""),
        "prompt": str(args.get("prompt") or ""),
    }
