"""A model catalogue: what wikiskill is told about each model, since it never guesses.

A model's family cannot be read off its name. `qwen3` and `qwen3.8` are one family, and Ollama
reports `mistral:latest` as a `llama` architecture. So family, size and shape are declared in a
small TOML file, and outputs use them to group rows and to mark a judge that shares a family with
the model it judges:

    [models."qwen3:30b-a3b"]
    family = "qwen"
    size_b = 30.5
    shape = "moe"

A key names a model with or without its provider, as `review --model` does. A model the catalogue
does not list is shown as uncatalogued, never dropped.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import names
from .errors import WikiskillError


class CatalogueError(WikiskillError):
    """A catalogue that cannot be read or does not say what a catalogue says."""


@dataclass(frozen=True)
class ModelInfo:
    model: str
    family: str
    size_b: float | None = None
    shape: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {"family": self.family, "size_b": self.size_b, "shape": self.shape}


@dataclass(frozen=True)
class Catalogue:
    entries: dict[str, ModelInfo] = field(default_factory=dict)
    source: str = ""

    def get(self, model: str) -> ModelInfo | None:
        """The entry for a model, matched with or without its provider on either side."""
        wanted = model.lower()
        for key, info in self.entries.items():
            if wanted in (key, names.model_id(key)) or key == names.model_id(wanted):
                return info
        return None

    def family(self, model: str) -> str | None:
        info = self.get(model)
        return info.family if info else None

    def order(self, models: list[str]) -> list[str]:
        """Catalogued models grouped by family and ordered by size, then the rest by name.

        Families keep the order of their smallest member, so a table reads from small to large.
        """
        known = [(m, self.get(m)) for m in models]
        listed = [(m, info) for m, info in known if info]
        smallest: dict[str, float] = {}
        for _, info in listed:
            size = info.size_b if info.size_b is not None else float("inf")
            smallest[info.family] = min(smallest.get(info.family, float("inf")), size)
        listed.sort(
            key=lambda pair: (
                smallest[pair[1].family],
                pair[1].family,
                pair[1].size_b if pair[1].size_b is not None else float("inf"),
                pair[0],
            )
        )
        rest = sorted(m for m, info in known if info is None)
        return [m for m, _ in listed] + rest


def load(path: str | Path) -> Catalogue:
    path = Path(path)
    try:
        document = tomllib.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise CatalogueError(f"cannot read the model catalogue {path}: {exc}") from exc
    except tomllib.TOMLDecodeError as exc:
        raise CatalogueError(f"{path} is not valid TOML: {exc}") from exc
    models = document.get("models")
    if set(document) != {"models"} or not isinstance(models, dict) or not models:
        raise CatalogueError(f'{path} must hold one `[models."<model>"]` table per model')
    entries = {}
    for model, raw in models.items():
        entries[model.lower()] = _entry(path, model, raw)
    return Catalogue(entries=entries, source=str(path))


def _entry(path: Path, model: str, raw: Any) -> ModelInfo:
    where = f"{path}: models.{model!r}"
    if not isinstance(raw, dict):
        raise CatalogueError(f"{where} must be a table")
    extra = set(raw) - {"family", "size_b", "shape"}
    if extra:
        raise CatalogueError(f"{where} has unknown keys: {', '.join(sorted(extra))}")
    family, size, shape = raw.get("family"), raw.get("size_b"), raw.get("shape")
    if not isinstance(family, str) or not family.strip():
        raise CatalogueError(f"{where} needs a `family`")
    if size is not None and (isinstance(size, bool) or not isinstance(size, int | float)):
        raise CatalogueError(f"{where}: `size_b` must be a number of billions of parameters")
    if shape is not None and not isinstance(shape, str):
        raise CatalogueError(f"{where}: `shape` must be text")
    return ModelInfo(
        model=model,
        family=family.strip().lower(),
        size_b=float(size) if size is not None else None,
        shape=shape,
    )


def load_optional(path: str | Path | None) -> Catalogue | None:
    return load(path) if path else None
