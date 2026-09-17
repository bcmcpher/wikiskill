"""Installation: idempotent, recorded, and reversible without touching the user's own files."""

from __future__ import annotations

import json

import pytest

from conftest import SOURCE_FIXTURE
from wikiskill import install as install_mod
from wikiskill.install import InstallError, install, record_path, uninstall


@pytest.fixture
def target(tmp_path):
    directory = tmp_path / "opencode-config"
    directory.mkdir()
    return directory


def do_install(target, **kwargs):
    return install("opencode", "project", target=target, source=SOURCE_FIXTURE, **kwargs)


def test_install_writes_components_and_the_logger(xdg, target):
    result = do_install(target)
    written = {str(p.relative_to(target)) for p in result.written}
    assert "skills/wikiskill-trace/SKILL.md" not in written  # fixture tree, not the real one
    assert "skills/example-skill/SKILL.md" in written
    assert "plugin/wikiskill-logger.ts" in written
    assert "plugin/wikiskill/mapper.ts" in written


def test_the_logger_source_is_installed_whole(xdg, target):
    do_install(target)
    modules = sorted(p.name for p in (target / "plugin" / "wikiskill").glob("*.ts"))
    assert {"mapper.ts", "match.ts", "redact.ts", "sessions.ts", "writer.ts", "config.ts"} <= set(
        modules
    )


def test_tests_and_package_metadata_are_not_installed(xdg, target):
    do_install(target)
    assert not (target / "plugin" / "test").exists()
    assert not (target / "plugin" / "package.json").exists()


def test_installing_twice_reports_no_changes(xdg, target):
    do_install(target)
    second = do_install(target)
    assert second.written == []
    assert second.changed is False
    assert second.unchanged


def test_install_records_exactly_what_it_wrote(xdg, target):
    result = do_install(target)
    record = json.loads(record_path("opencode", "project", target).read_text())
    recorded = {entry["path"] for entry in record["files"]}
    assert recorded == {str(p) for p in result.written}
    assert record["target"] == str(target)


def test_uninstall_removes_only_recorded_files(xdg, target):
    """A user's own skills living in the same directory must survive."""
    do_install(target)
    mine = target / "skills" / "my-own-skill"
    mine.mkdir(parents=True)
    (mine / "SKILL.md").write_text("mine", encoding="utf-8")
    also_mine = target / "opencode.json"
    also_mine.write_text("{}", encoding="utf-8")

    result = uninstall("opencode", "project", target=target)

    assert (mine / "SKILL.md").read_text() == "mine"
    assert also_mine.exists()
    assert not (target / "skills" / "example-skill").exists()
    assert not (target / "plugin" / "wikiskill-logger.ts").exists()
    assert result.removed


def test_uninstall_clears_its_record(xdg, target):
    do_install(target)
    uninstall("opencode", "project", target=target)
    assert not record_path("opencode", "project", target).is_file()


def test_uninstall_without_a_record_says_so(xdg, target):
    with pytest.raises(InstallError, match="nothing to uninstall"):
        uninstall("opencode", "project", target=target)


def test_uninstall_leaves_a_file_the_user_changed(xdg, target):
    do_install(target)
    edited = target / "skills" / "example-skill" / "SKILL.md"
    edited.write_text("I changed this", encoding="utf-8")

    result = uninstall("opencode", "project", target=target)

    assert edited.exists()
    assert edited in result.skipped
    assert any("--force" in warning for warning in result.warnings)


def test_forced_uninstall_removes_a_changed_file(xdg, target):
    do_install(target)
    edited = target / "skills" / "example-skill" / "SKILL.md"
    edited.write_text("I changed this", encoding="utf-8")
    uninstall("opencode", "project", target=target, force=True)
    assert not edited.exists()


def test_a_removed_source_component_is_removed_on_reinstall(xdg, target, tmp_path):
    source = tmp_path / "source"
    (source / "skills" / "keep").mkdir(parents=True)
    (source / "skills" / "keep" / "SKILL.md").write_text(
        "---\nname: keep\ndescription: stays\n---\n\nbody\n", encoding="utf-8"
    )
    (source / "skills" / "drop").mkdir(parents=True)
    (source / "skills" / "drop" / "SKILL.md").write_text(
        "---\nname: drop\ndescription: goes\n---\n\nbody\n", encoding="utf-8"
    )
    install("opencode", "project", target=target, source=source)
    assert (target / "skills" / "drop" / "SKILL.md").is_file()

    import shutil

    shutil.rmtree(source / "skills" / "drop")
    result = install("opencode", "project", target=target, source=source)

    assert not (target / "skills" / "drop").exists()
    assert (target / "skills" / "keep" / "SKILL.md").is_file()
    assert result.removed


def test_install_publishes_the_logger_configuration(xdg, target, plugin_source):
    from conftest import write_manifest
    from wikiskill import collection as collection_mod

    write_manifest(
        xdg,
        "dsh",
        f'name = "dsh"\nsources = [{{ path = "{plugin_source}", layout = "claude-plugin" }}]\n'
        '[watch]\nskills = ["govern/preregister"]\n',
    )
    coll = collection_mod.load("dsh")
    do_install(target, collection=coll)

    runtime = json.loads(collection_mod.runtime_config_path().read_text())
    assert [c["collection"] for c in runtime["collections"]] == ["dsh"]


def test_install_reports_a_resolvable_cli_path():
    """Claude Code hooks call wikiskill by explicit path, so install must print one."""
    assert install_mod.resolved_cli_path()


def test_unknown_scope_is_rejected(xdg, target):
    with pytest.raises(InstallError, match="scope must be one of"):
        install("opencode", "everywhere", target=target, source=SOURCE_FIXTURE)


def test_publishing_the_logger_configuration_is_a_note_not_a_warning(xdg, target, plugin_source):
    """Warnings are for things a user must act on; this is just where the file went."""
    from conftest import write_manifest
    from wikiskill import collection as collection_mod

    write_manifest(
        xdg,
        "dsh",
        f'name = "dsh"\nsources = [{{ path = "{plugin_source}", layout = "claude-plugin" }}]\n'
        '[watch]\nskills = ["govern/preregister"]\n',
    )
    result = do_install(target, collection=collection_mod.load("dsh"))
    assert any("logger configuration written to" in note for note in result.notes)
    assert not any("logger configuration" in warning for warning in result.warnings)
