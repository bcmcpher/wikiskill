"""Single-source build: one authored tree, one generated layout per harness."""

from __future__ import annotations

import pytest
import yaml

from conftest import SOURCE_FIXTURE
from wikiskill.build import BUILD_MARKER, BuildError, build, build_collection
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


def claude_agent(tmp_path, frontmatter: str):
    """A single claude-plugin-style agent, built for OpenCode."""
    source = tmp_path / "source"
    (source / "agents").mkdir(parents=True)
    (source / "agents" / "doer.md").write_text(
        f"---\nname: doer\ndescription: does things\n{frontmatter}---\n\nbody\n", encoding="utf-8"
    )
    return source


def test_claude_tools_become_opencode_permissions(tmp_path):
    source = claude_agent(tmp_path, "tools: Read, Bash, Grep, Glob\n")
    result = build("opencode", source=source, out_dir=tmp_path / "dist")
    meta = read_frontmatter(result.out_dir / "agents" / "doer.md").meta
    assert meta["permission"] == {"bash": "allow", "edit": "deny", "webfetch": "deny"}
    assert meta["tools"] == {"glob": True, "grep": True, "list": True, "read": True}


def test_claude_tools_as_a_list_are_read_too(tmp_path):
    source = claude_agent(tmp_path, "tools: [Read, Write]\n")
    result = build("opencode", source=source, out_dir=tmp_path / "dist")
    meta = read_frontmatter(result.out_dir / "agents" / "doer.md").meta
    assert meta["permission"]["edit"] == "allow"
    assert meta["permission"]["bash"] == "deny"


def test_explicit_capabilities_win_over_tools(tmp_path):
    source = claude_agent(tmp_path, "tools: Read, Bash\ncapabilities: [read]\n")
    result = build("opencode", source=source, out_dir=tmp_path / "dist")
    meta = read_frontmatter(result.out_dir / "agents" / "doer.md").meta
    assert meta["permission"]["bash"] == "deny"


def test_an_unknown_claude_tool_is_warned_not_fatal(tmp_path):
    source = claude_agent(tmp_path, "tools: Read, Teleport, mcp__zotero__search\n")
    result = build("opencode", source=source, out_dir=tmp_path / "dist")
    assert any("Teleport" in w for w in result.warnings)
    assert not any("mcp__zotero__search" in w for w in result.warnings)


def test_a_skill_tools_key_does_not_reach_the_harness(tmp_path):
    source = tmp_path / "source"
    (source / "skills" / "s").mkdir(parents=True)
    (source / "skills" / "s" / "SKILL.md").write_text(
        "---\nname: s\ndescription: d\ntools: Read, Bash\n---\n\nbody\n", encoding="utf-8"
    )
    result = build("opencode", source=source, out_dir=tmp_path / "dist")
    assert "tools" not in read_frontmatter(result.out_dir / "skills" / "s" / "SKILL.md").meta


# --------------------------------------------------------------------------- aliases


def test_a_claude_model_resolves_through_a_tier_alias(tmp_path):
    source = claude_agent(tmp_path, "tools: Read\nmodel: haiku\n")
    coll = collection_with_aliases(small="opencode/big-pickle", haiku="small")
    result = build("opencode", collection=coll, source=source, out_dir=tmp_path / "dist")
    assert read_frontmatter(result.out_dir / "agents" / "doer.md").meta["model"] == (
        "opencode/big-pickle"
    )
    assert result.unmapped_aliases == []


def test_an_unmapped_claude_model_is_dropped_and_reported(tmp_path):
    source = claude_agent(tmp_path, "tools: Read\nmodel: sonnet\n")
    result = build("opencode", source=source, out_dir=tmp_path / "dist")
    assert "model" not in read_frontmatter(result.out_dir / "agents" / "doer.md").meta
    assert result.unmapped_aliases == ["sonnet"]


def test_a_concrete_model_passes_through(tmp_path):
    source = claude_agent(tmp_path, "model: ollama/qwen3:1.7b\n")
    result = build("opencode", source=source, out_dir=tmp_path / "dist")
    meta = read_frontmatter(result.out_dir / "agents" / "doer.md").meta
    assert meta["model"] == "ollama/qwen3:1.7b"
    assert result.unmapped_aliases == []


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


# --------------------------------------------------------------------------- collection sources


def plugin_collection(root, plugins=None, **aliases) -> Collection:
    return Collection(
        name="dsh",
        sources=(Source(path=root, layout="claude-plugin", plugins=plugins),),
        watch={"skill": (), "agent": (), "command": ()},
        aliases={"opencode": dict(aliases)},
    )


def add_agent(root, plugin, name, frontmatter=""):
    directory = root / plugin / "agents"
    directory.mkdir(parents=True, exist_ok=True)
    (directory / f"{name}.md").write_text(
        f"---\nname: {name}\ndescription: {name}\n{frontmatter}---\n\nbody\n", encoding="utf-8"
    )


def add_skill(root, plugin, name):
    directory = root / plugin / "skills" / name
    directory.mkdir(parents=True)
    (directory / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: {name}\n---\n\nbody\n", encoding="utf-8"
    )


def test_a_collection_builds_every_plugin_and_prints_its_mapping(tmp_path):
    root = tmp_path / "plugins"
    add_agent(root, "datalad", "datalad-doer", "tools: Read, Bash\n")
    add_skill(root, "govern", "preregister")
    result = build_collection("opencode", plugin_collection(root), tmp_path / "dist")
    assert result.mapping == {
        "datalad/datalad-doer": "datalad-doer",
        "govern/preregister": "preregister",
    }
    doer = read_frontmatter(tmp_path / "dist" / "agents" / "datalad-doer.md").meta
    assert doer["permission"]["bash"] == "allow"
    assert (tmp_path / "dist" / BUILD_MARKER).is_file()


def test_a_flat_name_collision_fails_and_names_both(tmp_path):
    root = tmp_path / "plugins"
    add_skill(root, "project", "status")
    add_skill(root, "datalad", "status")
    with pytest.raises(BuildError, match="`datalad/status` and `project/status`"):
        build_collection("opencode", plugin_collection(root), tmp_path / "dist")
    assert not (tmp_path / "dist").exists()


def test_a_plugin_filter_builds_only_the_unit(tmp_path):
    root = tmp_path / "plugins"
    add_agent(root, "datalad", "datalad-doer")
    add_skill(root, "govern", "preregister")
    result = build_collection("opencode", plugin_collection(root, ("datalad",)), tmp_path / "dist")
    assert list(result.mapping) == ["datalad/datalad-doer"]
    assert not (tmp_path / "dist" / "skills").exists()


def test_strip_models_leaves_every_component_on_its_callers_model(tmp_path):
    root = tmp_path / "plugins"
    add_agent(root, "bids", "bids-doer", "model: haiku\n")
    coll = plugin_collection(root, small="opencode/big-pickle", haiku="small")
    kept = build_collection("opencode", coll, tmp_path / "kept")
    stripped = build_collection("opencode", coll, tmp_path / "stripped", strip_models=True)
    assert read_frontmatter(kept.out_dir / "agents" / "bids-doer.md").meta["model"] == (
        "opencode/big-pickle"
    )
    assert "model" not in read_frontmatter(stripped.out_dir / "agents" / "bids-doer.md").meta


def test_a_collection_build_leaves_its_sources_byte_identical(tmp_path):
    root = tmp_path / "plugins"
    add_agent(root, "datalad", "datalad-doer", "tools: Read, Bash\nmodel: haiku\n")
    add_skill(root, "govern", "preregister")

    def snapshot():
        return {
            p: (p.read_bytes() if p.is_file() else None, p.stat().st_mtime_ns)
            for p in sorted(root.rglob("*"))
        }

    before = snapshot()
    coll = plugin_collection(root, haiku="opencode/big-pickle")
    build_collection("opencode", coll, tmp_path / "d")
    assert snapshot() == before
