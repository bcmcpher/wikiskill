"""The helpers both backends share: model names, event fields, and a unit's starting state."""

from __future__ import annotations

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
