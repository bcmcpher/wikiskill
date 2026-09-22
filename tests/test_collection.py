"""The collection manifest: declaration, discovery, watch-list resolution, roles and aliases."""

from __future__ import annotations

import pytest

from conftest import write_manifest
from wikiskill import collection as collection_mod
from wikiskill import paths
from wikiskill.collection import Collection, ManifestError, Source


def manifest_body(source_path, layout="claude-plugin", watch='skills = ["govern/preregister"]'):
    return f"""
name = "dsh"
sources = [{{ path = "{source_path}", layout = "{layout}" }}]

[watch]
{watch}
"""


# --------------------------------------------------------------------------- discovery


def test_discovers_a_claude_plugin_layout(plugin_source):
    found = collection_mod.discover(Source(path=plugin_source, layout="claude-plugin"))
    names = {(c.kind, c.name) for c in found}
    assert ("skill", "govern/preregister") in names
    assert ("skill", "analyze/run-comparison") in names
    assert ("agent", "datalad/datalad-doer") in names


def test_a_plugin_filter_narrows_discovery_to_the_unit(plugin_source):
    source = Source(path=plugin_source, layout="claude-plugin", plugins=("datalad",))
    names = {(c.kind, c.name) for c in collection_mod.discover(source)}
    assert names == {("agent", "datalad/datalad-doer")}


def test_a_selected_plugin_that_does_not_exist_is_unresolved(xdg, plugin_source):
    body = f"""
name = "dsh"
sources = [{{ path = "{plugin_source}", layout = "claude-plugin", plugins = ["datalod"] }}]

[watch]
agents = ["datalad/datalad-doer"]
"""
    write_manifest(xdg, "dsh", body)
    coll = collection_mod.load("dsh")
    assert coll.unresolved_plugins() == [f"{plugin_source}/datalod"]
    assert coll.discover() == []


def test_discovers_an_opencode_layout(opencode_source):
    found = collection_mod.discover(Source(path=opencode_source, layout="opencode"))
    names = {(c.kind, c.name) for c in found}
    assert ("skill", "smoke") in names
    assert ("command", "smoke-check") in names
    # A directory without a SKILL.md is not a skill.
    assert ("skill", "not-a-skill") not in names


def test_a_components_path_is_the_file_that_identifies_its_version(plugin_source):
    found = collection_mod.discover(Source(path=plugin_source, layout="claude-plugin"))
    skill = next(c for c in found if c.name == "govern/preregister")
    assert skill.path.name == "SKILL.md"
    assert skill.plugin == "govern"


# --------------------------------------------------------------------------- watch list


def test_watch_list_globs_resolve(xdg, plugin_source):
    write_manifest(xdg, "dsh", manifest_body(plugin_source, watch='skills = ["analyze/*"]'))
    coll = collection_mod.load("dsh")
    assert [c.name for c in coll.watched()] == ["analyze/run-comparison"]
    assert coll.unresolved() == []


def test_unresolved_watch_entry_is_reported(xdg, plugin_source):
    write_manifest(xdg, "dsh", manifest_body(plugin_source, watch='skills = ["govern/absent"]'))
    coll = collection_mod.load("dsh")
    assert coll.unresolved() == ["skill:govern/absent"]
    assert coll.watched() == []


def test_a_watch_list_that_selects_nothing_is_rejected(xdg, plugin_source):
    write_manifest(xdg, "dsh", manifest_body(plugin_source, watch="skills = []"))
    with pytest.raises(ManifestError, match="selects nothing"):
        collection_mod.load("dsh")


# --------------------------------------------------------------------------- read-only


def test_checking_a_source_does_not_write_to_it(xdg, plugin_source):
    write_manifest(xdg, "dsh", manifest_body(plugin_source))
    before = {p: p.stat().st_mtime_ns for p in sorted(plugin_source.rglob("*"))}
    coll = collection_mod.load("dsh")
    coll.discover()
    coll.watched()
    coll.unresolved()
    coll.runtime_config()
    after = {p: p.stat().st_mtime_ns for p in sorted(plugin_source.rglob("*"))}
    assert before == after


# --------------------------------------------------------------------------- roles


ROLES_BODY = """
name = "dsh"
sources = [{{ path = "{source}", layout = "claude-plugin" }}]
watch = {{ skills = ["govern/preregister"] }}

[roles.judge]
base_url = "http://gpu-box:8000/v1"
model = "{judge}"

[roles.maintainer]
base_url = "http://localhost:11434/v1"
model = "qwen3:30b-a3b"

[targets]
opencode = ["ollama/qwen3:1.7b", "vllm/qwen3-32b"]
"""


def test_roles_keep_their_own_endpoints(xdg, plugin_source):
    write_manifest(xdg, "dsh", ROLES_BODY.format(source=plugin_source, judge="mixtral-8x7b"))
    coll = collection_mod.load("dsh")
    assert coll.roles["judge"].base_url == "http://gpu-box:8000/v1"
    assert coll.roles["maintainer"].base_url == "http://localhost:11434/v1"
    assert coll.roles["judge"].model != coll.roles["maintainer"].model


def test_judge_equal_to_a_target_is_rejected_by_name(xdg, plugin_source):
    """A judge grading its own output is not a measurement."""
    write_manifest(xdg, "dsh", ROLES_BODY.format(source=plugin_source, judge="qwen3-32b"))
    with pytest.raises(ManifestError) as excinfo:
        collection_mod.load("dsh")
    assert "qwen3-32b" in str(excinfo.value)
    assert "must not be a model under test" in str(excinfo.value)


def test_judge_equal_to_a_target_is_rejected_across_provider_prefixes(xdg, plugin_source):
    write_manifest(xdg, "dsh", ROLES_BODY.format(source=plugin_source, judge="vllm/qwen3-32b"))
    with pytest.raises(ManifestError, match="must not be a model under test"):
        collection_mod.load("dsh")


def test_judge_equal_to_a_target_is_rejected_through_an_alias(xdg, plugin_source):
    """A target named by alias still resolves to a concrete model before the comparison."""
    write_manifest(
        xdg,
        "dsh",
        f"""
name = "dsh"
sources = [{{ path = "{plugin_source}", layout = "claude-plugin" }}]
watch = {{ skills = ["govern/preregister"] }}

[roles.judge]
model = "qwen3:1.7b"

[targets]
opencode = ["small"]

[aliases.opencode]
small = "ollama/qwen3:1.7b"
""",
    )
    with pytest.raises(ManifestError, match="must not be a model under test"):
        collection_mod.load("dsh")


# --------------------------------------------------------------------------- aliases


def test_alias_resolves_per_harness(xdg, plugin_source):
    write_manifest(
        xdg,
        "dsh",
        manifest_body(plugin_source)
        + """
[aliases.opencode]
haiku = "ollama/qwen3:30b-a3b"

[aliases.claude-code]
haiku = "haiku"
""",
    )
    coll = collection_mod.load("dsh")
    assert coll.resolve_alias("opencode", "haiku") == "ollama/qwen3:30b-a3b"
    assert coll.resolve_alias("claude-code", "haiku") == "haiku"


def test_a_tier_alias_is_followed_one_hop(xdg, plugin_source):
    write_manifest(
        xdg,
        "dsh",
        manifest_body(plugin_source)
        + """
[aliases.opencode]
small = "opencode/big-pickle"
haiku = "small"
""",
    )
    coll = collection_mod.load("dsh")
    assert coll.resolve_alias("opencode", "haiku") == "opencode/big-pickle"
    assert coll.resolve_alias("opencode", "small") == "opencode/big-pickle"


@pytest.mark.parametrize(
    "table, expected",
    [
        ('small = "large"\nlarge = "small"\n', "opencode.small` -> `large` -> `small` is a cycle"),
        (
            'haiku = "small"\nsmall = "large"\nlarge = "ollama/qwen3:1.7b"\n',
            "more than one hop",
        ),
        ('haiku = "small"\nsmall = "big-pickle"\n', "does not end in a `provider/model`"),
    ],
)
def test_a_bad_alias_chain_is_rejected(xdg, plugin_source, table, expected):
    write_manifest(xdg, "dsh", manifest_body(plugin_source) + "\n[aliases.opencode]\n" + table)
    with pytest.raises(ManifestError, match=expected):
        collection_mod.load("dsh")


def test_unmapped_alias_is_reported_rather_than_fatal(xdg, plugin_source):
    write_manifest(xdg, "dsh", manifest_body(plugin_source))
    coll = collection_mod.load("dsh")
    assert coll.resolve_alias("opencode", "haiku") is None
    assert coll.unmapped_aliases("opencode", ["haiku", "maintainer"]) == ["haiku", "maintainer"]


# --------------------------------------------------------------------------- validation


@pytest.mark.parametrize(
    "body, expected",
    [
        ('sources = []\n[watch]\nskills = ["x"]\n', "non-empty array"),
        ('name = "dsh"\n[watch]\nskills = ["x"]\n', "`sources` is required"),
        (
            'name = "dsh"\nsources = [{ path = "/tmp", layout = "invented" }]\n[watch]\nskills = ["x"]\n',
            "layout` must be one of",
        ),
        (
            'name = "dsh"\nsources = [{ path = "/tmp", layout = "opencode" }]\n[watch]\nskills = ["x"]\n[roles.judge]\nbase_url = "u"\n',
            "roles.judge.model` is required",
        ),
        (
            'name = "dsh"\nsources = [{ path = "/tmp", layout = "opencode" }]\n[watch]\nskills = ["x"]\n[logging]\nbuffer_size = 0\n',
            "logging.buffer_size` must be a positive integer",
        ),
        (
            'name = "other"\nsources = [{ path = "/tmp", layout = "opencode" }]\n[watch]\nskills = ["x"]\n',
            "but the manifest file is named",
        ),
        (
            'name = "dsh"\nsources = [{ path = "/tmp", layout = "opencode", plugins = ["x"] }]\n[watch]\nskills = ["x"]\n',
            "plugins` applies only to the claude-plugin layout",
        ),
        (
            'name = "dsh"\nsources = [{ path = "/tmp", layout = "claude-plugin", plugins = [] }]\n[watch]\nskills = ["x"]\n',
            "plugins` must be a non-empty array",
        ),
    ],
)
def test_invalid_manifests_are_rejected_with_a_reason(xdg, body, expected):
    write_manifest(xdg, "dsh", body)
    with pytest.raises(ManifestError, match=expected):
        collection_mod.load("dsh")


def test_manifest_error_lists_every_problem_at_once(xdg):
    write_manifest(xdg, "dsh", "sources = 5\n[watch]\nskills = 7\n")
    with pytest.raises(ManifestError) as excinfo:
        collection_mod.load("dsh")
    assert len(excinfo.value.problems) >= 3


def test_missing_manifest_names_the_path(xdg):
    with pytest.raises(ManifestError, match="no manifest at"):
        collection_mod.load("absent")


def test_malformed_toml_is_reported_as_such(xdg):
    write_manifest(xdg, "dsh", "name = \n")
    with pytest.raises(ManifestError, match="not valid TOML"):
        collection_mod.load("dsh")


# --------------------------------------------------------------------------- runtime view


def test_runtime_config_resolves_watched_components_for_the_logger(xdg, plugin_source):
    write_manifest(xdg, "dsh", manifest_body(plugin_source))
    coll = collection_mod.load("dsh")
    runtime = coll.runtime_config()
    assert runtime["collection"] == "dsh"
    assert runtime["raw_dir"] == str(paths.raw_dir("dsh"))
    assert runtime["buffer_size"] == collection_mod.DEFAULT_BUFFER_SIZE
    assert runtime["output_limit_bytes"] == 16 * 1024
    watched = runtime["watched"]
    assert watched == [
        {
            "kind": "skill",
            "name": "govern/preregister",
            "path": str(plugin_source / "govern" / "skills" / "preregister" / "SKILL.md"),
        }
    ]


def test_write_runtime_config_is_json_the_plugin_can_read(xdg, plugin_source):
    import json

    write_manifest(xdg, "dsh", manifest_body(plugin_source))
    coll = collection_mod.load("dsh")
    target = collection_mod.write_runtime_config([coll])
    payload = json.loads(target.read_text())
    assert payload["version"] == 1
    assert [c["collection"] for c in payload["collections"]] == ["dsh"]


def test_render_manifest_opts_in_to_only_one_component(plugin_source):
    source = Source(path=plugin_source, layout="claude-plugin")
    discovered = sorted(collection_mod.discover(source), key=lambda c: (c.kind, c.name))
    body = collection_mod.render_manifest("dsh", [source], discovered)
    assert 'name = "dsh"' in body
    # Everything discovered appears, but all but one skill is commented out for the user to choose.
    assert body.count("#   ") >= 1
    parsed = collection_mod.parse(__import__("tomllib").loads(body), expected_name="dsh")
    assert isinstance(parsed, Collection)
    assert len(parsed.watch["skill"]) == 1


# --------------------------------------------------------------------------- publishing


def test_publishing_includes_every_configured_collection(xdg, plugin_source, opencode_source):
    """The logger treats runtime.json as its whole world; a subset silently stops logging the rest."""
    write_manifest(xdg, "dsh", manifest_body(plugin_source))
    write_manifest(
        xdg,
        "oc",
        f'name = "oc"\nsources = [{{ path = "{opencode_source}", layout = "opencode" }}]\n'
        '[watch]\nskills = ["smoke"]\n',
    )

    _, published, problems = collection_mod.publish_runtime_config()

    assert sorted(c.name for c in published) == ["dsh", "oc"]
    assert problems == []


def test_publishing_one_collection_does_not_drop_the_others(xdg, plugin_source, opencode_source):
    import json

    write_manifest(xdg, "dsh", manifest_body(plugin_source))
    write_manifest(
        xdg,
        "oc",
        f'name = "oc"\nsources = [{{ path = "{opencode_source}", layout = "opencode" }}]\n'
        '[watch]\nskills = ["smoke"]\n',
    )
    only_one = collection_mod.load("dsh")

    target, _, _ = collection_mod.publish_runtime_config(prefer=only_one)

    names = [c["collection"] for c in json.loads(target.read_text())["collections"]]
    assert sorted(names) == ["dsh", "oc"]


def test_publishing_reports_a_collection_it_could_not_load(xdg, plugin_source):
    write_manifest(xdg, "dsh", manifest_body(plugin_source))
    write_manifest(xdg, "broken", "name = 5\n")

    _, published, problems = collection_mod.publish_runtime_config()

    assert [c.name for c in published] == ["dsh"]
    assert len(problems) == 1
    assert "broken" in problems[0]


def test_publishing_with_nothing_configured_writes_an_empty_list(xdg):
    import json

    target, published, problems = collection_mod.publish_runtime_config()
    assert published == [] and problems == []
    assert json.loads(target.read_text())["collections"] == []
