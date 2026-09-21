"""Deterministic verifiers, and the line between a check that fails and one that cannot run.

Real files in a real temporary workdir, real subprocesses: a verifier's whole job is to observe
what actually happened on disk, so a mocked one would test nothing.
"""

from __future__ import annotations

import sys

import pytest

from wikiskill import suite as suite_mod
from wikiskill.score import verify
from wikiskill.suite import SuiteError, Task, Verifier


@pytest.fixture
def workdir(tmp_path):
    root = tmp_path / "work"
    root.mkdir()
    (root / "CHANGELOG.md").write_text("# Changelog\n\n## v1.0\n", encoding="utf-8")
    return root


def run(verifier, workdir, **kwargs):
    return verify.run_verifier(verifier, workdir=workdir, **kwargs)


# --------------------------------------------------------------------------- command


def test_command_passes_on_the_expected_exit_code(workdir):
    result = run(Verifier(kind="command", run="test -f CHANGELOG.md"), workdir)

    assert result.passed
    assert result.exit_code == 0
    assert "exited 0, expected 0" in result.detail


def test_command_fails_on_a_different_exit_code(workdir):
    result = run(Verifier(kind="command", run="test -f MISSING.md"), workdir)

    assert not result.passed
    assert result.exit_code == 1


def test_command_can_expect_a_nonzero_exit(workdir):
    result = run(Verifier(kind="command", run="test -f MISSING.md", expect_exit=1), workdir)

    assert result.passed, "a task can require that a check *fails*"


def test_command_runs_in_the_workdir_and_keeps_its_output(workdir):
    result = run(Verifier(kind="command", run="pwd; echo boom >&2; false"), workdir)

    assert not result.passed
    assert str(workdir) in result.output
    assert "boom" in result.output


def test_command_output_is_truncated(workdir):
    flood = f"{sys.executable} -c \"print('x' * 10000)\""
    result = run(Verifier(kind="command", run=flood), workdir)

    assert len(result.output) <= verify.OUTPUT_TAIL


def test_command_does_not_inherit_the_session_environment(workdir, monkeypatch):
    monkeypatch.setenv("OPENCODE_CONFIG_CONTENT", "{}")
    monkeypatch.setenv("WIKISKILL_ORIGIN", "eval")

    result = run(Verifier(kind="command", run="env"), workdir)

    assert "OPENCODE_CONFIG_CONTENT" not in result.output
    assert "WIKISKILL_ORIGIN" not in result.output


def test_a_timing_out_command_is_infrastructure_not_a_failure(workdir):
    verifier = Verifier(kind="command", run=f'{sys.executable} -c "import time; time.sleep(5)"')

    with pytest.raises(verify.VerifierError) as caught:
        run(verifier, workdir, timeout_s=1)

    assert "timed out after 1s" in str(caught.value)


def test_a_command_that_cannot_start_is_infrastructure(workdir, monkeypatch):
    def refuse(*args, **kwargs):
        raise OSError("no shell here")

    monkeypatch.setattr(verify.subprocess, "run", refuse)

    with pytest.raises(verify.VerifierError) as caught:
        run(Verifier(kind="command", run="true"), workdir)

    assert "could not be started" in str(caught.value)


# --------------------------------------------------------------------------- file_exists


def test_file_exists_both_ways(workdir):
    assert run(Verifier(kind="file_exists", path="CHANGELOG.md"), workdir).passed
    assert not run(Verifier(kind="file_exists", path="nope.md"), workdir).passed


def test_file_exists_refuses_to_look_outside_the_workdir(workdir):
    for path in ("/etc/passwd", "../escape.md", "~/secrets"):
        with pytest.raises(verify.VerifierError):
            run(Verifier(kind="file_exists", path=path), workdir)


# --------------------------------------------------------------------------- regex


def test_regex_matches_the_final_text_by_default(workdir):
    verifier = Verifier(kind="regex", pattern=r"v1\.0")

    assert run(verifier, workdir, final_text="released v1.0 today").passed
    assert not run(verifier, workdir, final_text="released something").passed


def test_regex_can_match_the_transcript(workdir):
    verifier = Verifier(kind="regex", pattern="datalad", target="transcript")

    assert run(verifier, workdir, final_text="done", transcript="I will use datalad\ndone").passed
    assert not run(verifier, workdir, final_text="done", transcript="done").passed


def test_regex_can_match_a_file(workdir):
    verifier = Verifier(kind="regex", pattern=r"## v1\.0", target="file", path="CHANGELOG.md")

    assert run(verifier, workdir).passed


def test_regex_on_a_missing_file_is_a_failure_not_a_crash(workdir):
    verifier = Verifier(kind="regex", pattern="anything", target="file", path="nope.md")

    result = run(verifier, workdir)

    assert not result.passed, "the model never wrote the file: that is a verdict, not an error"
    assert "does not exist" in result.detail


# --------------------------------------------------------------------------- negate


def test_negate_inverts_every_kind(workdir):
    assert not run(Verifier(kind="file_exists", path="CHANGELOG.md", negate=True), workdir).passed
    assert run(Verifier(kind="file_exists", path="nope.md", negate=True), workdir).passed

    forbidden = Verifier(kind="regex", pattern="TODO", negate=True)
    assert run(forbidden, workdir, final_text="all done").passed
    assert not run(forbidden, workdir, final_text="TODO: finish").passed

    assert run(Verifier(kind="command", run="false", negate=True), workdir).passed


def test_negate_keeps_the_observation_in_the_detail(workdir):
    result = run(Verifier(kind="file_exists", path="nope.md", negate=True), workdir)

    assert result.passed
    assert result.detail == "negated: nope.md does not exist"


# --------------------------------------------------------------------------- whole task


def task(*verifiers) -> Task:
    return Task(id="t", prompt="do it", split="val", verifiers=tuple(verifiers))


def test_a_task_with_no_verifiers_has_no_verdict(workdir):
    results, passed = verify.verify_task(task(), workdir=workdir)

    assert results == []
    assert passed is None, "nothing checked must never read as everything passed"


def test_every_verifier_runs_and_all_must_pass(workdir):
    results, passed = verify.verify_task(
        task(
            Verifier(kind="file_exists", path="CHANGELOG.md"),
            Verifier(kind="file_exists", path="nope.md"),
            Verifier(kind="command", run="true"),
        ),
        workdir=workdir,
    )

    assert [result.passed for result in results] == [True, False, True]
    assert passed is False


def test_all_passing_is_a_pass(workdir):
    _, passed = verify.verify_task(
        task(
            Verifier(kind="file_exists", path="CHANGELOG.md"), Verifier(kind="command", run="true")
        ),
        workdir=workdir,
    )

    assert passed is True


def test_a_missing_workdir_is_infrastructure(tmp_path):
    with pytest.raises(verify.VerifierError):
        verify.verify_task(task(Verifier(kind="command", run="true")), workdir=None)

    with pytest.raises(verify.VerifierError):
        verify.verify_task(
            task(Verifier(kind="command", run="true")), workdir=tmp_path / "never-created"
        )


# --------------------------------------------------------------------------- load-time checks


SUITE = """
suite: toy
tasks:
  - id: one
    prompt: Make the thing.
    split: val
    verifiers:
      - %s
"""


def load(tmp_path, verifier: str):
    path = tmp_path / "suite.yaml"
    path.write_text(SUITE % verifier, encoding="utf-8")
    return suite_mod.load(path)


@pytest.mark.parametrize(
    "verifier, expected",
    [
        ("{ kind: file_exists, path: /etc/passwd }", "must be relative"),
        ("{ kind: file_exists, path: ../escape }", "must not climb out"),
        ("{ kind: file_exists, path: ~/secrets }", "must be relative"),
        ("{ kind: regex, pattern: '(unclosed' }", "not a valid regular expression"),
        ("{ kind: regex, pattern: 'x', target: file }", "needs a `path`"),
    ],
)
def test_bad_verifiers_are_refused_when_the_suite_is_read(tmp_path, verifier, expected):
    with pytest.raises(SuiteError) as caught:
        load(tmp_path, verifier)

    assert any(expected in problem for problem in caught.value.problems), caught.value.problems


def test_a_good_verifier_still_loads(tmp_path):
    loaded = load(
        tmp_path, "{ kind: regex, pattern: 'v1\\\\.0', target: file, path: CHANGELOG.md }"
    )

    verifier = loaded.tasks[0].verifiers[0]
    assert verifier.target == "file"
    assert verifier.path == "CHANGELOG.md"
