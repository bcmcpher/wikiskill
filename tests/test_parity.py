"""The Python ports of redaction and the evaluation guard must agree with their TypeScript originals.

The cases live in `tests/fixtures/parity/`, and `harness/opencode/plugin/test/parity.test.ts` and
`harness/opencode/guard/test/parity.test.ts` run the same ones, so a case added here is checked on
both sides. A case marked `known_divergence` records each side's current output, so a fix to one
side fails here until the fixture says the two agree.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from conftest import FIXTURES
from wikiskill import guard, redact

REPO = Path(__file__).resolve().parents[1]
PARITY = FIXTURES / "parity"
REDACT = json.loads((PARITY / "redact.json").read_text(encoding="utf-8"))
GUARD = json.loads((PARITY / "guard.json").read_text(encoding="utf-8"))
REDACT_TS = REPO / "harness" / "opencode" / "plugin" / "wikiskill" / "redact.ts"


def expected(case):
    return case["expected"] if "known_divergence" not in case else case["python"]


def cases(fixture, section):
    return pytest.mark.parametrize(
        "case",
        fixture[section],
        ids=[c.get("name") or f"{c['subject']!r} ~ {c['pattern']!r}" for c in fixture[section]],
    )


def text_of(value):
    return value["repeat"] * value["times"] if isinstance(value, dict) else value


# --------------------------------------------------------------------------- redaction


@cases(REDACT, "redact")
def test_redact(case):
    text, found = redact.redact(case["text"], redact.env_secrets(case["env"]))
    assert {"text": text, "redactions": found} == expected(case)


@cases(REDACT, "env_secrets")
def test_env_secrets(case):
    assert redact.env_secrets(case["env"]) == expected(case)


@cases(REDACT, "redact_value")
def test_redact_value(case):
    value, found = redact.redact_value(case["value"])
    assert {"value": value, "redactions": found} == expected(case)


@cases(REDACT, "bound")
def test_bound(case):
    limited = redact.bound(text_of(case["text"]), case["limit"])
    assert {
        "text": limited.text,
        "length": limited.length,
        "truncated": limited.truncated,
    } == expected(case)


def _ts_patterns(source: str) -> list[tuple[str, str, str, int]]:
    """``(kind, source, flags, group)`` for each entry of `redact.ts`'s PATTERNS, read as text."""
    block = source[source.index("const PATTERNS") :]
    block = block[: block.index("\n]\n")]
    found = []
    for entry in re.finditer(r'kind:\s*"(\w+)",\s*re:\s*/', block):
        # Scan the regex literal: an escape takes two characters, and `/` inside a class is literal.
        i, in_class = entry.end(), False
        while True:
            char = block[i]
            if char == "\\":
                i += 2
                continue
            if char == "[":
                in_class = True
            elif char == "]":
                in_class = False
            elif char == "/" and not in_class:
                break
            i += 1
        literal = block[entry.end() : i]
        flags = re.match(r"[a-z]*", block[i + 1 :]).group(0)
        rest = block[i + 1 + len(flags) : block.index("}", i)]
        group = re.search(r"group:\s*(\d+)", rest)
        found.append((entry.group(1), literal, flags, int(group.group(1)) if group else 0))
    return found


def _normalised(pattern: str) -> str:
    """Escapes that mean the same in both dialects: `\\/` in a JS literal, `\\"` in a Python one."""
    return pattern.replace("\\/", "/").replace('\\"', '"').replace("\\'", "'")


def test_the_two_pattern_tables_are_the_same():
    ts = [
        (kind, _normalised(literal), "".join(sorted(set(flags) - {"g"})), group)
        for kind, literal, flags, group in _ts_patterns(REDACT_TS.read_text(encoding="utf-8"))
    ]
    py = [
        (kind, _normalised(p.pattern), "i" if p.flags & re.IGNORECASE else "", group)
        for kind, p, group in redact.PATTERNS
    ]
    assert len(ts) == len(redact.PATTERNS) == 10
    assert py == ts


# --------------------------------------------------------------------------- the guard


@pytest.mark.parametrize(
    "case", GUARD["matches"], ids=[f"{c['subject']!r} ~ {c['pattern']!r}" for c in GUARD["matches"]]
)
def test_matches(case):
    assert guard.matches(case["subject"], case["pattern"]) is expected(case)


@cases(GUARD, "commands_in")
def test_commands_in(case):
    assert guard.commands_in(case["args"]) == expected(case)


@cases(GUARD, "denial_for")
def test_denial_for(case):
    found = guard.denial_for(case["tool"], case["args"], case["deny"], case["tools"])
    assert (None if found is None else {"subject": found[0], "pattern": found[1]}) == expected(case)


@cases(GUARD, "parse_list")
def test_parse_list(case):
    assert guard.parse_list(case["raw"]) == expected(case)


@cases(GUARD, "parse_budget")
def test_parse_budget(case):
    assert guard.parse_budget(case["raw"]) == expected(case)


@cases(GUARD, "messages")
def test_refusal_messages(case):
    """Through `decide`, the path the hook takes, since the runners classify units by this text."""
    if "step" in case:
        reason = guard.STEP_EXHAUSTED.format(budget=case["step"])
    else:
        subject, pattern = case["blocked"]
        if subject.startswith("tool "):
            payload = {"tool_name": subject.removeprefix("tool "), "tool_input": {}}
            env = {"WIKISKILL_GUARD_TOOLS": json.dumps([pattern])}
        else:
            payload = {"tool_name": "Bash", "tool_input": {"command": subject}}
            env = {"WIKISKILL_GUARD_DENY": json.dumps([pattern])}
        reason = guard.decide(payload, env)
    assert reason == expected(case)


def test_every_divergence_says_why():
    for fixture in (REDACT, GUARD):
        for section, entries in fixture.items():
            if section.startswith("$"):
                continue
            for case in entries:
                if "known_divergence" in case:
                    assert case["known_divergence"].strip(), case
                    assert case["python"] != case["typescript"], case
                else:
                    assert "expected" in case, case


def test_the_fixtures_are_where_the_bun_suites_look():
    for package in ("plugin", "guard"):
        test = REPO / "harness" / "opencode" / package / "test" / "parity.test.ts"
        assert Path(test).is_file()
        assert "tests/fixtures/parity" in test.read_text(encoding="utf-8").replace('", "', "/")
