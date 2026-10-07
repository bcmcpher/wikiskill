"""The shipped example manifest must be a working manifest, not decoration."""

from __future__ import annotations

import shutil
import tomllib
from pathlib import Path

import pytest

from wikiskill import collection as collection_mod
from wikiskill.collection import ManifestError

EXAMPLE = Path(__file__).resolve().parent.parent / "examples" / "collections"


@pytest.fixture(params=sorted(EXAMPLE.glob("*.toml")), ids=lambda p: p.stem)
def example(request):
    return request.param


def test_the_example_parses_and_validates(example):
    raw = tomllib.loads(example.read_text(encoding="utf-8"))
    parsed = collection_mod.parse(raw, expected_name=example.stem)
    assert parsed.name == example.stem
    assert parsed.sources
    assert any(parsed.watch.values())


def test_the_example_declares_an_open_model_alias_table(example):
    parsed = collection_mod.parse(tomllib.loads(example.read_text()), expected_name=example.stem)
    assert parsed.aliases["opencode"], "the primary target is open models under OpenCode"
    resolved = [parsed.resolve_alias("opencode", alias) for alias in parsed.aliases["opencode"]]
    assert all("/" in value for value in resolved)


def test_the_examples_claude_model_names_resolve_through_tiers(example):
    parsed = collection_mod.parse(tomllib.loads(example.read_text()), expected_name=example.stem)
    small = parsed.resolve_alias("opencode", "small")
    large = parsed.resolve_alias("opencode", "large")
    assert parsed.resolve_alias("opencode", "haiku") == small
    assert parsed.resolve_alias("opencode", "sonnet") == large
    assert parsed.resolve_alias("opencode", "opus") == large


def test_the_examples_judge_is_not_a_model_under_test(example):
    parsed = collection_mod.parse(tomllib.loads(example.read_text()), expected_name=example.stem)
    assert collection_mod.judge_target_conflicts(parsed) == []


def test_copying_the_example_into_place_gives_a_loadable_collection(xdg, example, tmp_path):
    """What the file's own instructions tell a user to do must work."""
    destination = xdg["config"] / "wikiskill" / "collections" / example.name
    destination.parent.mkdir(parents=True, exist_ok=True)
    raw = tomllib.loads(example.read_text(encoding="utf-8"))
    plugin, skill = raw["watch"]["skills"][0].split("/")
    source = tmp_path / "plugins"
    (source / plugin / "skills" / skill).mkdir(parents=True)
    (source / plugin / "skills" / skill / "SKILL.md").write_text(
        f"---\nname: {skill}\ndescription: d\n---\n\nbody\n", encoding="utf-8"
    )
    shutil.copy(example, destination)
    destination.write_text(
        destination.read_text().replace(raw["sources"][0]["path"], str(source)),
        encoding="utf-8",
    )

    loaded = collection_mod.load(example.stem)

    assert loaded.sources[0].path == source
    assert [c.name for c in loaded.watched()] == [f"{plugin}/{skill}"]
    # The rest of the watch list is genuinely absent from this stub source.
    assert loaded.unresolved()


def test_the_example_is_rejected_if_its_judge_becomes_a_target(example):
    raw = tomllib.loads(example.read_text())
    judge = raw["roles"]["judge"]["model"]
    raw.setdefault("targets", {})["opencode"] = [judge]
    with pytest.raises(ManifestError, match="must not be a model under test"):
        collection_mod.parse(raw, expected_name=example.stem)
