"""Propose one change to one component, grounded in its wiki patterns. Never apply it.

Started only by the user. The proposer sees the component's full text, its active patterns, the
evidence those patterns were drawn from, and the component's earlier `skill-impact.md` entries. It
answers with either `no_action` or a small set of exact find-and-replace edits. Edits rather than a
diff, because a small model reproduces a sentence far more reliably than it counts diff hunk lines.

Before anything is written, the reply is held to what it was shown:
- it names the one component it was asked about
- it cites patterns of that component, and enough of the evidence labels it was shown, and no others
- the text it adds carries no evaluation content: task ids, verifier literals, rubric anchors, or
  long user notes
- model-specific guidance is marked, and rests on patterns scoped to those models

From the edits wikiskill writes the patch itself, checks that it applies to the source repository
with `git apply --check` (which writes nothing), and saves it under `wiki/proposals/<id>/` for the
user. What happens to it next is `gate`'s business.
"""

from __future__ import annotations

import difflib
import json
import re
import subprocess
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from . import names, paths, rawlog, review, wiki
from . import rubric as rubric_mod
from . import suite as suite_mod
from .collection import Collection
from .errors import WikiskillError
from .frontmatter import FrontmatterError
from .frontmatter import parse as parse_frontmatter
from .frontmatter import read as read_frontmatter
from .review import DEFAULT_RETRIES
from .roles import Ask
from .runner.base import new_run_id

PROPOSALS = "proposals"
PATTERN_TEXT_LIMIT = 6_000
IMPACT_TEXT_LIMIT = 4_000
#: As many traces as WikiSkill's proposer must read, lowered to what was shown when fewer exist.
MIN_EVIDENCE = 4
#: Evidence items behind model-specific guidance, across the patterns it addresses.
MIN_SCOPED_EVIDENCE = 3
#: Leak thresholds: shared words in a row, and characters in a verifier literal.
LEAK_WORDS = 8
LEAK_CHARS = 8
#: Notes shorter than this are a sentence anyone might write; longer ones are the user's own text.
NOTE_LEAK_LENGTH = 200

#: What the proposer must return. Kept here rather than in `schemas/` because nothing outside this
#: module reads it, and the edits are resolved against a file before anything is written.
REPLY_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["action", "component", "reason", "patterns"],
    "properties": {
        "action": {"enum": ["patch", "no_action"]},
        "component": {"type": "string", "minLength": 1},
        "reason": {"type": "string", "minLength": 1},
        "patterns": {"type": "array", "items": {"type": "string"}, "uniqueItems": True},
        "evidence": {"type": "array", "items": {"type": "string"}, "uniqueItems": True},
        "models": {"type": "array", "items": {"type": "string", "minLength": 1}},
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


class RefineError(WikiskillError):
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


@dataclass
class Leaks:
    """Evaluation content a proposal must not carry into a skill, each with where it came from."""

    task_ids: dict[str, str] = field(default_factory=dict)
    literals: dict[str, str] = field(default_factory=dict)
    #: (where, text) for rubric anchors and long notes, compared by shared runs of words.
    passages: list[tuple[str, str]] = field(default_factory=list)


@dataclass
class Context:
    """Everything one proposal is made from and checked against."""

    component: str
    path: Path
    text: str
    source_hash: str | None
    patterns: dict[str, Any]
    evidence: review.Digest
    impact: list[str]
    leaks: Leaks
    prompt: str = ""
    sample_id: str | None = None


# --------------------------------------------------------------------------- context


def proposer_prompt() -> str:
    path = paths.source_tree() / "agents" / "wikiskill-proposer.md"
    return read_frontmatter(path).body.strip()


def component_file(collection: Collection, component: str) -> Path:
    found = collection.component(component)
    if found is None:
        raise RefineError(f"{component!r} is not a component of collection {collection.name!r}")
    return found.path


def active_patterns(collection: str, component: str) -> dict[str, Any]:
    return {
        slug: doc
        for slug, doc in wiki.patterns(collection, component).items()
        if doc.meta.get("status") != wiki.SUPERSEDED
    }


def context(collection: Collection, component: str, *, budget: int | None = None) -> Context:
    """What the proposer is shown, and what its reply is checked against."""
    path = component_file(collection, component)
    text = path.read_text(encoding="utf-8")
    known = active_patterns(collection.name, component)
    refs: list[dict[str, Any]] = []
    for document in known.values():
        refs += [r for r in document.meta.get("evidence") or [] if r not in refs]
    budget = budget if budget is not None else review.budget_for(collection, "proposer")
    found = context_from(
        component,
        path=path,
        text=text,
        patterns=known,
        evidence=review.cited_digest(collection, component, refs, budget=budget),
        impact=wiki.impact_entries(collection.name, component),
        leaks=leaks(collection, component),
    )
    found.prompt = prompt(found)
    return found


def context_from(component: str, **parts: Any) -> Context:
    return Context(component=component, source_hash=rawlog.file_hash(parts["path"]), **parts)


def prompt(found: Context) -> str:
    lines = [
        f"# Component: {found.component}",
        "",
        "## Its full text",
        "",
        "````",
        found.text,
        "````",
        "",
        "## Its wiki patterns",
        "",
    ]
    used = 0
    for slug, document in sorted(found.patterns.items()):
        meta = document.meta
        block = (
            f"### {slug}\n\ncause: {meta.get('cause')}; models: "
            f"{', '.join(meta.get('models') or [])}; evidence items: "
            f"{len(meta.get('evidence') or [])}; trigger: {meta.get('trigger')}\n\n"
            f"{document.body.strip()}\n"
        )
        if used + len(block) > PATTERN_TEXT_LIMIT:
            lines.append(f"(pattern {slug} omitted: over the length limit)")
            continue
        used += len(block)
        lines.append(block)
    if not found.patterns:
        lines.append("- none")
    shown = sorted(found.evidence.evidence)
    need = min(MIN_EVIDENCE, len(shown))
    lines += ["", "## The evidence these patterns were drawn from", ""]
    if shown:
        lines += [
            f"Cite at least {need} of these labels in `evidence`: {', '.join(shown)}.",
            "",
            found.evidence.text.strip(),
        ]
        if found.evidence.omitted:
            lines.append(f"\n({found.evidence.omitted} more did not fit and cannot be cited)")
    else:
        lines.append("- none is still on disk; `evidence` may be empty")
    lines += ["", "## Earlier decisions on this component", ""]
    history = "\n\n".join(found.impact)
    if len(history) > IMPACT_TEXT_LIMIT:
        history = "(older entries omitted)\n\n" + history[-IMPACT_TEXT_LIMIT:]
    lines.append(history or "- none")
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------------- leak sources


def leaks(collection: Collection, component: str) -> Leaks:
    """The evaluation content of every suite that evaluated the component, and its long notes."""
    found = Leaks()
    seen: set[str] = set()
    for run in review.component_runs(collection.name, component):
        suite_path = run.manifest.get("suite_path")
        if not suite_path or suite_path in seen:
            continue
        seen.add(suite_path)
        try:
            loaded = suite_mod.load(suite_path, collection=collection)
        except (suite_mod.SuiteError, OSError):
            continue
        _suite_leaks(loaded, found)
    for event in _notes(collection.name, component):
        text = str((event.get("payload") or {}).get("text") or "")
        if len(text) > NOTE_LEAK_LENGTH:
            found.passages.append((f"note {event.get('event_id', '?')}", text))
    return found


def _suite_leaks(loaded: suite_mod.Suite, found: Leaks) -> None:
    for task in loaded.tasks:
        if re.search(r"[-_0-9]", task.id):
            found.task_ids[task.id] = f"a task id of suite {loaded.name}"
        for verifier in task.verifiers:
            for part in re.split(r"\\.|[\^$.|?*+()\[\]{}]", verifier.pattern or ""):
                if len(part.strip()) >= LEAK_CHARS:
                    found.literals[part.strip()] = f"a verifier of {loaded.name}/{task.id}"
        if task.rubric:
            try:
                rubric = rubric_mod.load(loaded.root / task.rubric)
            except (rubric_mod.RubricError, OSError):
                continue
            for dimension in rubric.dimensions:
                for name, text in dimension.anchors:
                    where = f"rubric {rubric.id}, {dimension.id}/{name}"
                    found.passages.append((where, text))


def _notes(collection: str, component: str) -> Iterable[dict[str, Any]]:
    # Both sides bare, as review compares evidence: a note on any plugin's component of this name.
    bare = names.bare(component)
    for file in rawlog.log_files(paths.raw_dir(collection)):
        for event in rawlog.read_events(file):
            name = (event.get("component") or {}).get("name", "")
            if event.get("type") == "note" and names.bare(name) == bare:
                yield event


# --------------------------------------------------------------------------- validation


def validate(reply: Any, found: Context, *, allow_overlap: bool = False) -> list[str]:
    """Every reason a proposer reply cannot become a proposal."""
    validator = Draft202012Validator(REPLY_SCHEMA)
    problems = [
        f"{'/'.join(str(p) for p in error.absolute_path) or '(top level)'}: {error.message}"
        for error in validator.iter_errors(reply)
    ]
    if problems:
        return problems
    if reply["component"] != found.component:
        problems.append(
            f"component: this proposal is for {found.component} alone, not "
            f"{reply['component']}; one proposal changes one component"
        )
    known = sorted(found.patterns)
    unknown = [p for p in reply["patterns"] if p not in found.patterns]
    if unknown:
        problems.append(
            f"patterns: {', '.join(unknown)} are not patterns of this component; known: "
            f"{', '.join(known) or 'none'}"
        )
    if reply["action"] == "no_action":
        return problems
    if not reply["patterns"]:
        problems.append("patterns: a patch must cite at least one wiki pattern")
    problems += _evidence_problems(reply.get("evidence") or [], sorted(found.evidence.evidence))
    edits = reply.get("edits") or []
    if not edits:
        problems.append("edits: a patch needs at least one edit")
    for index, edit in enumerate(edits):
        count = found.text.count(edit["find"])
        if count != 1:
            where = "does not occur" if count == 0 else f"occurs {count} times"
            problems.append(
                f"edits/{index}: `find` {where} in the component's text; copy one exact, unique "
                "passage"
            )
        if edit["find"] == edit["replace"]:
            problems.append(f"edits/{index}: `replace` is identical to `find`")
    added = added_text(edits)
    if not allow_overlap:
        problems += leak_problems(added, found.leaks)
    problems += scope_problems(reply, found.patterns, added)
    return problems


def _evidence_problems(cited: Sequence[str], shown: Sequence[str]) -> list[str]:
    problems = []
    unshown = [label for label in cited if label not in shown]
    if unshown:
        problems.append(
            f"evidence: {', '.join(unshown)} were not shown to you; cite only "
            f"{', '.join(shown) or 'nothing'}"
        )
    need = min(MIN_EVIDENCE, len(shown))
    have = len([label for label in cited if label in shown])
    if have < need:
        problems.append(
            f"evidence: a patch must cite at least {need} of the evidence labels shown; it cites "
            f"{have}"
        )
    return problems


def added_text(edits: Sequence[Mapping[str, str]]) -> str:
    """The lines the edits add, without the passages they keep."""
    added = []
    for edit in edits:
        for line in difflib.ndiff(edit["find"].splitlines(), edit["replace"].splitlines()):
            if line.startswith("+ "):
                added.append(line[2:])
    return "\n".join(added)


def _words(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.lower())


def _shared_run(added: Sequence[str], other: Sequence[str], n: int = LEAK_WORDS) -> str | None:
    """The first run of at least ``n`` words the two share, as long as it goes on."""
    grams = {tuple(other[i : i + n]) for i in range(len(other) - n + 1)}
    for i in range(len(added) - n + 1):
        if tuple(added[i : i + n]) in grams:
            end = i + n
            while end < len(added) and tuple(added[end - n + 1 : end + 1]) in grams:
                end += 1
            return " ".join(added[i:end])
    return None


def leak_problems(added: str, found: Leaks) -> list[str]:
    """Evaluation content in the text a patch adds, each match named with where it came from."""
    problems = []
    for task_id, where in sorted(found.task_ids.items()):
        if re.search(rf"(?<![\w-]){re.escape(task_id)}(?![\w-])", added, re.IGNORECASE):
            problems.append(f"leak: the added text names `{task_id}`, {where}")
    lowered = added.lower()
    for literal, where in sorted(found.literals.items()):
        if literal.lower() in lowered:
            problems.append(f"leak: the added text contains `{literal}`, from {where}")
    words = _words(added)
    for where, text in found.passages:
        shared = _shared_run(words, _words(text))
        if shared:
            problems.append(f"leak: the added text shares `{shared}` with {where}")
    return problems


def model_names(model: str) -> set[str]:
    """The names a model goes by: `ollama/qwen3:1.7b`, `qwen3:1.7b`, and the family `qwen3`."""
    bare = names.model_id(model)
    return {model.lower(), bare.lower(), bare.split(":", 1)[0].lower()}


def scope_problems(reply: Mapping[str, Any], known: Mapping[str, Any], added: str) -> list[str]:
    """Model-specific guidance only when marked, and only on scoped, well-evidenced patterns."""
    marked = {m.lower() for m in reply.get("models") or []}
    cited = [known[slug] for slug in reply["patterns"] if slug in known]
    if not marked:
        seen = sorted({m for doc in known.values() for m in doc.meta.get("models") or []})
        named = sorted(
            {
                name
                for model in seen
                for name in model_names(model)
                if re.search(rf"(?<![\w.-]){re.escape(name)}(?![\w-])", added, re.IGNORECASE)
            }
        )
        if named:
            return [
                (
                    f"models: the added text names {', '.join(named)}; model-specific guidance "
                    "must list its models in `models`, or be written for every model"
                )
            ]
        return []
    problems = []
    for slug, document in zip(reply["patterns"], cited, strict=False):
        outside = [m for m in document.meta.get("models") or [] if not model_names(m) & marked]
        if outside:
            problems.append(
                f"models: pattern {slug} was also seen on {', '.join(outside)}, so it does not "
                "support guidance for the marked models alone"
            )
    items = sum(len(document.meta.get("evidence") or []) for document in cited)
    if items < MIN_SCOPED_EVIDENCE:
        problems.append(
            f"models: model-specific guidance rests on {items} evidence item(s); at least "
            f"{MIN_SCOPED_EVIDENCE} are needed"
        )
    return problems


def apply_edits(text: str, edits: Sequence[Mapping[str, str]]) -> str:
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


# --------------------------------------------------------------------------- persisted prompts


def save_prompt(collection: Collection, found: Context) -> tuple[str, Path]:
    """Persist a proposer prompt, so a reply written in the harness is checked against it."""
    sample_id = new_run_id()
    directory = review.samples_dir(collection.name) / sample_id
    directory.mkdir(parents=True)
    (directory / "prompt.md").write_text(found.prompt, encoding="utf-8")
    (directory / "instructions.md").write_text(proposer_prompt() + "\n", encoding="utf-8")
    evidence = {label: asdict(item) for label, item in found.evidence.evidence.items()}
    (directory / "evidence.json").write_text(json.dumps(evidence, indent=2) + "\n", "utf-8")
    meta = {
        "sample_id": sample_id,
        "kind": "refine",
        "collection": collection.name,
        "component": found.component,
        "source_hash": found.source_hash,
        "runs": found.evidence.runs,
        "budget": found.evidence.budget,
        "omitted": found.evidence.omitted,
        "patterns_seen": {
            slug: str(doc.meta.get("updated") or "")
            for slug, doc in wiki.patterns(collection.name, found.component).items()
        },
        "taken": rawlog.now_ts(),
    }
    (directory / "sample.json").write_text(json.dumps(meta, indent=2) + "\n", "utf-8")
    return sample_id, directory


def load_prompt(collection: Collection, component: str, sample: str) -> Context:
    """A persisted proposer prompt; refused when the component or its patterns have moved on."""
    try:
        shown = review.load_sample(collection, sample)
    except review.ReviewError as exc:
        raise RefineError(str(exc)) from exc
    directory = Path(sample)
    if not directory.is_dir():
        directory = review.samples_dir(collection.name) / sample
    meta = json.loads((directory / "sample.json").read_text(encoding="utf-8"))
    if meta.get("kind") != "refine" or shown.component != component:
        raise RefineError(f"{directory.name} is not a proposer prompt for {component}")
    found = context(collection, component, budget=shown.budget)
    if found.source_hash != meta.get("source_hash"):
        raise RefineError(
            f"{component} changed after prompt {directory.name} was taken; prepare a new one"
        )
    found.evidence, found.prompt, found.sample_id = shown, shown.text, directory.name
    return found


# --------------------------------------------------------------------------- refine


def refine(
    collection: Collection,
    component: str,
    *,
    ask: Ask,
    proposer: str,
    retries: int = DEFAULT_RETRIES,
    found: Context | None = None,
    allow_overlap: bool = False,
) -> Proposal:
    """Ask for one proposal, validate it, and write it as a patch. Nothing is ever applied."""
    found = found or context(collection, component)
    if not found.patterns:
        return Proposal(
            action="no_action",
            reason=f"the wiki holds no pattern for {component}; run `wikiskill review` first",
            patterns=[],
            attempts=0,
        )

    messages = [
        {"role": "system", "content": proposer_prompt()},
        {"role": "user", "content": found.prompt},
    ]
    problems: list[str] = []
    for attempt in range(1, retries + 2):
        answer = ask(messages)
        reply: dict[str, Any] = {}
        try:
            reply = wiki.parse_reply(answer)
            problems = validate(reply, found, allow_overlap=allow_overlap)
        except wiki.WikiError as exc:
            problems = [str(exc)]
        if not problems and reply["action"] == "patch":
            after = apply_edits(found.text, reply["edits"])
            diff = make_diff(found.path, found.text, after)
            refused = check_applies(found.path, diff)
            if refused:
                problems = [f"the patch would not apply to the source repository: {refused}"]
        if not problems:
            return _write(
                collection,
                reply,
                found=found,
                proposer=proposer,
                attempts=attempt,
                allow_overlap=allow_overlap,
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


def description_changed(before: str, after: str) -> bool:
    """Whether an edit moved the `description`, the text a harness routes on."""
    return _description(before) != _description(after)


def _description(text: str) -> Any:
    try:
        return parse_frontmatter(text).meta.get("description")
    except FrontmatterError:
        return None


def _write(
    collection: Collection,
    reply: dict[str, Any],
    *,
    found: Context,
    proposer: str,
    attempts: int,
    allow_overlap: bool,
) -> Proposal:
    proposal = Proposal(
        action=reply["action"],
        reason=reply["reason"],
        patterns=list(reply["patterns"]),
        attempts=attempts,
    )
    if reply["action"] == "no_action":
        return proposal

    component, path = found.component, found.path
    root = wiki.ensure(collection.name)
    proposal_id = next_id(collection.name)
    directory = root / PROPOSALS / proposal_id
    (directory / "rendered").mkdir(parents=True)
    after = apply_edits(found.text, reply["edits"])
    rendered = directory / "rendered" / path.name
    rendered.write_text(after, encoding="utf-8")
    proposal.diff = make_diff(path, found.text, after)
    proposal.directory = directory
    repo = repository_of(path)
    cited = {label: found.evidence.evidence[label] for label in reply.get("evidence") or []}

    (directory / "patch.diff").write_text(proposal.diff, encoding="utf-8")
    (directory / "proposal.json").write_text(json.dumps(reply, indent=2) + "\n", encoding="utf-8")
    meta = {
        "id": proposal_id,
        "component": component,
        "source_path": str(path),
        "repository": str(repo) if repo else None,
        "source_hash": found.source_hash,
        "candidate_hash": rawlog.file_hash(rendered),
        "description_changed": description_changed(found.text, after),
        "patterns": proposal.patterns,
        "evidence": {label: item.ref for label, item in cited.items()},
        "models": list(reply.get("models") or []),
        "reason": proposal.reason,
        "proposer": proposer,
        "prompt": found.sample_id,
        "allow_overlap": allow_overlap,
        "created": rawlog.now_ts(),
        "status": "proposed",
    }
    (directory / "meta.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    (directory / "preview.md").write_text(
        _preview(
            collection.name,
            proposal_id=proposal_id,
            meta=meta,
            reply=reply,
            diff=proposal.diff,
            repo=repo,
        ),
        encoding="utf-8",
    )
    wiki.commit(root, f"propose {proposal_id} for {component}")
    return proposal


def _preview(
    collection: str,
    *,
    proposal_id: str,
    meta: Mapping[str, Any],
    reply: Mapping[str, Any],
    diff: str,
    repo: Path | None,
) -> str:
    edits = [
        f"{i}. Replace\n\n   > {e['find'].strip()[:600]}\n\n   with\n\n   > "
        f"{e['replace'].strip()[:600] or '(nothing)'}\n"
        for i, e in enumerate(reply["edits"], 1)
    ]
    scope = ", ".join(meta["models"]) or "every model"
    return "\n".join(
        [
            f"# {proposal_id}: {meta['component']}",
            "",
            f"**Why:** {meta['reason']}",
            "",
            "**Patterns:** " + ", ".join(f"`{p}`" for p in meta["patterns"]),
            "",
            "**Evidence:** " + (", ".join(f"`{e}`" for e in meta["evidence"]) or "none on disk"),
            "",
            f"**For:** {scope}",
            "",
            "**Edits:**",
            "",
            *edits,
            "## Patch",
            "",
            "```diff",
            diff.rstrip(),
            "```",
            "",
            "Nothing has been applied. To test it without touching the source, run the suite at",
            "the current version and with the proposal, then replay and decide:",
            "",
            "```bash",
            f"wikiskill eval --suite <suite> --collection {collection} --models <models>",
            (
                f"wikiskill eval --suite <suite> --collection {collection} --models <models> "
                f"--proposal {proposal_id}"
            ),
            (
                f"wikiskill proposal replay {proposal_id} <baseline-run> <candidate-run> "
                f"--collection {collection}"
            ),
            (
                f"wikiskill proposal decide {proposal_id} accept|reject|withdraw --note <why> "
                f"--collection {collection}"
            ),
            "```",
            "",
            (
                f"To try it in the source yourself: `wikiskill proposal apply {proposal_id} "
                f"--collection {collection}`" + (" (add `--branch` for a branch)." if repo else ".")
            ),
            "",
        ]
    )
