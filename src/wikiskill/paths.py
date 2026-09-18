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


#: Data the installed CLI reads at runtime: where it sits inside the package, and where it sits in
#: a checkout. Every entry must be shipped by the wheel — `pyproject.toml`'s `force-include` maps
#: the checkout path onto the packaged one, and `tests/test_packaging.py` checks that it still does.
PACKAGED_DATA: dict[str, tuple[str, str]] = {
    "schema": ("_schemas/raw-event.schema.json", "schemas/raw-event.schema.json"),
    "suite-schema": ("_schemas/task-suite.schema.json", "schemas/task-suite.schema.json"),
    "source": ("_source", "harness/source"),
    "opencode-plugin": ("_harness/opencode/plugin", "harness/opencode/plugin"),
    "opencode-guard": ("_harness/opencode/guard", "harness/opencode/guard"),
}


def package_dir() -> Path:
    return Path(__file__).resolve().parent


def packaged_data(kind: str) -> Path:
    """Locate packaged data, whether running from a checkout or an installed wheel.

    Returns the checkout location when neither exists, so the caller can report the path it wanted.
    """
    packaged, in_checkout = PACKAGED_DATA[kind]
    here = package_dir()
    for candidate in (here / packaged, here.parent.parent / in_checkout):
        if candidate.exists():
            return candidate
    return here.parent.parent / in_checkout


def schema_path() -> Path:
    """The raw event schema, whether running from a checkout or an installed wheel."""
    found = packaged_data("schema")
    if not found.is_file():
        raise FileNotFoundError(
            f"raw-event.schema.json not found next to the package or at {found}"
        )
    return found


def suite_schema_path() -> Path:
    """The task suite schema, whether running from a checkout or an installed wheel."""
    found = packaged_data("suite-schema")
    if not found.is_file():
        raise FileNotFoundError(
            f"task-suite.schema.json not found next to the package or at {found}"
        )
    return found


def source_tree() -> Path:
    """wikiskill's own single-source component tree."""
    found = packaged_data("source")
    if not found.is_dir():
        raise FileNotFoundError(f"harness/source not found next to the package or at {found}")
    return found
