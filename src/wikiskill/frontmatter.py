"""Reading and rewriting YAML frontmatter in wikiskill's single-source components."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

_FENCE = "---"


class FrontmatterError(Exception):
    """A component file has no frontmatter, or frontmatter that is not a YAML mapping."""


@dataclass
class Document:
    """A component file split into its frontmatter and its body."""

    meta: dict[str, Any]
    body: str
    path: Path | None = None

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
    try:
        meta = yaml.safe_load(raw) or {}
    except yaml.YAMLError as exc:
        raise FrontmatterError(f"frontmatter is not valid YAML{where}: {exc}") from exc
    if not isinstance(meta, dict):
        raise FrontmatterError(f"frontmatter{where} must be a mapping, got {type(meta).__name__}")
    return Document(meta=meta, body=rest.lstrip("\n"), path=path)


def read(path: str | Path) -> Document:
    file_path = Path(path)
    return parse(file_path.read_text(encoding="utf-8"), path=file_path)
