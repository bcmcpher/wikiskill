"""Deterministic verifiers, and the line between a check that fails and one that cannot run.

Real files in a real temporary workdir, real subprocesses: a verifier's whole job is to observe
what actually happened on disk, so a mocked one would test nothing.
"""

from __future__ import annotations

import dataclasses
import sys
from pathlib import Path

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


def test_command_sees_the_tasks_own_environment(workdir):
    task = Task(
        id="t",
        prompt="p",
        split="val",
        env=(("MARKER", "set"),),
        verifiers=(Verifier(kind="command", run='test "$MARKER" = set'),),
    )
    _, passed = verify.verify_task(task, workdir=workdir)

    assert passed


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


# --------------------------------------------------------------------------- structured results

GRADER = Path(__file__).parent / "fixtures" / "grader.py"
ACCEPTED = (("verdict", ("acceptable", "indistinguishable")),)


def graded(arguments: str, **fields) -> Verifier:
    """A command verifier that runs the synthetic grader and reads its JSON result."""
    return Verifier(
        kind="command",
        run=f"{sys.executable} {GRADER} {arguments}",
        result="json",
        pass_when=fields.pop("pass_when", ACCEPTED),
        score="score",
        **fields,
    )


def test_an_acceptable_verdict_passes_and_keeps_the_result(workdir):
    result = run(graded("acceptable 71.5"), workdir)

    assert result.passed
    assert result.result == {"verdict": "acceptable", "score": 71.5}
    record = result.as_dict()
    assert record["result"] == {"verdict": "acceptable", "score": 71.5}
    assert record["score_field"] == "score"


def test_a_valid_but_marginal_verdict_fails_and_names_it(workdir):
    result = run(graded("marginal 41"), workdir)

    assert not result.passed
    assert '`verdict` is "marginal"' in result.detail
    assert result.result == {"verdict": "marginal", "score": 41}


def test_an_invalid_submission_exiting_nonzero_fails_with_its_result_kept(workdir):
    # The verdict is listed as acceptable here, so only the exit code can fail it.
    verifier = graded("invalid 0 --exit 1", pass_when=(("verdict", ("invalid",)),))
    result = run(verifier, workdir)

    assert not result.passed
    assert result.exit_code == 1
    assert result.result == {"verdict": "invalid", "score": 0}


def test_log_lines_before_the_result_are_skipped(workdir):
    result = run(graded("acceptable 80 --log 2"), workdir)

    assert result.passed
    assert result.result == {"verdict": "acceptable", "score": 80}
    assert "grading step 1" in result.output, "the output tail still keeps the log"


def test_a_crashing_scorer_is_infrastructure_naming_the_verifier(workdir):
    verifier = graded("acceptable 1 --crash")

    with pytest.raises(verify.VerifierError, match="printed no JSON object") as caught:
        run(verifier, workdir)
    assert str(GRADER) in str(caught.value)


def test_a_json_value_that_is_not_an_object_is_infrastructure(workdir):
    with pytest.raises(verify.VerifierError, match="no JSON object"):
        run(Verifier(kind="command", run="echo '[1, 2]'", result="json"), workdir)


def test_an_oversized_result_is_infrastructure(workdir):
    with pytest.raises(verify.VerifierError, match="over the 65536-byte cap"):
        run(graded(f"acceptable 1 --pad {verify.RESULT_CAP}"), workdir)


def printing(workdir, text: str) -> Verifier:
    """A `result: json` verifier whose command prints ``text`` exactly, written as UTF-8."""
    (workdir / "out.txt").write_text(text, encoding="utf-8")
    return Verifier(kind="command", run="cat out.txt", result="json")


def test_the_cap_counts_bytes_as_results_jsonl_stores_them(workdir):
    # 25,000 `é` are 50 KB in UTF-8 and 150 KB ASCII-escaped; results.jsonl stores the first.
    result = run(printing(workdir, '{"note": "' + "é" * 25_000 + '"}'), workdir)
    assert result.result == {"note": "é" * 25_000}


def test_spaces_in_the_grader_output_do_not_count_against_the_cap(workdir):
    padded = "{" + ", ".join(f'"k{i}":{" " * 20}{i}' for i in range(3000)) + "}"
    assert len(padded) > verify.RESULT_CAP
    assert run(printing(workdir, padded), workdir).result is not None


@pytest.mark.parametrize("constant", ["NaN", "Infinity", "-Infinity"])
def test_a_non_finite_constant_is_infrastructure(workdir, constant):
    with pytest.raises(verify.VerifierError, match=f"printed {constant}"):
        run(printing(workdir, f'{{"verdict": "ok", "score": {constant}}}'), workdir)


def test_a_non_finite_constant_in_a_log_line_before_the_result_is_skipped(workdir):
    result = run(printing(workdir, '{"debug": NaN}\n{"verdict": "ok"}\n'), workdir)
    assert result.result == {"verdict": "ok"}


def test_a_non_finite_constant_in_a_last_line_result_is_infrastructure(workdir):
    with pytest.raises(verify.VerifierError, match="printed Infinity"):
        run(printing(workdir, 'grading\n{"verdict": "ok", "score": Infinity}\n'), workdir)


def test_an_unpaired_surrogate_escape_is_infrastructure(workdir):
    # Valid JSON text, but the string it reads as cannot be written to results.jsonl as UTF-8.
    with pytest.raises(verify.VerifierError, match="unpaired surrogate"):
        run(printing(workdir, '{"verdict": "ok", "s": "\\ud800"}'), workdir)


def test_json_nested_too_deeply_is_infrastructure(workdir):
    deep = '{"a": ' * 100_000 + "1" + "}" * 100_000
    with pytest.raises(verify.VerifierError, match="nested too deeply"):
        run(printing(workdir, deep), workdir)


def test_stderr_is_never_parsed(workdir):
    verifier = Verifier(kind="command", run='echo \'{"verdict": "ok"}\' >&2', result="json")

    with pytest.raises(verify.VerifierError):
        run(verifier, workdir)


def test_a_missing_field_is_named(workdir):
    verifier = graded("acceptable 1", pass_when=(("grade", ("A",)),))
    result = run(verifier, workdir)

    assert not result.passed
    assert "`grade` is missing" in result.detail


def test_a_boolean_is_not_a_number(workdir):
    verifier = Verifier(
        kind="command", run="echo '{\"ok\": true}'", result="json", pass_when=(("ok", (1,)),)
    )

    assert not run(verifier, workdir).passed
    assert run(dataclasses.replace(verifier, pass_when=(("ok", (True,)),)), workdir).passed


@pytest.mark.parametrize("arguments", ["acceptable 71.5", "marginal 41", "invalid 0 --exit 1"])
def test_negate_flips_a_structured_verdict(workdir, arguments):
    plain = run(graded(arguments), workdir)
    negated = run(graded(arguments, negate=True), workdir)

    assert negated.passed is not plain.passed
    assert negated.result == plain.result


def test_a_plain_command_records_no_result(workdir):
    record = run(Verifier(kind="command", run="echo '{\"a\": 1}'"), workdir).as_dict()

    assert "result" not in record
    assert "score_field" not in record


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
