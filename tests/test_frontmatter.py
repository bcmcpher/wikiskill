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
        ("---\nname: [unclosed\n---\n\nbody\n", "not valid YAML"),
    ],
)
def test_bad_frontmatter_is_rejected_with_a_reason(text, expected):
    with pytest.raises(FrontmatterError, match=expected):
        parse(text)
