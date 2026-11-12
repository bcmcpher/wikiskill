"""Task suite loading and the three checks a JSON schema cannot make."""

from __future__ import annotations

import pytest

from wikiskill import suite as suite_mod
from wikiskill.cli import main
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


def test_a_prompt_naming_the_qualified_route_is_refused(tmp_path):
    """Nobody writes `disseminate/dataset-release` in a prompt by accident."""
    body = """
suite: toy
tasks:
  - id: leaky
    prompt: Use disseminate/dataset-release to cut version 1.0.
    split: val
    expect: { skill: disseminate/dataset-release }
"""
    with pytest.raises(SuiteError) as caught:
        suite_mod.load(write(tmp_path, body))
    assert any("names 'disseminate/dataset-release'" in p for p in caught.value.problems)


def test_a_prompt_naming_half_the_route_is_a_warning_a_reader_judges(tmp_path):
    body = """
suite: toy
tasks:
  - id: named
    prompt: Use the dataset-release skill to cut version 1.0.
    split: val
    expect: { skill: disseminate/dataset-release }
  - id: ordinary
    prompt: Ask disseminate to cut a version of this dataset.
    split: val
    expect: { skill: disseminate/dataset-release }
"""
    loaded = suite_mod.load(write(tmp_path, body))

    assert len(loaded.warnings) == 2
    assert any("'dataset-release'" in warning for warning in loaded.warnings)
    assert any("'disseminate'" in warning for warning in loaded.warnings)


def test_an_unqualified_route_named_in_the_prompt_is_only_a_warning(tmp_path):
    """`datalad-doer` is a component name, and a component is often named after its subject."""
    body = """
suite: toy
tasks:
  - id: named
    prompt: Have the datalad-doer tag this for me.
    split: val
    expect: { agents: [datalad-doer] }
"""
    loaded = suite_mod.load(write(tmp_path, body))

    assert any("'datalad-doer'" in warning for warning in loaded.warnings)


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
    assert suite_mod.prompt_leaks(loaded.tasks[0]) == ([], [])
    assert loaded.warnings == ()


def test_every_problem_is_reported_at_once(tmp_path):
    body = """
suite: toy
tasks:
  - id: leaky
    prompt: Run govern/preregister now.
    split: val
    expect: { skill: govern/preregister }
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


# --------------------------------------------------------------------------- environment

ENV = """
suite: toy
defaults: { env: { DATALAD_AUTOSAVE: "0", LANG: C } }
tasks:
  - id: save
    prompt: Record the current state of this project.
    split: val
    verifiers:
      - { kind: file_exists, path: DONE.md }
    env: { LANG: C.UTF-8 }
"""


def test_env_folds_suite_defaults_under_the_tasks_own(tmp_path):
    task = suite_mod.load(write(tmp_path, ENV)).tasks[0]
    assert dict(task.env) == {"DATALAD_AUTOSAVE": "0", "LANG": "C.UTF-8"}


def test_env_values_must_be_strings(tmp_path):
    with pytest.raises(SuiteError):
        suite_mod.load(write(tmp_path, ENV.replace('"0"', "0")))


def test_env_may_not_touch_the_runners_isolation(tmp_path):
    body = ENV.replace("LANG: C.UTF-8", "XDG_CONFIG_HOME: /home/me/.config")
    with pytest.raises(SuiteError, match="XDG_CONFIG_HOME, which the runner owns"):
        suite_mod.load(write(tmp_path, body))


def test_setup_is_the_tasks_own_or_the_suite_defaults(tmp_path):
    body = ENV.replace(
        'defaults: { env: { DATALAD_AUTOSAVE: "0", LANG: C } }',
        'defaults: { env: { A: "1" }, setup: ["git init -q ."] }',
    )
    assert suite_mod.load(write(tmp_path, body)).tasks[0].setup == ("git init -q .",)
    own = body.replace("    env: { LANG: C.UTF-8 }", '    setup: ["touch a", "touch b"]')
    assert suite_mod.load(write(tmp_path, own)).tasks[0].setup == ("touch a", "touch b")


OVERRIDES = """
suite: toy
defaults:
  setup: ["git init -q"]
  guard: { deny: ["git push*"] }
  requires: [no-such-program-wikiskill]
  env: { A: "1" }
  secrets: [GRADER_KEY]
tasks:
  - id: cleared
    prompt: p
    split: val
    rubric: Does the reply answer?
    setup: []
    guard: {}
    requires: []
    env: {}
    secrets: []
  - id: inherited
    prompt: p
    split: val
    rubric: Does the reply answer?
  - id: unguarded
    prompt: p
    split: val
    rubric: Does the reply answer?
    guard: { deny: [] }
  - id: added
    prompt: p
    split: val
    rubric: Does the reply answer?
    env: { B: "2" }
"""


def test_an_empty_task_value_clears_the_default_and_absent_takes_it(tmp_path):
    from wikiskill.runner.run import missing_capabilities

    tasks = {t.id: t for t in suite_mod.load(write(tmp_path, OVERRIDES)).tasks}
    cleared, inherited = tasks["cleared"], tasks["inherited"]

    assert cleared.setup == ()
    assert cleared.guard_deny == ()
    assert tasks["unguarded"].guard_deny == ()
    assert cleared.requires == ()
    assert missing_capabilities(cleared) == [], "requires: [] is never skipped"

    assert inherited.setup == ("git init -q",)
    assert inherited.guard_deny == ("git push*",)
    assert missing_capabilities(inherited) == ["no-such-program-wikiskill"]


def test_an_empty_task_env_or_secrets_changes_nothing(tmp_path):
    tasks = {t.id: t for t in suite_mod.load(write(tmp_path, OVERRIDES)).tasks}

    assert dict(tasks["cleared"].env) == {"A": "1"}
    assert dict(tasks["added"].env) == {"A": "1", "B": "2"}
    assert tasks["cleared"].secrets == ("GRADER_KEY",)


def test_env_expands_home_and_host_variables(monkeypatch):
    monkeypatch.setenv("HOME", "/home/someone")
    monkeypatch.setenv("PATH", "/usr/bin")
    task = suite_mod.Task(
        id="t", prompt="p", split="val", env=(("PATH", "~/venv/bin:$PATH"), ("PLAIN", "x"))
    )

    assert task.resolved_env() == {"PATH": "/home/someone/venv/bin:/usr/bin", "PLAIN": "x"}
    assert dict(task.env)["PATH"] == "~/venv/bin:$PATH", "the task keeps what the suite said"


# --------------------------------------------------------------------------- structured results

GRADED = """
suite: toy
tasks:
  - id: graded
    prompt: Produce the brain mask for this scan.
    split: val
    verifiers:
      - %s
"""


def test_a_grader_with_a_verdict_is_accepted(tmp_path):
    verifier = (
        "{ kind: command, run: python3 grade.py, result: json, "
        "pass_when: { verdict: [acceptable, indistinguishable] }, score: score }"
    )
    path = write(tmp_path, GRADED % verifier)

    assert main(["suite", "check", str(path)]) == 0
    loaded = suite_mod.load(path).tasks[0].verifiers[0]
    assert loaded.result == "json"
    assert loaded.pass_when == (("verdict", ("acceptable", "indistinguishable")),)
    assert loaded.score == "score"


@pytest.mark.parametrize(
    "verifier, expected",
    [
        ("{ kind: command, run: x, pass_when: { verdict: [ok] } }", "`pass_when` needs `result"),
        ("{ kind: command, run: x, score: score }", "`score` needs `result: json`"),
        ("{ kind: regex, pattern: x, result: json }", "`result` applies only to a command"),
        (
            "{ kind: file_exists, path: a, result: json, score: s }",
            "`result`, `score` apply only to a command",
        ),
    ],
)
def test_result_fields_out_of_place_are_refused(tmp_path, capsys, verifier, expected):
    path = write(tmp_path, GRADED % verifier)

    assert main(["suite", "check", str(path)]) == 1
    assert expected in capsys.readouterr().out


@pytest.mark.parametrize(
    "verifier",
    [
        "{ kind: command, run: x, result: json, pass_when: {} }",
        "{ kind: command, run: x, result: json, pass_when: { verdict: [] } }",
        "{ kind: command, run: x, result: json, pass_when: { verdict: [[nested]] } }",
        "{ kind: command, run: x, result: yaml }",
    ],
)
def test_the_schema_gives_result_fields_their_shape(tmp_path, verifier):
    with pytest.raises(SuiteError):
        suite_mod.load(write(tmp_path, GRADED % verifier))


def test_a_bare_yes_in_pass_when_is_a_warning_not_an_error(tmp_path, capsys):
    bare = "{ kind: command, run: x, result: json, pass_when: { usable: [yes, maybe] } }"
    path = write(tmp_path, GRADED % bare)

    loaded = suite_mod.load(path)
    assert loaded.tasks[0].verifiers[0].pass_when == (("usable", (True, "maybe")),)
    (warning,) = loaded.warnings
    assert "`usable` accepts the boolean true" in warning
    assert "quote the value" in warning
    assert main(["suite", "check", str(path)]) == 0

    quoted = write(tmp_path, GRADED % bare.replace("[yes,", '["yes",'))
    assert suite_mod.load(quoted).warnings == ()


# --------------------------------------------------------------------------- follow-up turns

FOLLOWUPS = GOOD.replace(
    "    requires: [git]\n",
    '    requires: [git]\n    followups: ["Use the v2 tag instead.", "Now push it."]\n',
)


def test_followups_are_a_warning_that_they_are_not_sent(tmp_path, capsys):
    path = write(tmp_path, FOLLOWUPS)

    loaded = suite_mod.load(path)
    assert loaded.tasks[0].followups == ("Use the v2 tag instead.", "Now push it.")
    (warning,) = loaded.warnings
    assert "'release'" in warning
    assert "2 follow-up turn(s), which are not sent" in warning
    assert main(["suite", "check", str(path)]) == 0
    out = capsys.readouterr().out
    assert f"? {warning}" in out
    assert "ok, 1 to look at" in out


def test_a_suite_without_followups_gets_no_followup_warning(tmp_path):
    assert suite_mod.load(write(tmp_path, GOOD)).warnings == ()


def test_the_followup_warning_leaves_the_suite_hash_alone(tmp_path):
    from wikiskill import rawlog

    # A run's `suite_hash` is the hash of the file's bytes, so a warning, which only the loader
    # computes, cannot move it: the same file hashes the same before and after it is checked.
    path = write(tmp_path, FOLLOWUPS)
    before = rawlog.content_hash(path.read_bytes())
    assert suite_mod.load(path).warnings
    assert main(["suite", "check", str(path)]) == 0
    assert rawlog.content_hash(path.read_bytes()) == before


# --------------------------------------------------------------------------- secrets

SECRETS = """
suite: graded
defaults: { secrets: [FAKE_HF_TOKEN] }
tasks:
  - id: fetch
    prompt: Summarise the dataset card.
    split: val
    secrets: [FAKE_GRADER_KEY]
    verifiers:
      - { kind: command, run: "true" }
"""


def test_secrets_join_the_defaults_and_the_tasks_own(tmp_path):
    task = suite_mod.load(write(tmp_path, SECRETS)).tasks[0]
    assert task.secrets == ("FAKE_HF_TOKEN", "FAKE_GRADER_KEY")


def test_a_task_without_its_own_secrets_keeps_the_defaults(tmp_path):
    body = SECRETS.replace("    secrets: [FAKE_GRADER_KEY]\n", "")
    assert suite_mod.load(write(tmp_path, body)).tasks[0].secrets == ("FAKE_HF_TOKEN",)


def test_a_suite_without_secrets_declares_none(tmp_path):
    assert all(not task.secrets for task in suite_mod.load(write(tmp_path, GOOD)).tasks)


def test_a_secret_may_not_also_be_set_in_env(tmp_path, capsys):
    body = SECRETS.replace("    secrets: [FAKE_GRADER_KEY]", '    env: { FAKE_HF_TOKEN: "x" }')
    path = write(tmp_path, body)
    with pytest.raises(SuiteError, match="FAKE_HF_TOKEN as a secret and also sets it in `env`"):
        suite_mod.load(path)
    assert main(["suite", "check", str(path)]) == 1
    assert "also sets it in `env`" in capsys.readouterr().out


def test_a_secret_may_not_take_a_reserved_name(tmp_path, capsys):
    body = SECRETS.replace("[FAKE_GRADER_KEY]", "[OPENCODE_CONFIG_CONTENT]")
    path = write(tmp_path, body)
    with pytest.raises(SuiteError, match="OPENCODE_CONFIG_CONTENT as a secret, a reserved name"):
        suite_mod.load(path)
    assert main(["suite", "check", str(path)]) == 1
    assert "reserved name" in capsys.readouterr().out


@pytest.mark.parametrize("reference", ["$FAKE_HF_TOKEN", "${FAKE_HF_TOKEN}", "x:$FAKE_HF_TOKEN/y"])
def test_env_may_not_expand_a_secret(tmp_path, capsys, reference):
    body = SECRETS.replace(
        "    secrets: [FAKE_GRADER_KEY]", f"    env: {{ FAKE_FOO: '{reference}' }}"
    )
    path = write(tmp_path, body)
    with pytest.raises(SuiteError, match="sets `env` FAKE_FOO from the secret FAKE_HF_TOKEN"):
        suite_mod.load(path)
    assert main(["suite", "check", str(path)]) == 1


def test_env_may_name_a_longer_variable_that_starts_like_a_secret(tmp_path):
    body = SECRETS.replace(
        "    secrets: [FAKE_GRADER_KEY]", "    env: { FAKE_FOO: $FAKE_HF_TOKENS }"
    )
    assert suite_mod.load(write(tmp_path, body)).tasks[0].env == (("FAKE_FOO", "$FAKE_HF_TOKENS"),)


@pytest.mark.parametrize(
    "name",
    [
        "CLAUDE_CONFIG_DIR",
        "CLAUDECODE",
        "ANTHROPIC_BASE_URL",
        "ANTHROPIC_AUTH_TOKEN",
        "CLAUDE_CODE_SUBAGENT_MODEL",
        "HOME",
        "PATH",
        "XDG_DATA_HOME",
    ],
)
def test_a_secret_may_not_name_what_a_runner_isolates_or_routes_with(tmp_path, name):
    with pytest.raises(SuiteError, match=f"{name} as a secret, a reserved name"):
        suite_mod.load(write(tmp_path, SECRETS.replace("FAKE_GRADER_KEY", name)))


def test_a_hosted_anthropic_key_is_the_one_allowed_exception(tmp_path):
    task = suite_mod.load(write(tmp_path, SECRETS.replace("FAKE_GRADER_KEY", "ANTHROPIC_API_KEY")))
    assert "ANTHROPIC_API_KEY" in task.tasks[0].secrets


def test_a_secret_must_be_a_variable_name(tmp_path):
    with pytest.raises(SuiteError, match="1BAD"):
        suite_mod.load(write(tmp_path, SECRETS.replace("FAKE_GRADER_KEY", "1BAD")))


def test_secret_env_reads_only_what_the_host_sets(monkeypatch):
    monkeypatch.setenv("FAKE_GRADER_TOKEN", "fake-grader-value-123")
    monkeypatch.delenv("FAKE_UNSET_TOKEN", raising=False)
    task = suite_mod.Task(
        id="t", prompt="p", split="val", secrets=("FAKE_GRADER_TOKEN", "FAKE_UNSET_TOKEN")
    )
    assert task.secret_env() == {"FAKE_GRADER_TOKEN": "fake-grader-value-123"}


#: Two tasks; only the first declares a secret.
TWO_TASKS = """
suite: graded
tasks:
  - id: fetch
    prompt: Summarise the dataset card.
    split: val
    secrets: [FAKE_GRADER_KEY]
    verifiers:
      - { kind: command, run: "true" }
  - id: tidy
    prompt: Tidy the notes.
    split: val
    verifiers:
      - { kind: command, run: "true" }
"""


def test_every_task_withholds_a_secret_any_task_declares(tmp_path):
    fetch, tidy = suite_mod.load(write(tmp_path, TWO_TASKS)).tasks

    assert fetch.secrets == ("FAKE_GRADER_KEY",)
    assert tidy.secrets == (), "a verifier gets only its own task's secrets"
    assert fetch.withheld == tidy.withheld == ("FAKE_GRADER_KEY",)


def test_another_tasks_env_may_not_expand_a_secret(tmp_path, capsys):
    body = TWO_TASKS.replace(
        "    prompt: Tidy the notes.\n",
        "    prompt: Tidy the notes.\n    env: { FAKE_FOO: '$FAKE_GRADER_KEY' }\n",
    )
    path = write(tmp_path, body)
    with pytest.raises(SuiteError, match="'tidy' sets `env` FAKE_FOO from the secret FAKE_GRADER"):
        suite_mod.load(path)
    assert main(["suite", "check", str(path)]) == 1


def test_another_tasks_env_may_not_set_a_secret(tmp_path):
    body = TWO_TASKS.replace(
        "    prompt: Tidy the notes.\n",
        "    prompt: Tidy the notes.\n    env: { FAKE_GRADER_KEY: x }\n",
    )
    with pytest.raises(SuiteError, match="FAKE_GRADER_KEY in `env`, which another task declares"):
        suite_mod.load(write(tmp_path, body))
