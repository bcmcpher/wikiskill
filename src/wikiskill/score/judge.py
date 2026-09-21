"""The rubric judge: the last and least authoritative thing in a run.

Verifiers decide pass or fail. A judge scores only its own dimensions, and its score never changes
the pass rate — otherwise a run's headline number would move with a model's mood. What it adds is
the dimensions a deterministic check cannot express.

Three rules make its answer worth reading at all, and all three are enforced here rather than
documented:

- **Blind.** The judge is never shown the task's expected route. It sees the rubric, the artifacts,
  and the final answer, and nothing that tells it what the right skill was.
- **Not a model under test.** A model grading its own output is not a measurement. The manifest
  check refuses that at load time; `refuse_self_judging` refuses it again here, because the models
  can also come from `--models` on the command line.
- **Its own endpoint.** The judge role carries its own `base_url` and model, so a suite comparing
  local models is not also changing its own grader.
"""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..rubric import Dimension, Rubric
from ..runner.preflight import Endpoint, request_json

#: A judge reads; it does not explore. Enough of the workdir to score an artifact, not so much that
#: a large tree pushes the rubric out of the context window.
MAX_FILES = 40
MAX_FILE_BYTES = 4000
MAX_ANSWER_CHARS = 8000

DEFAULT_TIMEOUT_S = 300

#: What a split panel is called when three judges cannot agree and no level has a majority.
SPLIT = "split"


class JudgeError(Exception):
    """The judge could not be consulted. Never a verdict about the work."""


@dataclass(frozen=True)
class DimensionScore:
    dimension: str
    level: str
    reason: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {"dimension": self.dimension, "level": self.level, "reason": self.reason}


@dataclass(frozen=True)
class Opinion:
    """One judge's whole answer."""

    model: str
    scores: tuple[DimensionScore, ...] = ()
    error: str | None = None

    def level(self, dimension_id: str) -> str | None:
        return self.said(dimension_id)[0]

    def said(self, dimension_id: str) -> tuple[str | None, str]:
        """This judge's level for a dimension and the words it gave for it."""
        for score in self.scores:
            if score.dimension == dimension_id:
                return score.level, score.reason
        return None, ""


@dataclass
class Judgement:
    """Every judge's answer, and what the panel settled on per dimension."""

    rubric: str
    model: str
    opinions: list[Opinion] = field(default_factory=list)
    consensus: list[DimensionScore] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "rubric": self.rubric,
            "judge_model": self.model,
            "judges": len(self.opinions),
            "consensus": [score.as_dict() for score in self.consensus],
            "opinions": [
                {"scores": [s.as_dict() for s in opinion.scores], "error": opinion.error}
                for opinion in self.opinions
            ],
        }


# --------------------------------------------------------------------------- conflicts


def refuse_self_judging(judge_model: str, models: Sequence[str]) -> None:
    """Refuse a judge that is also a model under test, whatever named it."""
    bare = judge_model.rsplit("/", 1)[-1].strip().lower()
    for model in models:
        if model.rsplit("/", 1)[-1].strip().lower() == bare:
            raise JudgeError(
                f"the judge model {judge_model!r} is also under test (as {model!r}); a model "
                "grading its own output is not a measurement"
            )


# --------------------------------------------------------------------------- the prompt


def describe(rubric: Rubric) -> str:
    """The rubric as the judge sees it: dimensions, what to look at, and the anchors."""
    lines = [f"Rubric: {rubric.id}", ""]
    for dimension in rubric.dimensions:
        lines.append(f"## {dimension.id} ({dimension.kind})")
        if dimension.evidence:
            lines.append(f"What to look at: {dimension.evidence}")
        lines.append("Levels, worst first:")
        lines += [f"  - {name}: {text}" for name, text in dimension.anchors]
        lines.append("")
    if rubric.notes:
        lines.append("The rubric's author added:")
        lines += [f"  - {note}" for note in rubric.notes]
    return "\n".join(lines).strip()


def artifacts(workdir: Path | None) -> str:
    """What the run left on disk, truncated so a big tree cannot crowd out the rubric."""
    if workdir is None or not workdir.is_dir():
        return "(the run left no working directory)"
    files = sorted(
        path
        for path in workdir.rglob("*")
        if path.is_file() and ".git" not in path.relative_to(workdir).parts
    )
    if not files:
        return "(the working directory is empty)"

    chunks = []
    for path in files[:MAX_FILES]:
        name = path.relative_to(workdir)
        try:
            body = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            chunks.append(f"### {name}\n(unreadable: {exc})")
            continue
        clipped = body[:MAX_FILE_BYTES]
        suffix = "" if len(body) <= MAX_FILE_BYTES else f"\n... [{len(body)} bytes in total]"
        chunks.append(f"### {name}\n```\n{clipped}{suffix}\n```")
    if len(files) > MAX_FILES:
        chunks.append(f"... and {len(files) - MAX_FILES} more files")
    return "\n\n".join(chunks)


def prompt_for(rubric: Rubric, *, final_text: str, workdir: Path | None) -> list[dict[str, str]]:
    """The messages sent to the judge. Nothing here names the route the task expected."""
    system = (
        "You grade work against a rubric. Score every dimension by choosing exactly one of its "
        "levels, using the evidence given and nothing else. You are not told what approach was "
        "expected, and you must not guess at one: grade what is here. Reply with JSON only, as "
        '{"scores": [{"dimension": "<id>", "level": "<level>", "reason": "<one sentence>"}]}.'
    )
    answer = (final_text or "(the run produced no final answer)")[:MAX_ANSWER_CHARS]
    user = (
        f"{describe(rubric)}\n\n"
        f"# The final answer\n\n{answer}\n\n"
        f"# The files the work left behind\n\n{artifacts(workdir)}\n\n"
        f"Score these dimensions, all of them: {', '.join(d.id for d in rubric.dimensions)}."
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


# --------------------------------------------------------------------------- asking


def _content(completion: Any) -> str:
    if not isinstance(completion, dict):
        return ""
    for choice in completion.get("choices") or []:
        message = choice.get("message") or {}
        if isinstance(message.get("content"), str):
            return message["content"]
    return ""


def parse_reply(text: str, rubric: Rubric) -> tuple[DimensionScore, ...]:
    """The scores in a judge's reply, keeping only levels the rubric actually declares.

    Models fence their JSON, prepend a sentence, or invent a level. A reply that cannot be read at
    all raises; a reply that scores four of six dimensions yields four, and the missing two are
    visible as missing rather than filled in with a default.
    """
    body = text.strip()
    start, end = body.find("{"), body.rfind("}")
    if start == -1 or end <= start:
        raise JudgeError(f"the judge did not reply with JSON: {body[:200]!r}")
    try:
        parsed = json.loads(body[start : end + 1])
    except json.JSONDecodeError as exc:
        raise JudgeError(f"the judge's JSON is unreadable: {exc}") from exc

    raw_scores = parsed.get("scores") if isinstance(parsed, dict) else None
    if not isinstance(raw_scores, list):
        raise JudgeError("the judge's reply has no `scores` list")

    found = []
    for entry in raw_scores:
        if not isinstance(entry, dict):
            continue
        try:
            dimension = rubric.dimension(str(entry.get("dimension")))
        except KeyError:
            continue
        level = str(entry.get("level", "")).strip()
        if level not in dimension.levels:
            continue
        found.append(
            DimensionScore(
                dimension=dimension.id,
                level=level,
                reason=str(entry.get("reason") or "").strip(),
            )
        )
    return tuple(found)


def ask_once(
    rubric: Rubric,
    *,
    endpoint: Endpoint,
    model: str,
    final_text: str,
    workdir: Path | None,
    timeout_s: int = DEFAULT_TIMEOUT_S,
) -> Opinion:
    """One judge's opinion. A judge that cannot answer is recorded, not raised over."""
    payload = {
        "model": model.rsplit("/", 1)[-1],
        "messages": prompt_for(rubric, final_text=final_text, workdir=workdir),
        "temperature": 0,
        "stream": False,
    }
    try:
        status, body = request_json(
            f"{endpoint.root}/chat/completions",
            payload=payload,
            api_key=endpoint.api_key,
            timeout=timeout_s,
        )
    except OSError as exc:
        return Opinion(model=model, error=f"the judge endpoint is unreachable: {exc}")
    if status != 200:
        return Opinion(
            model=model, error=f"the judge endpoint answered {status}: {str(body)[:200]}"
        )
    try:
        return Opinion(model=model, scores=parse_reply(_content(body), rubric))
    except JudgeError as exc:
        return Opinion(model=model, error=str(exc))


# --------------------------------------------------------------------------- the panel


def settle(
    dimension: Dimension, levels: Sequence[str], reasons: Sequence[str] = ()
) -> DimensionScore | None:
    """What a panel settled on for one dimension.

    A majority wins. Without one the dimension is `split`, which is a real answer — three judges
    disagreeing about whether a ledger is complete is worth seeing, and averaging it away would
    hide it. A tie between two levels resolves to the worse of them, because a rubric exists to
    find problems and the benefit of the doubt is not the judge's to give.
    """
    said = [
        (level, reason)
        for level, reason in zip(levels, list(reasons) + [""] * len(levels), strict=False)
        if level in dimension.levels
    ]
    votes = [level for level, _ in said]
    if not votes:
        return None

    def spoken_for(level: str) -> str:
        """A judge's own words for the level that won. A summary of three is nobody's reasoning."""
        return next((reason for said_level, reason in said if said_level == level and reason), "")

    counts = Counter(votes)
    best = max(counts.values())
    leaders = [level for level, count in counts.items() if count == best]
    if len(leaders) == 1 or best * 2 > len(votes):
        return DimensionScore(
            dimension=dimension.id, level=leaders[0], reason=spoken_for(leaders[0])
        )
    if len(counts) == 2:
        worse = min(leaders, key=lambda level: dimension.rank(level) or 0)
        return DimensionScore(
            dimension=dimension.id, level=worse, reason="a tie, resolved to the worse level"
        )
    return DimensionScore(
        dimension=dimension.id, level=SPLIT, reason=f"judges said {', '.join(sorted(votes))}"
    )


def judge_task(
    rubric: Rubric,
    *,
    endpoint: Endpoint,
    model: str,
    final_text: str,
    workdir: Path | None,
    models_under_test: Sequence[str] = (),
    timeout_s: int = DEFAULT_TIMEOUT_S,
) -> Judgement:
    """Consult the panel the rubric asks for, and settle each dimension."""
    refuse_self_judging(model, models_under_test)

    judgement = Judgement(rubric=rubric.id, model=model)
    for _ in range(rubric.judges):
        judgement.opinions.append(
            ask_once(
                rubric,
                endpoint=endpoint,
                model=model,
                final_text=final_text,
                workdir=workdir,
                timeout_s=timeout_s,
            )
        )
    if all(opinion.error for opinion in judgement.opinions):
        raise JudgeError(judgement.opinions[0].error or "every judge failed")

    for dimension in rubric.dimensions:
        said = [opinion.said(dimension.id) for opinion in judgement.opinions]
        levels = [level for level, _ in said if level]
        reasons = [reason for level, reason in said if level]
        settled = settle(dimension, levels, reasons)
        if settled is not None:
            judgement.consensus.append(settled)
    return judgement
