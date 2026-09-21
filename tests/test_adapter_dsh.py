"""Reading data-science-harness `bench/` fixtures in place.

The contract is DSH's own: read where they live, write nothing, and ask for no new fields. What
wikiskill needs and DSH does not declare — a split, an agent name behind a plugin — wikiskill
supplies here, visibly.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from conftest import write_manifest
from wikiskill import collection as collection_mod
from wikiskill import suite as suite_mod
from wikiskill.adapters import dsh

#: The real fixture, when this machine has it. Nothing here writes to that repository.
DSH_TASKS = Path(
    os.environ.get("WIKISKILL_DSH_TASKS", "~/Projects/claude/data-science-harness/bench/tasks")
).expanduser()

FIXTURE = """
probe: routing
suite: lifecycle
status: specified

tasks:
  - id: govern-prereg
    prompt: >
      Lock in the analysis plan and register it publicly before we run anything.
    expected_skill: govern/preregister
    expected_delegates_to: [datalad]
    rigor: confirmatory

  - id: curate-raw
    prompt: I have a folder of DICOMs from the scanner. Get them into the standard layout.
    expected_skill: curate/raw-to-bids
    expected_delegates_to: [nipoppy, datalad]
    notes: DSH keeps its reasoning here; wikiskill has no field for it and does not ask for one.
"""

MANIFEST = """
name = "dsh"
sources = [{{ path = "{source}", layout = "claude-plugin" }}]

[watch]
skills = ["*"]
agents = ["*"]
commands = []
"""


def write(tmp_path, body, name="routing-lifecycle.yaml"):
    path = tmp_path / name
    path.write_text(body, encoding="utf-8")
    return path


@pytest.fixture
def dsh_collection(xdg, plugin_source):
    write_manifest(xdg, "dsh", MANIFEST.format(source=plugin_source))
    return collection_mod.load("dsh")


# --------------------------------------------------------------------------- detection


def test_a_dsh_fixture_is_recognised_and_a_wikiskill_suite_is_not():
    assert dsh.is_dsh_document({"probe": "routing", "tasks": [{"expected_skill": "a/b"}]})
    assert not dsh.is_dsh_document(
        {"suite": "toy", "tasks": [{"id": "t", "prompt": "p", "split": "val"}]}
    )
    assert not dsh.is_dsh_document({"probe": "routing", "tasks": []})
    assert not dsh.is_dsh_document("not a mapping")


def test_a_wikiskill_suite_that_mentions_a_probe_is_left_alone():
    """Both signals are needed, or a suite with a `probe` key would be rewritten."""
    assert not dsh.is_dsh_document(
        {"probe": "routing", "suite": "toy", "tasks": [{"id": "t", "prompt": "p", "split": "val"}]}
    )


# --------------------------------------------------------------------------- translation


def test_the_fixture_loads_through_the_ordinary_loader(tmp_path):
    loaded = suite_mod.load(write(tmp_path, FIXTURE))

    assert loaded.name == "routing-lifecycle"
    assert [task.id for task in loaded.tasks] == ["govern-prereg", "curate-raw"]
    assert loaded.tasks[0].expect.skill == "govern/preregister"


def test_a_split_is_supplied_by_wikiskill_since_dsh_declares_none(tmp_path):
    default = suite_mod.load(write(tmp_path, FIXTURE))
    chosen = suite_mod.load(write(tmp_path, FIXTURE, "again.yaml"), split="test")

    assert {task.split for task in default.tasks} == {dsh.DEFAULT_SPLIT}
    assert {task.split for task in chosen.tasks} == {"test"}


def test_delegated_plugins_become_agent_names(tmp_path):
    loaded = suite_mod.load(write(tmp_path, FIXTURE))

    assert loaded.tasks[0].expect.agents == ("datalad/datalad-doer",)
    assert loaded.tasks[1].expect.agents == ("nipoppy/nipoppy-doer", "datalad/datalad-doer")


def test_the_collection_answers_before_the_naming_convention(dsh_collection):
    """The collection reads the same repository DSH derives its ground truth from."""
    assert dsh.agent_names("datalad", dsh_collection) == ["datalad/datalad-doer"]
    assert dsh.agent_names("govern", dsh_collection) == ["govern/govern-doer"], (
        "no agent there, so the convention is the fallback"
    )


def test_fields_wikiskill_has_no_home_for_are_dropped_not_invented(tmp_path):
    built = dsh.to_suite_document(
        {
            "probe": "routing",
            "tasks": [{"id": "t", "prompt": "p", "expected_skill": "a/b", "rigor": "confirmatory"}],
        }
    )

    assert "rigor" not in built["tasks"][0]
    assert set(built["tasks"][0]) <= {"id", "prompt", "split", "expect", "rubric"}


def test_a_fixture_missing_what_a_task_needs_says_which(tmp_path):
    body = "probe: routing\ntasks:\n  - expected_skill: a/b\n"

    with pytest.raises(suite_mod.SuiteError) as caught:
        suite_mod.load(write(tmp_path, body))

    assert any("needs an `id`" in problem for problem in caught.value.problems)


# --------------------------------------------------------------------------- the real thing


@pytest.mark.skipif(not DSH_TASKS.is_dir(), reason="data-science-harness is not checked out here")
def test_the_real_routing_suite_loads_in_place():
    before = {path: path.stat().st_mtime_ns for path in sorted(DSH_TASKS.rglob("*.yaml"))}
    assert before, "there should be at least one fixture to read"

    for path in before:
        loaded = suite_mod.load(path)
        assert loaded.tasks, f"{path} produced no tasks"
        for task in loaded.tasks:
            assert task.judged, f"{task.id} states no expected outcome"

    after = {path: path.stat().st_mtime_ns for path in before}
    assert after == before, "reading a fixture must not touch it"
