"""Frontmatter parsing and round-tripping."""

from __future__ import annotations

import pytest

from wikiskill.frontmatter import FrontmatterError, parse


def test_parses_meta_and_body():
    doc = parse("---\nname: x\ndescription: d\n---\n\nbody here\n")
    assert doc.meta == {"name": "x", "description": "d"}
    assert doc.body == "body here\n"


def test_block_scalar_description_survives():
    doc = parse("---\ndescription: >\n  one line\n  and another\n---\n\nbody\n")
    assert doc.meta["description"] == "one line and another"


def test_render_round_trips_the_body():
    text = "---\nname: x\ndescription: d\n---\n\n# Heading\n\nparagraph\n"
    doc = parse(text)
    assert parse(doc.render()).body == doc.body


def test_render_keeps_key_order():
    doc = parse("---\ndescription: d\nname: x\n---\n\nbody\n")
    rendered = doc.render({"name": "x", "mode": "subagent", "description": "d"})
    assert rendered.index("name:") < rendered.index("mode:") < rendered.index("description:")


def test_a_body_with_a_fence_is_not_truncated():
    doc = parse("---\nname: x\n---\n\nbefore\n\n---\n\nafter\n")
    assert "after" in doc.body


@pytest.mark.parametrize(
    "text, expected",
    [
        ("no frontmatter here", "must start with"),
        ("---\nname: x\n", "unterminated frontmatter"),
        ("---\n- a\n- b\n---\n\nbody\n", "must be a mapping"),
        ("---\nname: x\n  stray: indent\n---\n\nbody\n", "not valid YAML"),
    ],
)
def test_bad_frontmatter_is_rejected_with_a_reason(text, expected):
    with pytest.raises(FrontmatterError, match=expected):
        parse(text)


# --------------------------------------------------------------------------- lenient reading


def test_a_hint_claude_code_accepts_is_read_as_plain_text():
    """`[aspects] — e.g. ...` is a flow sequence followed by stray text to YAML, not to Claude Code."""
    text = (
        "---\n"
        "description: Run a review\n"
        'argument-hint: [aspects] — e.g. "code errors" or "all"\n'
        "allowed-tools: Bash(git diff:*), Read\n"
        "---\n\nbody\n"
    )
    doc = parse(text)
    assert doc.meta["argument-hint"] == '[aspects] — e.g. "code errors" or "all"'
    assert doc.meta["allowed-tools"] == "Bash(git diff:*), Read"
    assert doc.repaired == ("argument-hint",)


def test_a_repaired_value_keeps_its_single_quotes():
    doc = parse("---\nargument-hint: [x] it's here\n---\n\nbody\n")
    assert doc.meta["argument-hint"] == "[x] it's here"


def test_a_block_scalar_beside_a_repaired_line_is_left_alone():
    doc = parse("---\ndescription: >\n  one\n  two\nargument-hint: [p] text\n---\n\nbody\n")
    assert doc.meta["description"] == "one two\n"
    assert doc.repaired == ("argument-hint",)


def test_valid_frontmatter_reports_no_repair():
    assert parse("---\nargument-hint: [path]\n---\n\nbody\n").repaired == ()


def test_a_repaired_document_renders_as_valid_yaml():
    doc = parse("---\nname: x\nargument-hint: [p] text\n---\n\nbody\n")
    again = parse(doc.render())
    assert again.repaired == ()
    assert again.meta == doc.meta
