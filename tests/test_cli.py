"""The CLI surface: exit codes and the output a person or a hook reads."""

from __future__ import annotations

import json

import pytest

from conftest import RAW_FIXTURES, write_manifest
from wikiskill import collection as collection_mod
from wikiskill import paths
from wikiskill.cli import main


def manifest_for(plugin_source, watch='skills = ["govern/preregister"]'):
    return (
        f'name = "dsh"\nsources = [{{ path = "{plugin_source}", layout = "claude-plugin" }}]\n'
        f"[watch]\n{watch}\n"
    )


# --------------------------------------------------------------------------- collection


def test_init_writes_a_manifest_and_lists_what_it_found(xdg, plugin_source, capsys):
    assert main(["collection", "init", "dsh", "--source", str(plugin_source)]) == 0
    out = capsys.readouterr().out
    assert str(paths.manifest_path("dsh")) in out
    assert "govern/preregister" in out
    assert "collection check dsh" in out
    assert paths.manifest_path("dsh").is_file()


def test_init_detects_the_layout(xdg, plugin_source, opencode_source):
    main(["collection", "init", "dsh", "--source", str(plugin_source)])
    assert collection_mod.load("dsh").sources[0].layout == "claude-plugin"
    main(["collection", "init", "oc", "--source", str(opencode_source)])
    assert collection_mod.load("oc").sources[0].layout == "opencode"


def test_init_refuses_to_overwrite_without_force(xdg, plugin_source, capsys):
    main(["collection", "init", "dsh", "--source", str(plugin_source)])
    assert main(["collection", "init", "dsh", "--source", str(plugin_source)]) == 1
    assert "--force" in capsys.readouterr().err
    assert main(["collection", "init", "dsh", "--source", str(plugin_source), "--force"]) == 0


def test_init_reports_a_missing_source(xdg, tmp_path, capsys):
    assert main(["collection", "init", "dsh", "--source", str(tmp_path / "absent")]) == 1
    assert "no such source directory" in capsys.readouterr().err


def test_an_initialised_manifest_passes_check(xdg, plugin_source):
    main(["collection", "init", "dsh", "--source", str(plugin_source)])
    assert main(["collection", "check", "dsh"]) == 0


def test_check_marks_watched_components(xdg, plugin_source, capsys):
    write_manifest(xdg, "dsh", manifest_for(plugin_source))
    assert main(["collection", "check", "dsh"]) == 0
    out = capsys.readouterr().out
    assert "* govern/preregister" in out
    assert "  analyze/run-comparison" in out
    assert out.rstrip().endswith("ok")


def test_check_exits_non_zero_on_an_unresolved_entry(xdg, plugin_source, capsys):
    write_manifest(xdg, "dsh", manifest_for(plugin_source, 'skills = ["govern/absent"]'))
    assert main(["collection", "check", "dsh"]) == 1
    captured = capsys.readouterr()
    assert "! skill:govern/absent" in captured.out
    assert "match nothing" in captured.err


def test_check_exits_non_zero_on_a_missing_source(xdg, tmp_path, capsys):
    write_manifest(
        xdg,
        "dsh",
        f'name = "dsh"\nsources = [{{ path = "{tmp_path / "gone"}", layout = "opencode" }}]\n'
        '[watch]\nskills = ["x"]\n',
    )
    assert main(["collection", "check", "dsh"]) == 1
    assert "does not exist" in capsys.readouterr().err


def test_check_sync_publishes_the_logger_configuration(xdg, plugin_source):
    write_manifest(xdg, "dsh", manifest_for(plugin_source))
    assert main(["collection", "check", "dsh", "--sync"]) == 0
    runtime = json.loads(collection_mod.runtime_config_path().read_text())
    assert runtime["collections"][0]["watch"]["skill"] == ["govern/preregister"]


def test_check_does_not_write_to_the_source(xdg, plugin_source):
    write_manifest(xdg, "dsh", manifest_for(plugin_source))
    before = {p: p.stat().st_mtime_ns for p in sorted(plugin_source.rglob("*"))}
    main(["collection", "check", "dsh", "--sync"])
    assert {p: p.stat().st_mtime_ns for p in sorted(plugin_source.rglob("*"))} == before


def test_show_json_is_the_loggers_view(xdg, plugin_source, capsys):
    write_manifest(xdg, "dsh", manifest_for(plugin_source))
    assert main(["collection", "show", "dsh", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["collection"] == "dsh"
    assert payload["raw_dir"].endswith("/dsh/raw")


def test_show_reports_an_invalid_manifest(xdg, capsys):
    write_manifest(xdg, "dsh", "name = 5\n")
    assert main(["collection", "show", "dsh"]) == 1
    assert "invalid collection manifest" in capsys.readouterr().err


# --------------------------------------------------------------------------- log


@pytest.fixture
def seeded(xdg):
    import shutil

    day = paths.raw_dir("dsh") / "2026-09-17"
    day.mkdir(parents=True)
    for name in ("opencode-skill-session.jsonl", "opencode-delegation.jsonl"):
        shutil.copy(RAW_FIXTURES / name, day / name)
    return day


def test_log_validate_reports_activations_and_succeeds(seeded, capsys):
    assert main(["log", "validate", "dsh"]) == 0
    out = capsys.readouterr().out
    assert "2 component_activated events" in out
    assert "0 schema errors" in out


def test_log_validate_exits_non_zero_on_a_bad_log(xdg, capsys):
    day = paths.raw_dir("dsh") / "2026-09-17"
    day.mkdir(parents=True)
    (day / "ses_bad.jsonl").write_text('{"schema_version":1,"type":"nope"}\n', encoding="utf-8")
    assert main(["log", "validate", "dsh"]) == 1
    assert "schema errors" in capsys.readouterr().out


def test_log_stats_report_models(seeded, capsys):
    assert main(["log", "stats", "dsh"]) == 0
    out = capsys.readouterr().out
    assert "sessions  2" in out
    assert "ollama/qwen3:1.7b" in out


def test_log_stats_work_without_a_manifest(seeded, capsys):
    """Stats stay useful when a manifest has drifted; only the watched-path signal is lost."""
    assert main(["log", "stats", "dsh"]) == 0
    assert "events" in capsys.readouterr().out


def test_log_tail_json_emits_one_event_per_line(seeded, capsys):
    assert main(["log", "tail", "dsh", "-n", "3", "--json"]) == 0
    lines = capsys.readouterr().out.strip().splitlines()
    assert len(lines) == 3
    assert all(json.loads(line)["schema_version"] == 1 for line in lines)


def test_log_commands_accept_a_raw_dir_override(xdg, tmp_path, capsys):
    assert main(["log", "validate", "dsh", "--raw-dir", str(tmp_path)]) == 0
    assert "0 events" in capsys.readouterr().out


# --------------------------------------------------------------------------- build / install


def test_build_lists_what_it_wrote(xdg, tmp_path, capsys):
    out_dir = tmp_path / "dist"
    assert main(["build", "--harness", "opencode", "--out", str(out_dir)]) == 0
    printed = capsys.readouterr().out
    assert "skills/wikiskill-trace/SKILL.md" in printed
    assert (out_dir / "skills" / "wikiskill-trace" / "SKILL.md").is_file()


def test_build_uses_a_collections_alias_table(xdg, plugin_source, tmp_path, capsys):
    write_manifest(
        xdg,
        "dsh",
        manifest_for(plugin_source) + '\n[aliases.opencode]\nmaintainer = "ollama/qwen3:1.7b"\n',
    )
    assert (
        main(
            [
                "build",
                "--harness",
                "opencode",
                "--collection",
                "dsh",
                "--out",
                str(tmp_path / "dist"),
            ]
        )
        == 0
    )
    assert "warning" not in capsys.readouterr().out.lower()


def test_install_and_uninstall_round_trip(xdg, tmp_path, capsys):
    target = tmp_path / "oc"
    assert (
        main(["install", "--harness", "opencode", "--scope", "project", "--target", str(target)])
        == 0
    )
    out = capsys.readouterr().out
    assert "wrote" in out
    assert "wikiskill " in out  # the resolved CLI path, for hooks
    assert (target / "plugin" / "wikiskill-logger.ts").is_file()

    assert (
        main(
            [
                "install",
                "--harness",
                "opencode",
                "--scope",
                "project",
                "--target",
                str(target),
                "--uninstall",
            ]
        )
        == 0
    )
    assert not (target / "plugin" / "wikiskill-logger.ts").exists()


def test_install_twice_says_no_changes(xdg, tmp_path, capsys):
    target = tmp_path / "oc"
    args = ["install", "--harness", "opencode", "--scope", "project", "--target", str(target)]
    main(args)
    capsys.readouterr()
    main(args)
    assert "no changes" in capsys.readouterr().out


def test_version_is_reported(capsys):
    with pytest.raises(SystemExit) as excinfo:
        main(["--version"])
    assert excinfo.value.code == 0
    assert "wikiskill" in capsys.readouterr().out


def test_sync_keeps_other_collections_published(xdg, plugin_source, opencode_source, capsys):
    """Checking one collection must not stop the logger watching the others."""
    write_manifest(xdg, "dsh", manifest_for(plugin_source))
    write_manifest(
        xdg,
        "oc",
        f'name = "oc"\nsources = [{{ path = "{opencode_source}", layout = "opencode" }}]\n'
        '[watch]\nskills = ["smoke"]\n',
    )

    assert main(["collection", "check", "dsh", "--sync"]) == 0

    runtime = json.loads(collection_mod.runtime_config_path().read_text())
    assert sorted(c["collection"] for c in runtime["collections"]) == ["dsh", "oc"]
    assert "dsh, oc" in capsys.readouterr().out


def test_install_with_one_collection_keeps_the_others_published(xdg, tmp_path, plugin_source, opencode_source):
    write_manifest(xdg, "dsh", manifest_for(plugin_source))
    write_manifest(
        xdg,
        "oc",
        f'name = "oc"\nsources = [{{ path = "{opencode_source}", layout = "opencode" }}]\n'
        '[watch]\nskills = ["smoke"]\n',
    )

    assert (
        main(
            [
                "install",
                "--harness",
                "opencode",
                "--scope",
                "project",
                "--target",
                str(tmp_path / "oc-config"),
                "--collection",
                "dsh",
            ]
        )
        == 0
    )

    runtime = json.loads(collection_mod.runtime_config_path().read_text())
    assert sorted(c["collection"] for c in runtime["collections"]) == ["dsh", "oc"]


def test_install_warns_when_no_collection_is_configured(xdg, tmp_path, capsys):
    assert (
        main(
            [
                "install",
                "--harness",
                "opencode",
                "--scope",
                "project",
                "--target",
                str(tmp_path / "oc-config"),
            ]
        )
        == 0
    )
    out = capsys.readouterr().out
    assert "the logger will record nothing" in out
    assert "collection init" in out
