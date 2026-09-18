"""Task suite loading and the three checks a JSON schema cannot make."""

from __future__ import annotations

import pytest

from wikiskill import suite as suite_mod
from wikiskill.suite import SuiteError

GOOD = """
suite: toy
defaults: { repeats: 2, timeout_s: 120, max_steps: 20 }
tasks:
  - id: release
    prompt: Cut version 1.0 so the paper can cite a fixed version.
    split: val
    expect: { skill: disseminate/dataset-release, agents: [datalad-doer] }
    verifiers:
      - { kind: file_exists, path: CHANGELOG.md }
    requires: [git]
    guard: { deny: ["git push*"] }
  - id: review
    prompt: Check whether these scans are usable before we analyse them.
    split: test
    expect: { skill: govern/qc-review }
    repeats: 5
"""


def write(tmp_path, body: str, name: str = "suite.yaml"):
    path = tmp_path / name
    path.write_text(body, encoding="utf-8")
    return path


def test_loads_and_folds_defaults(tmp_path):
    loaded = suite_mod.load(write(tmp_path, GOOD))

    assert loaded.name == "toy"
    assert [task.id for task in loaded.tasks] == ["release", "review"]
    release, review = loaded.tasks
    assert release.repeats == 2, "the suite default applies"
    assert review.repeats == 5, "a task overrides the default"
    assert release.timeout_s == 120
    assert release.guard_deny == ("git push*",)
    assert release.requires == ("git",)
    assert release.expect.primary == "disseminate/dataset-release"
    assert release.expect.agents == ("datalad-doer",)
    assert [v.kind for v in release.verifiers] == ["file_exists"]
    assert loaded.split("test") == [review]


def test_root_is_the_suite_directory(tmp_path):
    loaded = suite_mod.load(write(tmp_path, GOOD))
    assert loaded.root == tmp_path.resolve()


def test_schema_rejects_an_unknown_split(tmp_path):
    body = GOOD.replace("split: val", "split: holdout")
    with pytest.raises(SuiteError) as caught:
        suite_mod.load(write(tmp_path, body))
    assert any("holdout" in problem for problem in caught.value.problems)


def test_duplicate_task_ids_are_named(tmp_path):
    body = GOOD.replace("id: review", "id: release")
    with pytest.raises(SuiteError) as caught:
        suite_mod.load(write(tmp_path, body))
    assert any("duplicate task id 'release'" in problem for problem in caught.value.problems)


def test_task_without_an_expected_outcome_is_rejected(tmp_path):
    body = """
suite: toy
tasks:
  - id: vague
    prompt: Do something useful with this dataset.
    split: val
"""
    with pytest.raises(SuiteError) as caught:
        suite_mod.load(write(tmp_path, body))
    assert any("declares no expected outcome" in problem for problem in caught.value.problems)


def test_prompt_naming_its_expected_skill_is_a_leak(tmp_path):
    body = """
suite: toy
tasks:
  - id: leaky
    prompt: Use the dataset-release skill to cut version 1.0.
    split: val
    expect: { skill: disseminate/dataset-release }
"""
    with pytest.raises(SuiteError) as caught:
        suite_mod.load(write(tmp_path, body))
    assert any("names 'dataset-release'" in problem for problem in caught.value.problems)


def test_prompt_naming_the_plugin_is_also_a_leak(tmp_path):
    body = """
suite: toy
tasks:
  - id: leaky
    prompt: Ask disseminate to cut a version of this dataset.
    split: val
    expect: { skill: disseminate/dataset-release }
"""
    with pytest.raises(SuiteError) as caught:
        suite_mod.load(write(tmp_path, body))
    assert any("names 'disseminate'" in problem for problem in caught.value.problems)


def test_expected_agent_named_in_the_prompt_is_a_leak(tmp_path):
    body = """
suite: toy
tasks:
  - id: leaky
    prompt: Have the datalad doer tag this for me.
    split: val
    expect: { agents: [datalad-doer] }
"""
    with pytest.raises(SuiteError) as caught:
        suite_mod.load(write(tmp_path, body))
    assert any("names 'datalad-doer'" in problem for problem in caught.value.problems)


def test_a_word_shared_with_the_route_is_not_a_leak(tmp_path):
    """`release` alone does not name `dataset-release`; only the whole identifier does."""
    body = """
suite: toy
tasks:
  - id: fine
    prompt: Release a citable version of the dataset for the paper.
    split: val
    expect: { skill: disseminate/dataset-release }
"""
    loaded = suite_mod.load(write(tmp_path, body))
    assert suite_mod.prompt_leaks(loaded.tasks[0]) == []


def test_every_problem_is_reported_at_once(tmp_path):
    body = """
suite: toy
tasks:
  - id: leaky
    prompt: Run dataset-release now.
    split: val
    expect: { skill: dataset-release }
  - id: leaky
    prompt: Do something.
    split: val
"""
    with pytest.raises(SuiteError) as caught:
        suite_mod.load(write(tmp_path, body))
    kinds = {
        "leak": any("names" in p for p in caught.value.problems),
        "duplicate": any("duplicate" in p for p in caught.value.problems),
        "unjudged": any("no expected outcome" in p for p in caught.value.problems),
    }
    assert all(kinds.values()), caught.value.problems


def test_unreadable_and_unparseable_files_are_suite_errors(tmp_path):
    with pytest.raises(SuiteError):
        suite_mod.load(tmp_path / "missing.yaml")
    with pytest.raises(SuiteError):
        suite_mod.load(write(tmp_path, "suite: [unclosed\n"))
    with pytest.raises(SuiteError):
        suite_mod.load(write(tmp_path, "- not a mapping\n"))


def test_leak_terms_cover_both_halves_of_a_name():
    assert suite_mod.leak_terms("govern/preregister") == [
        "govern/preregister",
        "preregister",
        "govern",
    ]
    assert suite_mod.leak_terms("datalad-doer") == ["datalad-doer"]
