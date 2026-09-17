"""XDG locations. Nothing here writes into a collection's source repository."""

from __future__ import annotations

import os
from pathlib import Path

_APP = "wikiskill"


def _xdg(var: str, default: str) -> Path:
    raw = os.environ.get(var)
    base = Path(raw).expanduser() if raw else Path.home() / default
    return base / _APP


def config_home() -> Path:
    """``${XDG_CONFIG_HOME:-~/.config}/wikiskill``."""
    return _xdg("XDG_CONFIG_HOME", ".config")


def data_home() -> Path:
    """``${XDG_DATA_HOME:-~/.local/share}/wikiskill``."""
    return _xdg("XDG_DATA_HOME", ".local/share")


def state_home() -> Path:
    """``${XDG_STATE_HOME:-~/.local/state}/wikiskill`` — install records live here."""
    return _xdg("XDG_STATE_HOME", ".local/state")


def collections_dir() -> Path:
    return config_home() / "collections"


def manifest_path(collection: str) -> Path:
    return collections_dir() / f"{collection}.toml"


def collection_data(collection: str) -> Path:
    return data_home() / collection


def raw_dir(collection: str) -> Path:
    return collection_data(collection) / "raw"


def wiki_dir(collection: str) -> Path:
    return collection_data(collection) / "wiki"


def evals_dir(collection: str) -> Path:
    return collection_data(collection) / "evals"


def logger_error_log(collection: str) -> Path:
    return raw_dir(collection) / "_logger-errors.log"


def schema_path() -> Path:
    """The raw event schema, whether running from a checkout or an installed wheel."""
    here = Path(__file__).resolve().parent
    for candidate in (here / "_schemas" / "raw-event.schema.json",
                      here.parent.parent / "schemas" / "raw-event.schema.json"):
        if candidate.is_file():
            return candidate
    raise FileNotFoundError("raw-event.schema.json not found next to the package or in ./schemas")


def source_tree() -> Path:
    """wikiskill's own single-source component tree."""
    here = Path(__file__).resolve().parent
    for candidate in (here / "_source", here.parent.parent / "harness" / "source"):
        if candidate.is_dir():
            return candidate
    raise FileNotFoundError("harness/source not found next to the package or in ./harness")
