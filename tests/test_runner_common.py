"""The helpers both backends share: model names, event fields, and a unit's starting state."""

from __future__ import annotations

import dataclasses

import pytest

from wikiskill import names
from wikiskill.runner import base as runner_base
from wikiskill.runner import common
from wikiskill.suite import Route, Task

#: A valid ULID, because a run id is one.
RUN_ID = "01ABCDEFGHJKMNPQRSTVWXYZ01"


def unit(*setup, env=()):
    task = Task(
        id="release",
        prompt="Cut version 1.0.",
        split="val",
        expect=Route(skill="dataset-release"),
        setup=tuple(setup),
        env=tuple(env),
    )
    return runner_base.Unit(
        run_id=RUN_ID, suite="toy", task=task, model="ollama/qwen3:8b", condition="off", repeat=0
    )


@pytest.mark.parametrize(
    ("model", "expected"),
    [
        ("ollama/qwen3:30b-a3b", ("ollama", "qwen3:30b-a3b")),
        ("openrouter/meta/llama-3", ("openrouter", "meta/llama-3")),
        ("qwen3:30b-a3b", ("unknown", "qwen3:30b-a3b")),
        # nothing after the slash: the whole name is the model, from no known provider
        ("ollama/", ("unknown", "ollama/")),
    ],
)
def test_split_model(model, expected):
    assert common.split_model(model) == expected
    assert common.model_id(model) == expected[1]


@pytest.mark.parametrize(
    "model", ["ollama/qwen3:30b-a3b", "openrouter/meta/llama-3", "qwen3:30b-a3b", "/qwen3"]
)
def test_model_id_agrees_with_names_except_on_a_trailing_slash(model):
    assert common.model_id(model) == names.model_id(model)
    assert common.model_id("ollama/") != names.model_id("ollama/")


def test_string_field_is_the_first_non_empty_string():
    source = {"description": "", "prompt": 3, "args": "go", "name": "later"}
    assert common.string_field(source, "description", "prompt", "args", "name") == "go"
    assert common.string_field(source, "missing", "prompt") is None


def test_setup_runs_in_the_workdir_with_the_tasks_env_and_logs_each_command(tmp_path):
    workdir = tmp_path / "work"
    workdir.mkdir()
    common.run_setup(
        unit('printf "$MARK" > state.txt', env=(("MARK", "ready"),)), workdir, tmp_path
    )
    assert (workdir / "state.txt").read_text() == "ready"
    assert "$ printf" in (tmp_path / "setup.log").read_text()


def test_no_setup_writes_no_log(tmp_path):
    common.run_setup(unit(), tmp_path, tmp_path)
    assert not (tmp_path / "setup.log").exists()


def test_a_failing_setup_command_stops_the_rest_and_says_why(tmp_path):
    with pytest.raises(runner_base.RunnerError) as caught:
        common.run_setup(unit("true", "echo nope >&2; exit 3", "touch never"), tmp_path, tmp_path)
    assert str(caught.value) == "setup `echo nope >&2; exit 3` for task 'release' exited 3: nope"
    assert not (tmp_path / "never").exists()


def test_git_init_makes_a_repository(tmp_path):
    common.git_init(tmp_path)
    assert (tmp_path / ".git").is_dir()


class Stub(runner_base.Backend):
    """Only what `prepare_workdir` reads: the suite root."""

    def __init__(self, suite_root):
        self.suite_root = suite_root

    def version(self):
        return "0"

    def preflight(self, model):
        return runner_base.PreflightResult(model=model, ok=True)

    def prepare(self, unit):
        raise NotImplementedError

    def execute(self, unit):
        raise NotImplementedError

    def normalize(self, trajectory):
        return []


def with_fixtures(task_unit, fixtures):
    return dataclasses.replace(
        task_unit, task=dataclasses.replace(task_unit.task, fixtures=fixtures)
    )


def test_prepare_workdir_copies_fixtures_then_runs_setup_then_inits(tmp_path):
    (tmp_path / "suite" / "start").mkdir(parents=True)
    (tmp_path / "suite" / "start" / "README").write_text("seeded")
    root = tmp_path / "unit"
    root.mkdir()
    (root / "work").mkdir()
    (root / "work" / "stale").write_text("from a previous run")

    chosen = with_fixtures(unit("cat README > copied"), "start")
    workdir = Stub(tmp_path / "suite").prepare_workdir(chosen, root)

    assert workdir == root / "work"
    assert not (workdir / "stale").exists(), "a previous run's workdir is replaced"
    assert (workdir / "copied").read_text() == "seeded", "setup runs after the fixtures are copied"
    assert (workdir / ".git").is_dir()


def test_prepare_workdir_without_fixtures_starts_empty(tmp_path):
    workdir = Stub(tmp_path).prepare_workdir(unit(), tmp_path)
    assert sorted(p.name for p in workdir.iterdir()) == [".git"]


def test_prepare_workdir_refuses_a_missing_fixture_directory(tmp_path):
    with pytest.raises(runner_base.RunnerError, match="names a fixture directory that is not"):
        Stub(tmp_path).prepare_workdir(with_fixtures(unit(), "absent"), tmp_path)


# --------------------------------------------------------------------------- redaction

KEY = "ghp_" + "A" * 36


def test_scrubber_redacts_a_key_and_an_environment_value():
    scrub = common.Scrubber.of(True, {"DATASET_TOKEN": "s3cr3t-value-123"}, 1024)
    text, truncated, found = scrub.text(f"token {KEY} and s3cr3t-value-123")

    assert text == "token [REDACTED:api_key] and [REDACTED:env_value]"
    assert not truncated
    assert {entry["kind"] for entry in found} == {"api_key", "env_value"}


def test_scrubber_redacts_before_it_bounds():
    scrub = common.Scrubber.of(True, {}, 20)
    text, truncated, found = scrub.text("x" * 9 + " " + KEY)

    assert truncated
    assert "ghp_" not in text and text.startswith("x" * 9 + " [REDACTED")
    assert found == [{"kind": "api_key", "count": 1}]


def test_a_disabled_scrubber_only_bounds():
    scrub = common.Scrubber.of(False, {"DATASET_TOKEN": "s3cr3t-value-123"}, 1024)

    assert scrub.secrets == ()
    assert scrub.text(f"{KEY} s3cr3t-value-123") == (f"{KEY} s3cr3t-value-123", False, [])
    assert scrub.value({"k": KEY}) == ({"k": KEY}, [])


def test_scrubber_redacts_every_string_in_a_nested_input():
    scrub = common.Scrubber.of(True, {}, 1024)
    clean, found = scrub.value({"command": f"echo {KEY}", "env": [{"v": KEY}], "n": 3})

    assert clean == {
        "command": "echo [REDACTED:api_key]",
        "env": [{"v": "[REDACTED:api_key]"}],
        "n": 3,
    }
    assert common.merged(found) == [{"kind": "api_key", "count": 2}]
