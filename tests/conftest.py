"""Shared fixtures.

Every test that touches wikiskill's own storage redirects XDG at a temporary directory, so no test
can read or write the developer's real config, data or install records.
"""

from __future__ import annotations

from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"
RAW_FIXTURES = FIXTURES / "raw"
SOURCE_FIXTURE = FIXTURES / "source"


@pytest.fixture
def xdg(tmp_path, monkeypatch):
    """Redirect every XDG base directory into ``tmp_path``."""
    homes = {}
    for var, name in (
        ("XDG_CONFIG_HOME", "config"),
        ("XDG_DATA_HOME", "data"),
        ("XDG_STATE_HOME", "state"),
        ("XDG_CACHE_HOME", "cache"),
    ):
        directory = tmp_path / name
        directory.mkdir()
        monkeypatch.setenv(var, str(directory))
        homes[name] = directory
    return homes


@pytest.fixture
def opencode_source(tmp_path):
    """A source tree in OpenCode layout: components at the top level."""
    root = tmp_path / "oc-source"
    (root / "skills" / "smoke").mkdir(parents=True)
    (root / "skills" / "smoke" / "SKILL.md").write_text(
        "---\nname: smoke\ndescription: smoke test skill\n---\n\nbody\n", encoding="utf-8"
    )
    (root / "skills" / "not-a-skill").mkdir()
    (root / "commands").mkdir()
    (root / "commands" / "smoke-check.md").write_text(
        "---\ndescription: smoke command\n---\n\nrun it\n", encoding="utf-8"
    )
    return root


@pytest.fixture
def plugin_source(tmp_path):
    """A source tree in claude-plugin layout: one level of plugin directories."""
    root = tmp_path / "plugins"
    for plugin, skills, agents in (
        ("govern", ["preregister", "obligations"], []),
        ("analyze", ["run-comparison"], []),
        ("datalad", [], ["datalad-doer"]),
    ):
        for skill in skills:
            directory = root / plugin / "skills" / skill
            directory.mkdir(parents=True)
            (directory / "SKILL.md").write_text(
                f"---\nname: {skill}\ndescription: {skill} skill\n---\n\nbody\n", encoding="utf-8"
            )
        for agent in agents:
            directory = root / plugin / "agents"
            directory.mkdir(parents=True, exist_ok=True)
            (directory / f"{agent}.md").write_text(
                f"---\nname: {agent}\ndescription: {agent} agent\n---\n\nbody\n", encoding="utf-8"
            )
    return root


def write_manifest(xdg_homes, name: str, body: str) -> Path:
    """Place a manifest where ``wikiskill collection`` will find it."""
    path = xdg_homes["config"] / "wikiskill" / "collections" / f"{name}.toml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    return path
