"""What the command groups share: exit codes, the misuse message, and the `--collection` argument.

Light on purpose: every group imports this at load time, and so does `wikiskill.cli` itself.
"""

from __future__ import annotations

import argparse
import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..collection import Collection

OK, FAILED, MISUSE = 0, 1, 2


def misuse(message: str) -> int:
    """Say why the arguments cannot describe what was asked, and return `MISUSE`."""
    print(f"error: {message}", file=sys.stderr)
    return MISUSE


def add_collection_argument(
    parser: argparse.ArgumentParser, help: str | None = None, *, required: bool = False
) -> None:
    """The `--collection` option, required or with a help line of the command's own."""
    parser.add_argument("--collection", required=required, default=None, help=help)


def load(name: str) -> Collection:
    from .. import collection as collection_mod

    return collection_mod.load(name)


def collection_for(name: str | None) -> Collection | None:
    return load(name) if name else None


def named_or_every(name: str | None) -> list[Collection]:
    """The one collection named, or every one with a readable manifest."""
    if name:
        return [load(name)]
    from .. import paths
    from ..collection import ManifestError

    found = []
    for manifest in sorted(paths.collections_dir().glob("*.toml")):
        try:
            found.append(load(manifest.stem))
        except ManifestError:
            continue
    return found
