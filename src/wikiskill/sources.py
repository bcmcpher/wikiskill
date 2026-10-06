"""Source snapshots: the text of each component version, kept by its `source_hash`.

A version of a component is only the hash of its main file, and the file moves on. Runs and refine
store the text they hashed here, so `wikiskill diff` can show it later without the source
repository's history. One file per hash, `sources/sha256-<hex>`: content-addressed, so a snapshot
is written once and never changes, and two runs of one version share it.

Light on purpose: the runner and refine import it, and neither should pay for `diff`.
"""

from __future__ import annotations

import os
import secrets
from pathlib import Path

from . import paths, rawlog
from .errors import WikiskillError

PREFIX = "sha256:"


class SnapshotError(WikiskillError):
    """A snapshot could not be stored. Callers report it as a warning; nothing fails on it."""


def key(source_hash: str) -> str:
    """The file name for a hash: `sha256-<hex>`, since `:` is not portable in a file name."""
    return source_hash.replace(PREFIX, "sha256-", 1)


def path_for(collection: str, source_hash: str) -> Path:
    return paths.sources_dir(collection) / key(source_hash)


def store(collection: str, data: bytes) -> str:
    """Keep ``data`` under its hash and return the hash.

    A snapshot that already holds that text is left alone; one that does not, truncated or damaged,
    is replaced. The file gets the data directory's usual mode, not a temporary file's owner-only
    one.
    """
    source_hash = rawlog.content_hash(data)
    target = path_for(collection, source_hash)
    if read(collection, source_hash) is not None:
        return source_hash
    directory = target.parent
    temporary = directory / f".tmp-{os.getpid()}-{secrets.token_hex(4)}"
    try:
        directory.mkdir(parents=True, exist_ok=True)
        try:
            with temporary.open("xb") as out:
                out.write(data)
            os.replace(temporary, target)
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise
    except OSError as exc:
        raise SnapshotError(f"could not store a source snapshot in {directory}: {exc}") from exc
    return source_hash


def read(collection: str, source_hash: str) -> bytes | None:
    """The snapshot of a version, or None when there is none or it does not hash to its key."""
    try:
        data = path_for(collection, source_hash).read_bytes()
    except OSError:
        return None
    return data if rawlog.content_hash(data) == source_hash else None
