"""Propose one change to one component, grounded in its wiki patterns. Never apply it.

Started only by the user. The proposer sees the component's full text and its patterns, and answers
with either `no_action` or a small set of exact find-and-replace edits. Edits rather than a diff,
because a small model reproduces a sentence far more reliably than it counts diff hunk lines. From
those edits wikiskill writes the patch itself, checks that it applies to the source repository with
`git apply --check` (which writes nothing), and saves it under `wiki/proposals/<id>/` for the user
to read and apply by hand.

The next evaluation of the component then runs at a new `source_hash`, and `wikiskill compare`
says whether the change did anything.
"""

from __future__ import annotations

import difflib
import json
import subprocess
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from . import paths, rawlog, wiki
from .collection import Collection
from .frontmatter import read as read_frontmatter
from .review import DEFAULT_RETRIES, Ask

PROPOSALS = "proposals"
PATTERN_TEXT_LIMIT = 6_000

#: What the proposer must return. Kept here rather than in `schemas/` because nothing outside this
#: module reads it, and the edits are resolved against a file before anything is written.
REPLY_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["action", "reason", "patterns"],
    "properties": {
        "action": {"enum": ["patch", "no_action"]},
        "reason": {"type": "string", "minLength": 1},
        "patterns": {"type": "array", "items": {"type": "string"}, "uniqueItems": True},
        "edits": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["find", "replace"],
                "properties": {
                    "find": {"type": "string", "minLength": 1},
                    "replace": {"type": "string"},
                },
            },
        },
    },
}


class RefineError(Exception):
    """A refinement could not be carried out."""


@dataclass
class Proposal:
    action: str
    reason: str
    patterns: list[str]
    directory: Path | None = None
    diff: str = ""
    attempts: int = 1
    problems: list[str] = field(default_factory=list)


# --------------------------------------------------------------------------- prompt


def proposer_prompt() -> str:
    path = paths.source_tree() / "agents" / "wikiskill-proposer.md"
    return read_frontmatter(path).body.strip()


def component_file(collection: Collection, component: str) -> Path:
    matches = [c for c in collection.discover() if c.name == component]
    if not matches:
        raise RefineError(f"{component!r} is not a component of collection {collection.name!r}")
    return matches[0].path


def prompt(component: str, text: str, patterns: dict[str, Any]) -> str:
    lines = [f"# Component: {component}", "", "## Its full text", "", "````", text, "````", ""]
    lines += ["## Its wiki patterns", ""]
    used = 0
    for slug, document in sorted(patterns.items()):
        meta = document.meta
        block = (
            f"### {slug}\n\ncause: {meta.get('cause')}; models: "
            f"{', '.join(meta.get('models') or [])}; trigger: {meta.get('trigger')}\n\n"
            f"{document.body.strip()}\n"
        )
        if used + len(block) > PATTERN_TEXT_LIMIT:
            lines.append(f"(pattern {slug} omitted: over the length limit)")
            continue
        used += len(block)
        lines.append(block)
    if not patterns:
        lines.append("- none")
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------------- validation


def validate(reply: Any, *, text: str, known_patterns: Sequence[str]) -> list[str]:
    """Every reason a proposer reply cannot become a proposal."""
    validator = Draft202012Validator(REPLY_SCHEMA)
    problems = [
        f"{'/'.join(str(p) for p in error.absolute_path) or '(top level)'}: {error.message}"
        for error in validator.iter_errors(reply)
    ]
    if problems:
        return problems
    unknown = [p for p in reply["patterns"] if p not in known_patterns]
    if unknown:
        problems.append(
            f"patterns: {', '.join(unknown)} are not patterns of this component; known: "
            f"{', '.join(known_patterns) or 'none'}"
        )
    if reply["action"] == "no_action":
        return problems
    if not reply["patterns"]:
        problems.append("patterns: a patch must cite at least one wiki pattern")
    edits = reply.get("edits") or []
    if not edits:
        problems.append("edits: a patch needs at least one edit")
    for index, edit in enumerate(edits):
        count = text.count(edit["find"])
        if count != 1:
            where = "does not occur" if count == 0 else f"occurs {count} times"
            problems.append(
                f"edits/{index}: `find` {where} in the component's text; copy one exact, unique "
                "passage"
            )
        if edit["find"] == edit["replace"]:
            problems.append(f"edits/{index}: `replace` is identical to `find`")
    return problems


def apply_edits(text: str, edits: Sequence[dict[str, str]]) -> str:
    for edit in edits:
        text = text.replace(edit["find"], edit["replace"], 1)
    return text


# --------------------------------------------------------------------------- patch


def repository_of(path: Path) -> Path | None:
    done = subprocess.run(
        ["git", "-C", str(path.parent), "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
        check=False,
    )
    return Path(done.stdout.strip()) if done.returncode == 0 and done.stdout.strip() else None


def make_diff(path: Path, before: str, after: str) -> str:
    """A unified diff `git apply` accepts, relative to the file's repository when it has one."""
    repo = repository_of(path)
    relative = str(path.relative_to(repo)) if repo else path.name
    lines = difflib.unified_diff(
        before.splitlines(keepends=True),
        after.splitlines(keepends=True),
        fromfile=f"a/{relative}",
        tofile=f"b/{relative}",
    )
    diff = "".join(lines)
    return diff if diff.endswith("\n") else diff + "\n"


def check_applies(path: Path, diff: str) -> str | None:
    """Why the patch would not apply to the source repository, or None. Writes nothing."""
    repo = repository_of(path)
    if repo is None:
        return None
    done = subprocess.run(
        ["git", "-C", str(repo), "apply", "--check", "-"],
        input=diff,
        capture_output=True,
        text=True,
        check=False,
    )
    return None if done.returncode == 0 else (done.stderr.strip() or "git apply --check failed")


def next_id(collection: str) -> str:
    directory = wiki.wiki_root(collection) / PROPOSALS
    taken = [p.name for p in directory.iterdir()] if directory.is_dir() else []
    numbers = [int(n[2:]) for n in taken if n.startswith("p-") and n[2:].isdigit()]
    return f"p-{(max(numbers) + 1) if numbers else 1:03d}"


# --------------------------------------------------------------------------- refine


def refine(
    collection: Collection,
    component: str,
    *,
    ask: Ask,
    proposer: str,
    retries: int = DEFAULT_RETRIES,
) -> Proposal:
    """Ask for one proposal, validate it, and write it as a patch. Nothing is ever applied."""
    path = component_file(collection, component)
    text = path.read_text(encoding="utf-8")
    known = wiki.patterns(collection.name, component)
    if not known:
        return Proposal(
            action="no_action",
            reason=f"the wiki holds no pattern for {component}; run `wikiskill review` first",
            patterns=[],
            attempts=0,
        )

    messages = [
        {"role": "system", "content": proposer_prompt()},
        {"role": "user", "content": prompt(component, text, known)},
    ]
    problems: list[str] = []
    for attempt in range(1, retries + 2):
        answer = ask(messages)
        reply: dict[str, Any] = {}
        try:
            reply = wiki.parse_reply(answer)
            problems = validate(reply, text=text, known_patterns=sorted(known))
        except wiki.WikiError as exc:
            problems = [str(exc)]
        if not problems and reply["action"] == "patch":
            after = apply_edits(text, reply["edits"])
            diff = make_diff(path, text, after)
            refused = check_applies(path, diff)
            if refused:
                problems = [f"the patch would not apply to the source repository: {refused}"]
        if not problems:
            return _write(
                collection,
                component,
                reply,
                path=path,
                text=text,
                proposer=proposer,
                attempts=attempt,
            )
        messages += [
            {"role": "assistant", "content": answer},
            {
                "role": "user",
                "content": (
                    "Your reply cannot become a proposal. Fix these problems and reply with the "
                    "whole JSON object again, nothing else:\n- " + "\n- ".join(problems)
                ),
            },
        ]
    return Proposal(
        action="failed", reason="", patterns=[], attempts=retries + 1, problems=problems
    )


def _write(
    collection: Collection,
    component: str,
    reply: dict[str, Any],
    *,
    path: Path,
    text: str,
    proposer: str,
    attempts: int,
) -> Proposal:
    proposal = Proposal(
        action=reply["action"],
        reason=reply["reason"],
        patterns=list(reply["patterns"]),
        attempts=attempts,
    )
    if reply["action"] == "no_action":
        return proposal

    root = wiki.ensure(collection.name)
    proposal_id = next_id(collection.name)
    directory = root / PROPOSALS / proposal_id
    directory.mkdir(parents=True)
    after = apply_edits(text, reply["edits"])
    proposal.diff = make_diff(path, text, after)
    proposal.directory = directory
    repo = repository_of(path)

    (directory / "patch.diff").write_text(proposal.diff, encoding="utf-8")
    (directory / "meta.json").write_text(
        json.dumps(
            {
                "id": proposal_id,
                "component": component,
                "source_path": str(path),
                "repository": str(repo) if repo else None,
                "source_hash": rawlog.file_hash(path),
                "patterns": proposal.patterns,
                "reason": proposal.reason,
                "proposer": proposer,
                "created": rawlog.now_ts(),
                "status": "proposed",
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    apply_hint = (
        f"git -C {repo} apply {directory / 'patch.diff'}"
        if repo
        else f"patch {path} < {directory / 'patch.diff'}"
    )
    (directory / "preview.md").write_text(
        "\n".join(
            [
                f"# {proposal_id}: {component}",
                "",
                f"**Why:** {proposal.reason}",
                "",
                "**Patterns:** " + ", ".join(f"`{p}`" for p in proposal.patterns),
                "",
                "**Edits:**",
                "",
                *[
                    f"{i}. Replace\n\n   > {e['find'].strip()[:600]}\n\n   with\n\n   > "
                    f"{e['replace'].strip()[:600] or '(nothing)'}\n"
                    for i, e in enumerate(reply["edits"], 1)
                ],
                "## Patch",
                "",
                "```diff",
                proposal.diff.rstrip(),
                "```",
                "",
                "Nothing has been applied. To try it, apply it yourself, re-run the same suite,",
                "and compare:",
                "",
                "```bash",
                apply_hint,
                (
                    f"wikiskill eval --suite <suite> --collection {collection.name} "
                    "--models <same models> --condition <same conditions>"
                ),
                f"wikiskill compare <before-run> <after-run> --collection {collection.name} \\",
                f"  --record accept|reject --proposal {proposal_id}",
                "```",
                "",
            ]
        ),
        encoding="utf-8",
    )
    wiki.commit(root, f"propose {proposal_id} for {component}")
    return proposal
