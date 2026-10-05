"""The experience wiki: persistent, scoped pattern pages, written only from validated output.

The maintainer model proposes; this module decides what reaches disk. Every create, update and
index entry is checked against the evidence the maintainer was actually shown, and a pattern's
scope — which models, which harnesses, which version of the component — is computed here from the
evidence it cites, never taken from the model's word for it.

The wiki is a git repository per collection. Nothing is ever rolled back: a rejected proposal adds a
`skill-impact.md` entry and leaves the patterns as they were, and a review whose output never
validated adds a `log.md` entry and nothing else.

`.watermark.json` records, per component, the evidence a successful review was shown, so the next
review samples only what is new. It is written in the same commit as the patterns it produced.
"""

from __future__ import annotations

import json
import re
import subprocess
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from . import paths, rawlog
from .frontmatter import Document
from .frontmatter import read as read_frontmatter

INDEX, LOG, IMPACT = "index.md", "log.md", "skill-impact.md"
PATTERNS, COMPONENTS = "patterns", "components"
WATERMARK = ".watermark.json"
SUPERSEDED = "superseded"
HISTORY = "## History"


class WikiError(Exception):
    """The wiki could not be read or written."""


@dataclass(frozen=True)
class Evidence:
    """One piece of evidence the maintainer was shown, under the id it was shown as."""

    id: str
    component: str
    model: str
    harness: str
    source_hash: str | None
    ref: dict[str, Any]


@dataclass
class Applied:
    created: list[str] = field(default_factory=list)
    updated: list[str] = field(default_factory=list)
    superseded: list[str] = field(default_factory=list)
    committed: bool = False
    warnings: list[str] = field(default_factory=list)


# --------------------------------------------------------------------------- layout


def wiki_root(collection: str) -> Path:
    return paths.wiki_dir(collection)


def ensure(collection: str) -> Path:
    """Create the wiki layout and its git repository if they are not there yet."""
    root = wiki_root(collection)
    (root / PATTERNS).mkdir(parents=True, exist_ok=True)
    for name, heading in (
        (INDEX, "# Wiki index\n"),
        (LOG, "# Wiki log\n\nOne entry per review, newest last.\n"),
        (IMPACT, "# Skill impact\n\nOne entry per decision on a proposal, newest last.\n"),
    ):
        if not (root / name).exists():
            (root / name).write_text(heading, encoding="utf-8")
    if not (root / ".git").exists():
        _git(root, "init", "--quiet")
    return root


def patterns(collection: str, component: str | None = None) -> dict[str, Document]:
    """Every pattern page, or one component's, by slug."""
    directory = wiki_root(collection) / PATTERNS
    found = {}
    if not directory.is_dir():
        return found
    for path in sorted(directory.glob("*.md")):
        document = read_frontmatter(path)
        if component is None or document.meta.get("component") == component:
            found[path.stem] = document
    return found


def impact_entries(collection: str, component: str) -> list[str]:
    """This component's `skill-impact.md` entries, oldest first, each as written."""
    path = wiki_root(collection) / IMPACT
    if not path.is_file():
        return []
    sections = re.split(r"(?m)^(?=## )", path.read_text(encoding="utf-8"))
    marker = f"- component: `{component}`"
    return [s.strip() for s in sections if s.startswith("## ") and marker in s]


# --------------------------------------------------------------------------- validation


def load_schema() -> dict[str, Any]:
    return json.loads(paths.packaged_data("maintainer-schema").read_text(encoding="utf-8"))


def validate(
    output: Any,
    *,
    component: str,
    evidence: Mapping[str, Evidence],
    existing: Iterable[str] | Mapping[str, Mapping[str, Any]],
    taken: Iterable[str] = (),
) -> list[str]:
    """Every reason the maintainer's output cannot be applied, each one actionable.

    ``existing`` is this component's patterns, by slug, or by slug to their frontmatter: the
    frontmatter says which are superseded and what scope a pattern already has. ``taken`` is every
    slug in the wiki, since a slug is a file name and two components cannot share one.
    """
    validator = Draft202012Validator(load_schema())
    problems = [
        f"{'/'.join(str(p) for p in error.absolute_path) or '(top level)'}: {error.message}"
        for error in sorted(validator.iter_errors(output), key=lambda e: list(e.absolute_path))
    ]
    if problems:
        return problems

    metas: dict[str, Mapping[str, Any]] = (
        dict(existing) if isinstance(existing, Mapping) else {slug: {} for slug in existing}
    )
    existing = set(metas)
    taken = set(taken) | existing
    created: set[str] = set()
    for index, entry in enumerate(output["create"]):
        slug = entry["slug"]
        if slug in taken:
            problems.append(
                f"create/{index}: pattern {slug!r} already exists; put new evidence under `update`"
            )
        if slug in created:
            problems.append(f"create/{index}: pattern {slug!r} is created twice")
        created.add(slug)
        problems.extend(_unknown_evidence(f"create/{index}", entry["evidence"], evidence))
        problems.extend(_unearned_universal(f"create/{index}", entry, evidence, {}))
    retired, revived = set(), set()
    for index, entry in enumerate(output["update"]):
        if entry["slug"] not in existing:
            problems.append(
                f"update/{index}: there is no pattern {entry['slug']!r} for {component}; existing "
                f"ones are: {', '.join(sorted(existing)) or 'none'}"
            )
        problems.extend(_unknown_evidence(f"update/{index}", entry["evidence"], evidence))
        problems.extend(
            _unearned_universal(f"update/{index}", entry, evidence, metas.get(entry["slug"]) or {})
        )
        if entry.get("status") == SUPERSEDED:
            retired.add(entry["slug"])
        elif entry.get("status") == "active":
            revived.add(entry["slug"])

    active = {slug for slug, meta in metas.items() if meta.get("status") != SUPERSEDED}
    expected = (active | created | revived) - retired
    listed = set(output["index"])
    if listed != expected:
        missing, extra = sorted(expected - listed), sorted(listed - expected)
        if missing:
            problems.append(f"index: missing a summary for {', '.join(missing)}")
        if extra:
            problems.append(
                "index: summarises patterns that do not exist or are superseded: "
                + ", ".join(extra)
            )
    return problems


def _unearned_universal(
    where: str, entry: Mapping[str, Any], known: Mapping[str, Evidence], meta: Mapping[str, Any]
) -> list[str]:
    """A `universal` claim the evidence does not support: one model under one harness."""
    if not entry.get("universal"):
        return []
    cited = [known[e] for e in entry["evidence"] if e in known]
    models = {e.model for e in cited} | set(meta.get("models") or [])
    harnesses = {e.harness for e in cited} | set(meta.get("harnesses") or [])
    if len(models) > 1 or len(harnesses) > 1:
        return []
    return [
        (
            f"{where}: `universal` needs evidence from at least two models or two harnesses, but "
            f"{entry['slug']!r} has only {', '.join(sorted(models)) or 'no model'} under "
            f"{', '.join(sorted(harnesses)) or 'no harness'}; drop the claim"
        )
    ]


def _unknown_evidence(where: str, cited: Iterable[str], known: Mapping[str, Any]) -> list[str]:
    unknown = [e for e in cited if e not in known]
    if not unknown:
        return []
    return [f"{where}: cites evidence that was not given: {', '.join(unknown)}"]


def parse_reply(text: str) -> Any:
    """The JSON object in a model's reply: thinking stripped, code fences tolerated."""
    body = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()
    start, end = body.find("{"), body.rfind("}")
    if start == -1 or end <= start:
        raise WikiError(f"the reply holds no JSON object: {body[:200]!r}")
    try:
        return json.loads(body[start : end + 1])
    except json.JSONDecodeError as exc:
        raise WikiError(f"the reply's JSON is unreadable: {exc}") from exc


# --------------------------------------------------------------------------- applying


def apply(
    collection: str,
    output: dict[str, Any],
    *,
    component: str,
    evidence: Mapping[str, Evidence],
    maintainer: str,
    runs: Iterable[str] = (),
    shown: Mapping[str, Any] | None = None,
) -> Applied:
    """Write validated output into the wiki and commit it. Call `validate` first.

    ``shown`` is the evidence the maintainer saw, as watermark keys; it is marked processed in the
    same commit.
    """
    root = ensure(collection)
    applied = Applied()
    now = rawlog.now_ts()

    for entry in output["create"]:
        cited = [evidence[e] for e in entry["evidence"]]
        meta = {
            "slug": entry["slug"],
            "title": entry["title"],
            "component": component,
            "cause": entry["cause"],
            "trigger": entry["trigger"],
            **_scope(cited),
            "universal": bool(entry.get("universal")),
            "status": "active",
            "evidence": [e.ref for e in cited],
            "created": now,
            "updated": now,
            "maintainer": maintainer,
        }
        body = f"\n## Observation\n\n{entry['observation'].strip()}\n"
        if entry.get("suggestion", "").strip():
            body += f"\n## Suggestion\n\n{entry['suggestion'].strip()}\n"
        body += "\n## Updates\n"
        path = root / PATTERNS / f"{entry['slug']}.md"
        path.write_text(Document(meta=meta, body=body).render(), encoding="utf-8")
        applied.created.append(entry["slug"])

    for entry in output["update"]:
        path = root / PATTERNS / f"{entry['slug']}.md"
        document = read_frontmatter(path)
        meta = dict(document.meta)
        cited = [evidence[e] for e in entry["evidence"]]
        refs = list(meta.get("evidence") or [])
        refs += [e.ref for e in cited if e.ref not in refs]
        meta["evidence"] = refs
        previous = _scope_from_meta(meta)
        merged = _scope(cited)
        for key in ("models", "harnesses", "source_hashes"):
            meta[key] = sorted(set(previous[key]) | set(merged[key]))
        meta["updated"] = now
        if "universal" in entry:
            meta["universal"] = entry["universal"]
        if "status" in entry:
            meta["status"] = entry["status"]
        if entry.get("status") == SUPERSEDED:
            applied.superseded.append(entry["slug"])
        refs_text = ", ".join(_ref_label(e.ref) for e in cited)
        marker = " Superseded." if entry.get("status") == SUPERSEDED else ""
        note = f"- {now}: {entry['observation'].strip()}{marker} ({refs_text})"
        body = document.body.rstrip() + f"\n\n{note}\n"
        path.write_text(Document(meta=meta, body=body).render(), encoding="utf-8")
        applied.updated.append(entry["slug"])

    _write_index(root, output["index"], collection)
    changes = (
        f"created {', '.join(applied.created) or 'none'}; "
        f"updated {', '.join(applied.updated) or 'none'}"
    )
    _write_component(root, collection, component, f"- {now}: review by {maintainer}: {changes}")
    if shown:
        _advance(root, component, shown)
    runs_text = ", ".join(f"`{r}`" for r in runs) or "none"
    with (root / LOG).open("a", encoding="utf-8") as log:
        log.write(
            f"\n## {now}: review of `{component}` by {maintainer}\n\n{output['log'].strip()}\n\n"
            f"- runs: {runs_text}\n"
            f"- created: {', '.join(applied.created) or 'none'}\n"
            f"- updated: {', '.join(applied.updated) or 'none'}\n"
            f"- superseded: {', '.join(applied.superseded) or 'none'}\n"
        )
    applied.committed = commit(
        root,
        f"review {component}: {len(applied.created)} created, {len(applied.updated)} updated",
        applied.warnings,
    )
    return applied


def record_failure(
    collection: str, component: str, *, maintainer: str, attempts: int, problems: Iterable[str]
) -> bool:
    """Log a review whose output never validated, and commit that alone. Returns whether it did."""
    root = ensure(collection)
    listed = "\n".join(f"- {problem}" for problem in problems) or "- no problem recorded"
    with (root / LOG).open("a", encoding="utf-8") as log:
        log.write(
            f"\n## {rawlog.now_ts()}: review of `{component}` by {maintainer} failed\n\n"
            f"Nothing was applied after {attempts} attempt(s). The last problems:\n\n{listed}\n"
        )
    return commit(root, f"review {component}: failed after {attempts} attempt(s)")


# --------------------------------------------------------------------------- watermark


def watermark(collection: str) -> dict[str, dict[str, Any]]:
    """Per component, the evidence reviews have been shown: eval unit keys and live sessions."""
    path = wiki_root(collection) / WATERMARK
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise WikiError(f"{path} is unreadable: {exc}") from exc
    return data if isinstance(data, dict) else {}


def processed(collection: str, component: str) -> tuple[set[str], dict[str, str]]:
    """The eval units, and each live session's last shown event, already reviewed."""
    entry = watermark(collection).get(component) or {}
    return set(entry.get("eval") or []), dict(entry.get("sessions") or {})


def _advance(root: Path, component: str, shown: Mapping[str, Any]) -> None:
    path = root / WATERMARK
    data = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    entry = data.setdefault(component, {"eval": [], "sessions": {}})
    entry["eval"] = sorted(set(entry.get("eval") or []) | set(shown.get("eval") or []))
    entry["sessions"] = {**(entry.get("sessions") or {}), **(shown.get("sessions") or {})}
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


# --------------------------------------------------------------------------- component pages


def component_page(collection: str, component: str) -> Path:
    return wiki_root(collection) / COMPONENTS / f"{component.replace('/', '-')}.md"


def _write_component(root: Path, collection: str, component: str, history_line: str) -> None:
    """Regenerate a component's pattern table and append to its history.

    Created with the component's first pattern; a component with none has no page.
    """
    own = patterns(collection, component)
    path = component_page(collection, component)
    if not own and not path.exists():
        return
    history = ""
    if path.exists():
        _, _, history = path.read_text(encoding="utf-8").partition(HISTORY + "\n")
    rows = [
        f"| [{slug}](../{PATTERNS}/{slug}.md) | {meta.get('status', 'active')} | "
        f"{meta.get('cause')} | {', '.join(meta.get('models') or [])} | "
        f"{', '.join(meta.get('harnesses') or [])} | "
        f"{', '.join(_short(h) for h in meta.get('source_hashes') or [])} |"
        for slug, meta in ((slug, document.meta) for slug, document in sorted(own.items()))
    ]
    text = (
        f"# `{component}`\n\n"
        "What the wiki has learned about this component. The table is regenerated on every review; "
        "the history is appended.\n\n"
        "| pattern | status | cause | models | harnesses | observed on |\n"
        "|---|---|---|---|---|---|\n" + "\n".join(rows) + "\n\n"
        f"{HISTORY}\n{history.rstrip()}\n{history_line}\n"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _universal(meta: Mapping[str, Any]) -> str:
    return " (universal)" if meta.get("universal") else ""


def _short(digest: str) -> str:
    return digest.removeprefix("sha256:")[:12]


def _scope(cited: Iterable[Evidence]) -> dict[str, list[str]]:
    cited = list(cited)
    return {
        "models": sorted({e.model for e in cited}),
        "harnesses": sorted({e.harness for e in cited}),
        "source_hashes": sorted({e.source_hash for e in cited if e.source_hash}),
    }


def _scope_from_meta(meta: Mapping[str, Any]) -> dict[str, list[str]]:
    return {key: list(meta.get(key) or []) for key in ("models", "harnesses", "source_hashes")}


def _ref_label(ref: Mapping[str, Any]) -> str:
    if "run_id" in ref:
        return f"{ref['run_id']}/{ref['task_id']}/{ref['condition']}/r{ref['repeat']}"
    return str(ref.get("session_id", "?"))


def _write_index(root: Path, summaries: Mapping[str, str], collection: str) -> None:
    """Rebuild the index from every pattern page; this review's summaries replace older ones."""
    rows = []
    for slug, document in sorted(patterns(collection).items()):
        meta = document.meta
        if meta.get("status") == SUPERSEDED:
            continue
        summary = summaries.get(slug) or meta.get("summary") or meta.get("title", "")
        if slug in summaries:
            meta = {**meta, "summary": summaries[slug]}
            path = root / PATTERNS / f"{slug}.md"
            path.write_text(Document(meta=meta, body=document.body).render(), encoding="utf-8")
        rows.append(
            f"| [{slug}]({PATTERNS}/{slug}.md) | `{meta.get('component')}` | {meta.get('cause')} "
            f"| {', '.join(meta.get('models') or [])}{_universal(meta)} | {summary} |"
        )
    text = (
        "# Wiki index\n\n| pattern | component | cause | models | summary |\n"
        "|---|---|---|---|---|\n"
    )
    (root / INDEX).write_text(text + "\n".join(rows) + ("\n" if rows else ""), encoding="utf-8")


# --------------------------------------------------------------------------- git


def commit(root: Path, message: str, warnings: list[str] | None = None) -> bool:
    """Commit everything in the wiki. A failure is reported, never raised: the files are written."""
    try:
        _git(root, "add", "--all")
        status = _git(root, "status", "--porcelain")
        if not status.strip():
            return False
        _git(root, "commit", "--quiet", "-m", message)
        return True
    except WikiError as exc:
        if warnings is not None:
            warnings.append(f"the wiki was written but not committed: {exc}")
        return False


def _git(root: Path, *args: str) -> str:
    try:
        done = subprocess.run(
            ["git", "-C", str(root), *args],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise WikiError(f"git {' '.join(args)}: {exc}") from exc
    if done.returncode != 0:
        raise WikiError(f"git {' '.join(args)}: {done.stderr.strip() or done.stdout.strip()}")
    return done.stdout
