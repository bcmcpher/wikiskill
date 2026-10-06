"""What changed between two versions of one component: its text, and its results.

A version is a `source_hash`. The user names one as `current`, a hash prefix, a proposal (`p-003`
is its candidate, `p-003^` the version it was made from) or `run:<id>`, and every form is resolved
to a full hash before anything else, so the rest of this module never sees a reference.

Nothing is evaluated and nothing is written outside the report. The text is recovered, cheapest
first, from source snapshots, the current file, a proposal's rendered copy, a candidate run's copied
source, and last the git history of the component's repository, read without a checkout. The
results are `compare`'s, on the newest pair of finished runs that evaluated each version on the
same suite. Either half that cannot be produced is reported with the reason, beside the other.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from . import compare, gate, names, paths, rawlog, refine, sources
from .collection import Collection, Component
from .errors import WikiskillError

CURRENT = "current"
RUN_PREFIX = "run:"
#: How many revisions of the component's file the git history search reads before it gives up.
GIT_LIMIT = 500

_PROPOSAL = re.compile(r"^(p-\d+)(\^?)$")
_HASH_PREFIX = re.compile(r"^(?:sha256:)?([0-9a-f]{7,64})$")


class DiffError(WikiskillError):
    """A version reference or a run cannot name what was asked."""


def short(source_hash: str | None, length: int = 7) -> str:
    return (source_hash or "?").removeprefix(sources.PREFIX)[:length]


def component_of(collection: Collection, name: str) -> Component:
    found = collection.component(name)
    if found is None:
        raise DiffError(f"{name!r} is not a component of collection {collection.name!r}")
    return found


# --------------------------------------------------------------------------- versions


@dataclass
class Version:
    """One version of a component and every place wikiskill has seen it."""

    source_hash: str
    first_seen: str = ""
    current: bool = False
    #: Proposals whose candidate this is, and proposals made from it.
    produced_by: list[str] = field(default_factory=list)
    base_of: list[str] = field(default_factory=list)
    runs: list[str] = field(default_factory=list)
    activations: int = 0

    def seen(self, when: str) -> None:
        if when and (not self.first_seen or when < self.first_seen):
            self.first_seen = when


def _iso(seconds: float) -> str:
    return (
        datetime.fromtimestamp(seconds, UTC)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


def _run_time(run: compare.LoadedRun) -> str:
    """When a run started: from its ULID, or the manifest's mtime for an id that is not one."""
    ms = rawlog.event_id_ms(run.run_id)
    if ms is not None:
        return _iso(ms / 1000)
    return _mtime(run.root / "run.json")


def _mtime(path: Path) -> str:
    """A file's modification time, or "" when it has gone since it was read."""
    try:
        return _iso(path.stat().st_mtime)
    except OSError:
        return ""


def _proposals(collection: str, component: str) -> list[dict[str, Any]]:
    return [meta for meta in gate.proposals(collection) if meta.get("component") == component]


def versions(
    collection: Collection,
    name: str,
    *,
    loaded: list[compare.LoadedRun] | None = None,
    raw: bool = True,
) -> list[Version]:
    """Every version of a component wikiskill knows of, oldest first.

    Versions come from proposals, run manifests, raw-log activations and the current file. A
    snapshot names no component, so it shows only that a version's text is kept; every snapshot was
    written by a run or a proposal, which records the version anyway.
    """
    component = component_of(collection, name)
    found: dict[str, Version] = {}

    def at(source_hash: str) -> Version:
        return found.setdefault(source_hash, Version(source_hash))

    for meta in _proposals(collection.name, name):
        created = str(meta.get("created") or "")
        if meta.get("source_hash"):
            at(meta["source_hash"]).base_of.append(meta["id"])
            at(meta["source_hash"]).seen(created)
        if meta.get("candidate_hash"):
            at(meta["candidate_hash"]).produced_by.append(meta["id"])
            at(meta["candidate_hash"]).seen(created)

    for run in loaded if loaded is not None else compare.runs(collection.name):
        recorded = run.hashes().get(name)
        if recorded:
            at(recorded).runs.append(run.run_id)
            at(recorded).seen(_run_time(run))

    if raw:
        for source_hash, ts in _activations(collection, component):
            version = at(source_hash)
            version.activations += 1
            version.seen(ts)

    current = rawlog.file_hash(component.path)
    if current:
        at(current).current = True
        if not found[current].first_seen:
            found[current].seen(_mtime(component.path))
    return sorted(found.values(), key=lambda v: (v.first_seen, v.source_hash))


def _activations(collection: Collection, component: Component) -> list[tuple[str, str]]:
    """(source_hash, ts) of each raw-log activation of the component.

    OpenCode logs a plugin's component by its bare name, so a bare name answers for this component,
    but only while no other component of the same kind in the collection shares it; otherwise it is
    left out rather than guessed. A line is decoded only when it mentions an activation and the
    bare name: the raw log is the largest thing read here, and almost every line is something else.
    """
    name, bare = component.name, names.bare(component.name)
    shared = sum(
        1 for c in collection.discover() if c.kind == component.kind and names.bare(c.name) == bare
    )
    seen = []
    for path in rawlog.log_files(paths.raw_dir(collection.name)):
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        for line in lines:
            if '"component_activated"' not in line or bare not in line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if event.get("type") != "component_activated":
                continue
            logged = event.get("component") or {}
            logged_name = str(logged.get("name"))
            if not logged.get("source_hash") or logged.get("kind") != component.kind:
                continue
            if logged_name == name or (shared == 1 and names.matches(name, logged_name)):
                seen.append((logged["source_hash"], str(event.get("ts") or "")))
    return seen


def resolve(
    collection: Collection,
    name: str,
    ref: str,
    *,
    loaded: list[compare.LoadedRun] | None = None,
) -> str:
    """The full `source_hash` a version reference names.

    A hash prefix is matched against this component's own versions, never against snapshots,
    which name no component: a prefix of another component's text must not answer for this one.
    Proposals, runs and the current file are tried first; the raw log, the largest thing to read,
    only when they do not have it. `loaded` passes in runs the caller has already read.
    """
    component = component_of(collection, name)
    if ref == CURRENT:
        found = rawlog.file_hash(component.path)
        if found is None:
            raise DiffError(f"{component.path} cannot be read, so `current` names no version")
        return found
    if ref.startswith(RUN_PREFIX):
        run_id = ref[len(RUN_PREFIX) :]
        try:
            run = compare.load_run(collection.name, run_id)
        except compare.CompareError as exc:
            raise DiffError(f"{ref}: {exc}") from exc
        recorded = run.hashes().get(name)
        if not recorded:
            raise DiffError(f"{ref}: run {run.run_id} recorded no source_hash for {name}")
        return recorded
    if matched := _PROPOSAL.match(ref):
        proposal, base = matched.group(1), matched.group(2) == "^"
        try:
            meta = gate.load(collection.name, proposal)
        except gate.GateError as exc:
            raise DiffError(f"{ref}: {exc}") from exc
        if meta.get("component") != name:
            raise DiffError(
                f"{ref}: {proposal} is a proposal for {meta.get('component')}, not {name}"
            )
        wanted = meta.get("source_hash") if base else meta.get("candidate_hash")
        if not wanted:
            raise DiffError(
                f"{ref}: {proposal} recorded no {'source' if base else 'candidate'} hash"
            )
        return wanted
    if matched := _HASH_PREFIX.match(ref):
        return _resolve_prefix(collection, name, ref, matched.group(1), loaded)
    raise DiffError(
        f"{ref!r} is not a version: use `current`, a hash prefix of at least 7 hex digits, "
        "`p-NNN`, `p-NNN^` or `run:<id>`"
    )


def _resolve_prefix(
    collection: Collection,
    name: str,
    ref: str,
    digits: str,
    loaded: list[compare.LoadedRun] | None,
) -> str:
    hits = _by_prefix(digits, versions(collection, name, loaded=loaded, raw=False))
    if not hits:
        hits = _by_prefix(digits, versions(collection, name, loaded=loaded))
    if not hits:
        raise DiffError(f"{ref!r} matches no known version of {name}")
    if len(hits) > 1:
        raise DiffError(f"{ref!r} matches {len(hits)} versions of {name}: " + ", ".join(hits))
    return hits[0]


def _by_prefix(digits: str, known: list[Version]) -> list[str]:
    return sorted(
        v.source_hash
        for v in known
        if v.source_hash.removeprefix(sources.PREFIX).startswith(digits)
    )


# --------------------------------------------------------------------------- text


@dataclass
class Recovered:
    """A version's text and where it came from, or the places searched for it."""

    source_hash: str
    text: bytes | None = None
    found_in: str | None = None
    searched: list[str] = field(default_factory=list)
    #: Said when a search stopped short, such as at the git history limit.
    note: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "source_hash": self.source_hash,
            "available": self.text is not None,
            "found_in": self.found_in,
            "searched": self.searched,
            "note": self.note,
        }


class Texts:
    """Where one component's version texts can be found, looked up once per command.

    The component, its proposals and the repository's history are read when first needed and kept,
    so recovering several versions costs one discovery, one read of the proposals, and one pass over
    the history.
    """

    def __init__(self, collection: Collection, name: str, *, git: bool = True):
        self.collection = collection
        self.component = component_of(collection, name)
        self.proposals = _proposals(collection.name, name)
        self.history = GitHistory(self.component.path) if git else None

    def recover(self, source_hash: str) -> Recovered:
        """A version's text, from the cheapest place that has it. Every candidate is re-hashed."""
        collection, component = self.collection.name, self.component
        found = Recovered(source_hash)

        def hit(data: bytes | None, where: str) -> bool:
            if data is not None and rawlog.content_hash(data) == source_hash:
                found.text, found.found_in = data, where
                return True
            return False

        found.searched.append("source snapshots")
        if hit(sources.read(collection, source_hash), "source snapshot"):
            return found

        found.searched.append("the current file")
        if hit(rawlog.read_bytes(component.path), f"the current file {component.path}"):
            return found

        found.searched.append("proposals' rendered copies")
        for meta in self.proposals:
            rendered = gate.directory(collection, meta["id"]) / "rendered" / component.path.name
            if hit(rawlog.read_bytes(rendered), f"{meta['id']}'s rendered copy"):
                return found

        relative = _relative(component.path, component.source.path)
        if relative is None:
            found.searched.append(
                "candidate runs' copied sources (skipped: the file is not under its source "
                "directory)"
            )
        else:
            found.searched.append("candidate runs' copied sources")
            evals = paths.evals_dir(collection)
            for copy in sorted(evals.glob("*/candidate-source")) if evals.is_dir() else []:
                where = f"run {copy.parent.name}'s candidate source"
                if hit(rawlog.read_bytes(copy / relative), where):
                    return found

        if self.history is not None:
            found.searched.append(self.history.place)
            data, where = self.history.find(source_hash)
            hit(data, where or "")
            if found.text is None and self.history.note:
                found.note = self.history.note
        return found


def recover(collection: Collection, name: str, source_hash: str, *, git: bool = True) -> Recovered:
    """One version's text. To look up several, make one `Texts` and ask it for each."""
    return Texts(collection, name, git=git).recover(source_hash)


def _relative(path: Path, root: Path) -> Path | None:
    """``path`` below ``root``, also when one of them is reached through a symlink, or None."""
    for left, right in ((path, root), (path.resolve(), root.resolve())):
        try:
            return left.relative_to(right)
        except ValueError:
            continue
    return None


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[bytes]:
    # Optional locks off: even `git status` would otherwise refresh the index, and this reads only.
    # quotePath off: a path with non-ASCII characters is printed as it is, so `git show` takes it.
    return subprocess.run(
        ["git", "-C", str(repo), "-c", "core.quotePath=false", *args],
        capture_output=True,
        check=False,
        env={**os.environ, "GIT_OPTIONAL_LOCKS": "0"},
    )


class GitHistory:
    """The git history of one component file, read lazily and at most once per revision.

    Never checks anything out. Each revision's text is kept by its hash as it is read, so a later
    lookup in the same command starts where the last one stopped instead of from the newest commit.
    """

    def __init__(self, path: Path):
        self.path = path
        self.repo = refine.repository_of(path)
        self.note: str | None = None
        self._revisions: list[tuple[str, str]] | None = None
        self._read = 0
        self._texts: dict[str, tuple[bytes, str]] = {}

    @property
    def place(self) -> str:
        if self.repo is None:
            return "git history (the component is not in a git repository)"
        return f"the git history of {self.repo}"

    def revisions(self) -> list[tuple[str, str]]:
        """(revision, path at that revision), newest first, up to the limit."""
        if self._revisions is not None:
            return self._revisions
        self._revisions = []
        if self.repo is None:
            return self._revisions
        relative = _relative(self.path, self.repo)
        if relative is None:
            self.note = f"{self.path} is not under its repository {self.repo}"
            return self._revisions
        log = _git(
            self.repo,
            "log",
            "--follow",
            "--name-only",
            f"--max-count={GIT_LIMIT}",
            "--format=commit %H",
            "--",
            str(relative),
        )
        if log.returncode != 0:
            self.note = f"git log failed: {log.stderr.decode(errors='replace').strip()}"
            return self._revisions
        revision = None
        for line in log.stdout.decode(errors="replace").splitlines():
            if line.startswith("commit "):
                revision = line.split(" ", 1)[1]
            elif line.strip() and revision is not None:
                self._revisions.append((revision, line.strip()))
                revision = None
        if len(self._revisions) >= GIT_LIMIT:
            self.note = (
                f"the git history search stopped at its limit of {GIT_LIMIT} revisions; older "
                "ones were not read"
            )
        return self._revisions

    def find(self, source_hash: str) -> tuple[bytes | None, str | None]:
        """The text of a version and the revision it came from, or (None, None)."""
        if source_hash in self._texts:
            return self._texts[source_hash]
        revisions = self.revisions()
        while self._read < len(revisions):
            revision, at = revisions[self._read]
            self._read += 1
            assert self.repo is not None
            shown = _git(self.repo, "show", f"{revision}:{at}")
            if shown.returncode != 0:
                continue
            found = rawlog.content_hash(shown.stdout)
            self._texts.setdefault(found, (shown.stdout, f"git {revision[:12]}:{at}"))
            if found == source_hash:
                return self._texts[found]
        return None, None


@dataclass
class TextDiff:
    a: Recovered
    b: Recovered
    identical: bool
    diff: str | None = None
    description_changed: bool | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "identical": self.identical,
            "description_changed": self.description_changed,
            "a": self.a.as_dict(),
            "b": self.b.as_dict(),
        }


def text_diff(collection: Collection, name: str, hash_a: str, hash_b: str) -> TextDiff:
    texts = Texts(collection, name)
    a = texts.recover(hash_a)
    b = a if hash_a == hash_b else texts.recover(hash_b)
    found = TextDiff(a=a, b=b, identical=hash_a == hash_b)
    if found.identical or a.text is None or b.text is None:
        return found
    before, after = a.text.decode("utf-8", "replace"), b.text.decode("utf-8", "replace")
    found.diff = refine.make_diff(texts.component.path, before, after)
    found.description_changed = refine.description_changed(before, after)
    return found


# --------------------------------------------------------------------------- results


@dataclass
class Unavailable:
    """Why no pair of runs could be compared, and the runs found for each version."""

    reason: str
    runs_a: list[str] = field(default_factory=list)
    runs_b: list[str] = field(default_factory=list)


def _group(run: compare.LoadedRun) -> tuple[str, str, tuple[str, ...]]:
    return (run.suite or "", run.suite_hash or "", tuple(sorted(run.tasks)))


def _labelled(of: list[compare.LoadedRun]) -> list[str]:
    return [f"{run.run_id} (suite {run.suite})" for run in of]


def pick_runs(
    collection: Collection,
    name: str,
    hash_a: str,
    hash_b: str,
    *,
    loaded: list[compare.LoadedRun] | None = None,
) -> tuple[compare.LoadedRun, compare.LoadedRun] | Unavailable:
    """The newest pair of runs, one of each version, that share suite, tasks and suite content."""
    every = sorted(
        loaded if loaded is not None else compare.runs(collection.name), key=lambda r: r.run_id
    )
    of_a = [run for run in every if run.hashes().get(name) == hash_a]
    of_b = [run for run in every if run.hashes().get(name) == hash_b]
    if not of_a or not of_b:
        missing = [label for label, of in (("A", of_a), ("B", of_b)) if not of]
        which = " and ".join(f"version {label}" for label in missing)
        return Unavailable(
            f"{which} {'has' if len(missing) == 1 else 'have'} no finished runs",
            _labelled(of_a),
            _labelled(of_b),
        )
    groups: dict[tuple[str, str, tuple[str, ...]], tuple[list, list]] = {}
    for run in of_a:
        groups.setdefault(_group(run), ([], []))[0].append(run)
    for run in of_b:
        groups.setdefault(_group(run), ([], []))[1].append(run)
    shared = []
    for runs_a, runs_b in groups.values():
        if hash_a == hash_b and len(runs_a) >= 2:
            # One version against itself: the two newest runs of it, older as A.
            shared.append((runs_a[-2], runs_a[-1]))
        elif hash_a != hash_b and runs_a and runs_b:
            shared.append((runs_a[-1], runs_b[-1]))
    if not shared:
        return Unavailable(
            "no suite has finished runs of both versions with the same tasks and suite content",
            _labelled(of_a),
            _labelled(of_b),
        )
    return max(shared, key=lambda pair: max(pair[0].run_id, pair[1].run_id))


def explicit_run(
    collection: Collection, name: str, run_id: str, wanted: str, label: str
) -> compare.LoadedRun:
    """A run given with `--run-a`/`--run-b`, refused when it ran another version."""
    try:
        run = compare.load_run(collection.name, run_id)
    except compare.CompareError as exc:
        raise DiffError(str(exc)) from exc
    recorded = run.hashes().get(name)
    if recorded != wanted:
        raise DiffError(
            f"run {run.run_id} recorded {name} at {recorded or 'no source_hash'}, not version "
            f"{label} ({wanted})"
        )
    return run


@dataclass
class Results:
    comparison: compare.Comparison | None = None
    unavailable: Unavailable | None = None

    def as_dict(self) -> dict[str, Any]:
        if self.comparison is not None:
            return {
                "available": True,
                "run_a": self.comparison.a.run_id,
                "run_b": self.comparison.b.run_id,
                "comparison": self.comparison.as_dict(),
            }
        unavailable = self.unavailable or Unavailable("not computed")
        return {
            "available": False,
            "reason": unavailable.reason,
            "runs_a": unavailable.runs_a,
            "runs_b": unavailable.runs_b,
        }


def results_diff(
    collection: Collection,
    name: str,
    hash_a: str,
    hash_b: str,
    *,
    run_a: str | None = None,
    run_b: str | None = None,
    loaded: list[compare.LoadedRun] | None = None,
) -> Results:
    every = loaded if loaded is not None else compare.runs(collection.name)
    a = explicit_run(collection, name, run_a, hash_a, "A") if run_a else None
    b = explicit_run(collection, name, run_b, hash_b, "B") if run_b else None
    if a is None or b is None:
        # Fill the side not given from runs that share the given side's suite, or both sides.
        given = a or b
        pool = [r for r in every if given is None or _group(r) == _group(given)]
        if given is not None and hash_a == hash_b:
            # One version against itself: the other side is another run of it, never the same one,
            # and the older run is A, as everywhere else. A given B is paired with the newest run
            # before it; a given A with the newest run of all.
            others = sorted(
                (r for r in pool if r.run_id != given.run_id and r.hashes().get(name) == hash_a),
                key=lambda r: r.run_id,
            )
            if a is None:
                others = [r for r in others if r.run_id < given.run_id] or others
            if not others:
                return Results(
                    unavailable=Unavailable(
                        f"no other finished run of this version on suite {given.suite}",
                        [given.run_id],
                        [given.run_id],
                    )
                )
            a, b = a or others[-1], b or others[-1]
            return _compared(a, b, name)
        picked = pick_runs(collection, name, hash_a, hash_b, loaded=pool)
        if isinstance(picked, Unavailable):
            return Results(unavailable=_with_hint(collection.name, picked, hash_b))
        a, b = a or picked[0], b or picked[1]
    return _compared(a, b, name)


def _compared(a: compare.LoadedRun, b: compare.LoadedRun, name: str) -> Results:
    try:
        return Results(comparison=compare.compare(a, b, component=name))
    except compare.CompareError as exc:
        raise DiffError(f"runs {a.run_id} and {b.run_id} cannot be compared: {exc}") from exc


def _with_hint(collection: str, unavailable: Unavailable, hash_b: str) -> Unavailable:
    """Point at `eval --proposal` when an unevaluated version B is a proposal's candidate."""
    if unavailable.runs_b:
        return unavailable
    for meta in gate.proposals(collection):
        if meta.get("candidate_hash") == hash_b:
            unavailable.reason += (
                f"; it is {meta['id']}'s candidate, so run it with "
                f"`wikiskill eval --suite <suite> --collection {collection} --models <models> "
                f"--proposal {meta['id']}`"
            )
            break
    return unavailable


# --------------------------------------------------------------------------- report


@dataclass
class Diff:
    collection: str
    component: str
    ref_a: str
    ref_b: str
    hash_a: str
    hash_b: str
    text: TextDiff
    results: Results

    def as_dict(self) -> dict[str, Any]:
        return {
            "collection": self.collection,
            "component": self.component,
            "a": {"ref": self.ref_a, "source_hash": self.hash_a},
            "b": {"ref": self.ref_b, "source_hash": self.hash_b},
            "text": self.text.as_dict(),
            "results": self.results.as_dict(),
        }


def diff(
    collection: Collection,
    name: str,
    ref_a: str,
    ref_b: str,
    *,
    run_a: str | None = None,
    run_b: str | None = None,
) -> Diff:
    # Runs are read once for the whole command: references, the run choice and the comparison.
    every = compare.runs(collection.name)
    hash_a = resolve(collection, name, ref_a, loaded=every)
    hash_b = resolve(collection, name, ref_b, loaded=every)
    return Diff(
        collection=collection.name,
        component=name,
        ref_a=ref_a,
        ref_b=ref_b,
        hash_a=hash_a,
        hash_b=hash_b,
        text=text_diff(collection, name, hash_a, hash_b),
        results=results_diff(
            collection, name, hash_a, hash_b, run_a=run_a, run_b=run_b, loaded=every
        ),
    )


def _where(found: Recovered) -> str:
    return found.found_in or "unavailable"


def render(found: Diff) -> str:
    text = found.text
    lines = [
        f"# Diff: {found.component}",
        "",
        *(
            f"- {label}: `{ref}`, source_hash `{short(source_hash, 12)}`, text from {_where(side)}"
            for label, ref, source_hash, side in (
                ("A", found.ref_a, found.hash_a, text.a),
                ("B", found.ref_b, found.hash_b, text.b),
            )
        ),
        "",
        "## Text",
        "",
    ]
    if text.identical:
        lines += ["Identical: both versions have the same source_hash.", ""]
    else:
        for label, side in (("A", text.a), ("B", text.b)):
            if side.text is None:
                lines.append(
                    f"Version {label}'s text is unavailable. Searched: {', '.join(side.searched)}."
                )
                if side.note:
                    lines.append(f"Note: {side.note}.")
                lines.append("")
        if text.diff is not None:
            if text.description_changed:
                lines.append(
                    "> The frontmatter `description` changed. That changes how a harness routes "
                    "to the component, not only what it does once there."
                )
            else:
                lines.append("The frontmatter `description` is unchanged.")
            lines += ["", "```diff", text.diff.rstrip("\n"), "```", ""]
    lines += ["## Results", ""]
    comparison, unavailable = found.results.comparison, found.results.unavailable
    if comparison is not None:
        lines += [f"Runs: A `{comparison.a.run_id}`, B `{comparison.b.run_id}`.", ""]
        # Two levels down, so the comparison's own headings sit under this section.
        lines += [
            f"##{line}" if line.startswith("#") else line
            for line in compare.render(comparison).splitlines()
        ]
    elif unavailable is not None:
        lines += [f"Unavailable: {unavailable.reason}.", ""]
        for label, runs in (("A", unavailable.runs_a), ("B", unavailable.runs_b)):
            lines.append(f"- runs of version {label}: {', '.join(runs) or 'none'}")
        lines.append("")
    return "\n".join(lines).rstrip("\n") + "\n"


def output_dir(found: Diff) -> Path:
    slug = found.component.replace("/", "-").replace(":", "-")
    return (
        paths.evals_dir(found.collection)
        / "diff"
        / slug
        / f"{short(found.hash_a)}_vs_{short(found.hash_b)}"
    )


def write(found: Diff, out: Path | None = None) -> list[Path]:
    """`diff.md`, `diff.json`, and `text.diff` when there is a diff to write."""
    out = out or output_dir(found)
    out.mkdir(parents=True, exist_ok=True)
    written = [out / "diff.md", out / "diff.json"]
    written[0].write_text(render(found), encoding="utf-8")
    written[1].write_text(json.dumps(found.as_dict(), indent=2) + "\n", encoding="utf-8")
    patch = out / "text.diff"
    if found.text.diff is not None:
        patch.write_text(found.text.diff, encoding="utf-8")
        written.append(patch)
    else:
        patch.unlink(missing_ok=True)
    return written


def render_versions(name: str, found: list[Version], recoverable: dict[str, bool]) -> str:
    lines = [
        f"Versions of {name}, oldest first:",
        "",
        "| version | first seen | text | proposals | runs | current |",
        "|---|---|---|---|---|---|",
    ]
    for version in found:
        made = [f"candidate of {p}" for p in version.produced_by]
        made += [f"base of {p}" for p in version.base_of]
        lines.append(
            f"| `{short(version.source_hash, 12)}` | {version.first_seen or '-'} | "
            f"{'yes' if recoverable.get(version.source_hash) else 'no'} | "
            f"{', '.join(made) or '-'} | {len(version.runs)} | "
            f"{'yes' if version.current else ''} |"
        )
    return "\n".join(lines) + "\n"
