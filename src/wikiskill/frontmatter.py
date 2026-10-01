"""Reading and rewriting YAML frontmatter in wikiskill's single-source components."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

_FENCE = "---"

#: A top-level `key: value` line. Indented lines belong to a block above them and are never touched.
_TOP_LEVEL = re.compile(r"^(?P<key>[A-Za-z0-9_-]+):[ \t]+(?P<value>\S.*?)[ \t]*$")


class FrontmatterError(Exception):
    """A component file has no frontmatter, or frontmatter that is not a YAML mapping."""


@dataclass
class Document:
    """A component file split into its frontmatter and its body."""

    meta: dict[str, Any]
    body: str
    path: Path | None = None
    #: Keys whose value was not valid YAML as written and was read as a plain string instead.
    repaired: tuple[str, ...] = field(default=())

    def render(self, meta: dict[str, Any] | None = None) -> str:
        """The file text with ``meta`` (default: this document's) as frontmatter.

        ``sort_keys=False`` keeps the emitted order the caller chose, so a built file reads the way
        the harness's own documentation writes it.
        """
        front = yaml.safe_dump(
            meta if meta is not None else self.meta,
            sort_keys=False,
            allow_unicode=True,
            default_flow_style=False,
            width=100,
        )
        return f"{_FENCE}\n{front}{_FENCE}\n\n{self.body.lstrip(chr(10))}"


def parse(text: str, path: Path | None = None) -> Document:
    where = f" in {path}" if path else ""
    if not text.startswith(_FENCE):
        raise FrontmatterError(f"no YAML frontmatter{where}: the file must start with `---`")
    end = text.find(f"\n{_FENCE}", len(_FENCE))
    if end == -1:
        raise FrontmatterError(f"unterminated frontmatter{where}: no closing `---`")
    raw = text[len(_FENCE) : end]
    rest = text[end + len(_FENCE) + 1 :]
    repaired: tuple[str, ...] = ()
    try:
        meta = yaml.safe_load(raw) or {}
    except yaml.YAMLError as exc:
        meta, repaired = _lenient(raw)
        if meta is None:
            raise FrontmatterError(f"frontmatter is not valid YAML{where}: {exc}") from exc
    if not isinstance(meta, dict):
        raise FrontmatterError(f"frontmatter{where} must be a mapping, got {type(meta).__name__}")
    return Document(meta=meta, body=rest.lstrip("\n"), path=path, repaired=repaired)


def _lenient(raw: str) -> tuple[Any, tuple[str, ...]]:
    """Read frontmatter the way Claude Code does when strict YAML refuses it.

    Claude Code accepts `argument-hint: [path] — audit a directory`, which YAML reads as a flow
    sequence followed by stray text. Plugins written for it carry such lines, and refusing them
    would refuse the whole collection. A top-level line that does not parse on its own is read as
    the plain string it was meant to be; nothing else is rewritten. Returns ``(None, ())`` when
    the frontmatter still does not parse, so the caller reports the original error.
    """
    lines = raw.split("\n")
    repaired: list[str] = []
    for index, line in enumerate(lines):
        match = _TOP_LEVEL.match(line)
        if not match or match["value"][0] in "'\"|>":
            continue
        try:
            yaml.safe_load(line)
        except yaml.YAMLError:
            quoted = "'" + match["value"].replace("'", "''") + "'"
            lines[index] = f"{match['key']}: {quoted}"
            repaired.append(match["key"])
    if not repaired:
        return None, ()
    try:
        return yaml.safe_load("\n".join(lines)) or {}, tuple(repaired)
    except yaml.YAMLError:
        return None, ()


def repaired_warning(doc: Document) -> str:
    """What a lenient read changed, worded for a person who can quote the value in the source."""
    keys = ", ".join(f"`{key}`" for key in doc.repaired)
    return (
        f"{doc.path}: {keys} is not valid YAML as written and was read as plain text; "
        "quote the value to make that explicit"
    )


def read(path: str | Path) -> Document:
    file_path = Path(path)
    return parse(file_path.read_text(encoding="utf-8"), path=file_path)
