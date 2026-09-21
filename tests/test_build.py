"""Single-source build: one authored tree, one generated layout per harness."""

from __future__ import annotations

import pytest
import yaml

from conftest import SOURCE_FIXTURE
from wikiskill.build import BUILD_MARKER, BuildError, build
from wikiskill.collection import Collection, Source
from wikiskill.frontmatter import read as read_frontmatter


def collection_with_aliases(**aliases) -> Collection:
    return Collection(
        name="dsh",
        sources=(Source(path=SOURCE_FIXTURE, layout="opencode"),),
        watch={"skill": (), "agent": (), "command": ()},
        aliases={"opencode": dict(aliases)},
    )


@pytest.fixture
def built(tmp_path):
    return build(
        "opencode",
        collection=collection_with_aliases(maintainer="ollama/qwen3:30b-a3b"),
        source=SOURCE_FIXTURE,
        out_dir=tmp_path / "dist",
    )


def agent_meta(built, name):
    return read_frontmatter(built.out_dir / "agents" / f"{name}.md").meta


def test_every_source_component_is_generated(built):
    assert "skills/example-skill/SKILL.md" in built.relative()
    assert "agents/read-only-agent.md" in built.relative()
    assert "commands/example-command.md" in built.relative()


def test_a_source_change_reaches_the_built_layout(tmp_path):
    """The point of single-source: edit once, rebuild, and every harness has it."""
    source = tmp_path / "source"
    (source / "skills" / "s").mkdir(parents=True)
    main = source / "skills" / "s" / "SKILL.md"
    main.write_text("---\nname: s\ndescription: first\n---\n\noriginal\n", encoding="utf-8")

    first = build("opencode", source=source, out_dir=tmp_path / "d1")
    assert "original" in (first.out_dir / "skills" / "s" / "SKILL.md").read_text()

    main.write_text("---\nname: s\ndescription: first\n---\n\nrevised\n", encoding="utf-8")
    second = build("opencode", source=source, out_dir=tmp_path / "d2")
    assert "revised" in (second.out_dir / "skills" / "s" / "SKILL.md").read_text()


def test_supporting_material_travels_with_a_skill(built):
    assert (built.out_dir / "skills" / "example-skill" / "references" / "note.md").is_file()


def test_body_survives_the_build_unchanged(built):
    body = read_frontmatter(built.out_dir / "skills" / "example-skill" / "SKILL.md").body
    assert "Body text that must survive the build unchanged." in body


# --------------------------------------------------------------------------- agents


def test_an_opencode_agent_is_a_subagent(built):
    assert agent_meta(built, "read-only-agent")["mode"] == "subagent"


def test_capabilities_become_a_deny_by_default_permission_block(built):
    """`capabilities: [read, search]` must deny edit, bash and web access."""
    permission = agent_meta(built, "read-only-agent")["permission"]
    assert permission == {"bash": "deny", "edit": "deny", "webfetch": "deny"}


def test_granted_capabilities_are_allowed(built):
    permission = agent_meta(built, "powerful-agent")["permission"]
    assert permission == {"bash": "allow", "edit": "allow", "webfetch": "allow"}


def test_read_and_search_enable_their_tools(built):
    tools = agent_meta(built, "read-only-agent")["tools"]
    assert tools["read"] is True
    assert tools["grep"] is True and tools["glob"] is True and tools["list"] is True


def test_no_capabilities_denies_all(tmp_path):
    source = tmp_path / "source"
    (source / "agents").mkdir(parents=True)
    (source / "agents" / "inert.md").write_text(
        "---\ndescription: can do nothing\ncapabilities: []\n---\n\nthink\n", encoding="utf-8"
    )
    result = build("opencode", source=source, out_dir=tmp_path / "dist")
    meta = read_frontmatter(result.out_dir / "agents" / "inert.md").meta
    assert set(meta["permission"].values()) == {"deny"}
    assert set(meta["tools"].values()) == {False}


# --------------------------------------------------------------------------- aliases


def test_a_mapped_alias_becomes_a_concrete_model(built):
    assert agent_meta(built, "read-only-agent")["model"] == "ollama/qwen3:30b-a3b"


def test_an_unmapped_alias_omits_the_model_and_is_reported(built):
    """The agent then inherits its caller's model rather than failing the build."""
    assert "model" not in agent_meta(built, "powerful-agent")
    assert "nonesuch" in built.unmapped_aliases
    assert any("inherits its caller's" in w for w in built.warnings)


def test_a_build_without_a_manifest_still_succeeds(tmp_path):
    result = build("opencode", source=SOURCE_FIXTURE, out_dir=tmp_path / "dist")
    assert result.files
    assert "maintainer" in result.unmapped_aliases


# --------------------------------------------------------------------------- hygiene


def test_neutral_only_keys_do_not_reach_the_harness(built):
    meta = agent_meta(built, "read-only-agent")
    assert "role_model" not in meta
    assert "capabilities" not in meta


def test_output_is_valid_yaml_frontmatter(built):
    for path in built.files:
        if path.suffix != ".md":
            continue
        text = path.read_text(encoding="utf-8")
        if not text.startswith("---"):
            continue
        yaml.safe_load(text.split("---", 2)[1])


def test_build_clears_stale_output(tmp_path):
    out = tmp_path / "dist"
    out.mkdir()
    # What a previous build leaves behind: its output, and its marker.
    (out / BUILD_MARKER).write_text("generated by wikiskill build\n", encoding="utf-8")
    stale = out / "skills" / "removed" / "SKILL.md"
    stale.parent.mkdir(parents=True)
    stale.write_text("gone", encoding="utf-8")
    build("opencode", source=SOURCE_FIXTURE, out_dir=out)
    assert not stale.exists()
    assert (out / BUILD_MARKER).is_file()


def test_build_refuses_to_erase_a_directory_it_does_not_own(tmp_path):
    # `--out ~/.config/opencode` is a plausible misreading of "output directory" — it is where
    # `install` puts these same files — and a build used to delete whatever was there.
    config = tmp_path / "opencode"
    (config / "skills" / "mine").mkdir(parents=True)
    kept = config / "opencode.json"
    kept.write_text('{"model": "ollama/qwen3"}', encoding="utf-8")

    with pytest.raises(BuildError, match="not a build directory"):
        build("opencode", source=SOURCE_FIXTURE, out_dir=config)

    assert kept.read_text(encoding="utf-8") == '{"model": "ollama/qwen3"}'
    assert (config / "skills" / "mine").is_dir()


def test_build_uses_an_empty_directory_without_complaint(tmp_path):
    out = tmp_path / "empty"
    out.mkdir()
    result = build("opencode", source=SOURCE_FIXTURE, out_dir=out)
    assert result.files


def test_the_build_marker_is_not_installed(tmp_path, xdg):
    # It identifies a build directory; it has no business in a harness config directory.
    from wikiskill.install import install

    result = install("opencode", "project", target=tmp_path / "proj", source=SOURCE_FIXTURE)
    assert all(path.name != BUILD_MARKER for path in result.written)


def test_building_does_not_touch_the_source_tree(tmp_path):
    before = {p: p.stat().st_mtime_ns for p in sorted(SOURCE_FIXTURE.rglob("*"))}
    build("opencode", source=SOURCE_FIXTURE, out_dir=tmp_path / "dist")
    after = {p: p.stat().st_mtime_ns for p in sorted(SOURCE_FIXTURE.rglob("*"))}
    assert before == after


def test_unknown_harness_is_rejected(tmp_path):
    with pytest.raises(BuildError, match="unknown harness"):
        build("emacs", source=SOURCE_FIXTURE, out_dir=tmp_path / "dist")


def test_a_component_without_a_description_is_rejected(tmp_path):
    source = tmp_path / "source"
    (source / "agents").mkdir(parents=True)
    (source / "agents" / "nameless.md").write_text("---\nname: x\n---\n\nbody\n", encoding="utf-8")
    with pytest.raises(BuildError, match="`description` is required"):
        build("opencode", source=source, out_dir=tmp_path / "dist")


def test_unknown_capabilities_are_warned_not_fatal(tmp_path):
    source = tmp_path / "source"
    (source / "agents").mkdir(parents=True)
    (source / "agents" / "odd.md").write_text(
        "---\ndescription: d\ncapabilities: [read, teleport]\n---\n\nbody\n", encoding="utf-8"
    )
    result = build("opencode", source=source, out_dir=tmp_path / "dist")
    assert any("teleport" in w for w in result.warnings)


def test_the_real_source_tree_builds(tmp_path):
    """wikiskill's own components must survive their own build."""
    result = build("opencode", out_dir=tmp_path / "dist")
    assert any(p.name == "SKILL.md" for p in result.files)


def test_the_eval_command_never_asks_the_calling_session_to_run_the_suite(tmp_path):
    """An evaluation that ran here would put this session into the thing being measured."""
    result = build("opencode", out_dir=tmp_path / "dist")

    (command,) = [p for p in result.files if p.name == "wikiskill-eval.md"]
    # Whitespace-normalised: an assertion about prose should not depend on where a line wrapped.
    text = " ".join(command.read_text(encoding="utf-8").lower().split())

    assert "never run the suite in this session" in text
    assert "&" in text and "wikiskill eval" in text, "it has to say how to start it detached"
    assert "--preflight-only" in text, "and to cost the run before starting it"
