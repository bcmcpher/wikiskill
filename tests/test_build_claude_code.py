"""The Claude Code build: a plugin from the same single-source tree, with the logger's hooks."""

from __future__ import annotations

import json
import shlex
import subprocess

import pytest

from conftest import SOURCE_FIXTURE
from wikiskill.build import CLAUDE_HOOK_EVENTS, build, build_collection
from wikiskill.collection import Collection, Source
from wikiskill.frontmatter import read as read_frontmatter
from wikiskill.install import CLAUDE_MARKETPLACE, CLAUDE_PLUGIN, install


def aliases(**mapping) -> Collection:
    return Collection(
        name="dsh",
        sources=(Source(path=SOURCE_FIXTURE, layout="opencode"),),
        watch={"skill": (), "agent": (), "command": ()},
        aliases={"claude-code": dict(mapping)},
    )


@pytest.fixture
def built(tmp_path):
    return build(
        "claude-code",
        collection=aliases(maintainer="sonnet"),
        source=SOURCE_FIXTURE,
        out_dir=tmp_path / "dist",
        hooks=True,
    )


def meta(built, relative):
    return read_frontmatter(built.out_dir / relative).meta


def test_the_build_is_a_claude_code_plugin(built):
    manifest = json.loads((built.out_dir / ".claude-plugin" / "plugin.json").read_text())
    assert manifest["name"] == "wikiskill"
    assert "skills/example-skill/SKILL.md" in built.relative()
    assert "agents/read-only-agent.md" in built.relative()
    assert "commands/example-command.md" in built.relative()


def test_read_and_search_capabilities_become_exactly_those_tools(built):
    """The spec's scenario: `capabilities: [read, search]` is `tools: Read, Grep, Glob`."""
    agent = meta(built, "agents/read-only-agent.md")
    assert agent["tools"] == "Read, Grep, Glob"
    assert "capabilities" not in agent
    assert "role_model" not in agent


def test_every_capability_grants_its_tools(built):
    assert meta(built, "agents/powerful-agent.md")["tools"] == (
        "Read, Grep, Glob, Bash, Edit, Write, WebFetch"
    )


def test_opencode_only_keys_never_reach_claude_code(built):
    agent = meta(built, "agents/read-only-agent.md")
    assert "mode" not in agent
    assert "permission" not in agent


def test_an_alias_resolves_through_the_claude_code_table(built):
    assert meta(built, "agents/read-only-agent.md")["model"] == "sonnet"
    assert "model" not in meta(built, "agents/powerful-agent.md")
    assert "nonesuch" in built.unmapped_aliases


def test_a_claude_model_name_needs_no_alias(tmp_path):
    source = tmp_path / "src"
    (source / "agents").mkdir(parents=True)
    (source / "agents" / "a.md").write_text(
        "---\ndescription: d\nmodel: haiku\ntools: Read\n---\nbody\n", encoding="utf-8"
    )
    result = build("claude-code", source=source, out_dir=tmp_path / "out")
    assert read_frontmatter(result.out_dir / "agents" / "a.md").meta["model"] == "haiku"
    assert result.unmapped_aliases == []


def test_hooks_cover_every_logged_event_by_absolute_path(built):
    hooks = json.loads((built.out_dir / "hooks" / "hooks.json").read_text())["hooks"]
    assert set(hooks) == set(CLAUDE_HOOK_EVENTS)
    for event, entries in hooks.items():
        [command] = [hook["command"] for entry in entries for hook in entry["hooks"]]
        executable = shlex.split(command)[0]
        assert executable.startswith("/"), command
        assert command.endswith(f"hook {event}")


def test_a_hook_command_runs_in_a_minimal_non_interactive_shell(built):
    """Task 1.3: hooks run without a login shell, so the command must not need PATH."""
    hooks = json.loads((built.out_dir / "hooks" / "hooks.json").read_text())["hooks"]
    command = hooks["Stop"][0]["hooks"][0]["command"]
    cli = command.rsplit(" hook ", 1)[0]
    done = subprocess.run(
        ["env", "-i", "PATH=/usr/bin:/bin", "bash", "-c", f"{cli} --version"],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert done.returncode == 0, done.stderr
    assert done.stdout.startswith("wikiskill ")


def test_wikiskills_own_tree_gets_hooks_and_a_collection_build_does_not(tmp_path):
    own = build("claude-code", out_dir=tmp_path / "own")
    assert (own.out_dir / "hooks" / "hooks.json").is_file()
    assert (own.out_dir / "commands" / "wikiskill-note.md").is_file()
    assert (own.out_dir / "commands" / "wikiskill-review.md").is_file()
    assert (own.out_dir / "agents" / "wikiskill-maintainer.md").is_file()

    collection = Collection(
        name="dsh",
        sources=(Source(path=SOURCE_FIXTURE, layout="opencode"),),
        watch={"skill": (), "agent": (), "command": ()},
    )
    result = build_collection("claude-code", collection, tmp_path / "coll")
    assert not (result.out_dir / "hooks").exists()
    manifest = json.loads((result.out_dir / ".claude-plugin" / "plugin.json").read_text())
    assert manifest["name"] == "dsh"


def test_install_writes_a_one_plugin_marketplace(xdg, tmp_path):
    target = tmp_path / "market"
    result = install("claude-code", "global", source=SOURCE_FIXTURE, target=target)
    marketplace = json.loads((target / ".claude-plugin" / "marketplace.json").read_text())
    assert marketplace["name"] == CLAUDE_MARKETPLACE
    assert marketplace["plugins"][0]["source"] == f"./{CLAUDE_PLUGIN}"
    assert (target / CLAUDE_PLUGIN / ".claude-plugin" / "plugin.json").is_file()
    assert (target / CLAUDE_PLUGIN / "hooks" / "hooks.json").is_file()
    assert any("claude plugin install" in note for note in result.notes)
    again = install("claude-code", "global", source=SOURCE_FIXTURE, target=target)
    assert not again.changed
