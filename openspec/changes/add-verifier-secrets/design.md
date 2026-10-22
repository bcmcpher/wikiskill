## Context

Environments are built in five places: `OpenCodeRunner._env` (session, `runner/opencode.py:587`),
the OpenCode export step (`:802`), `ClaudeCodeRunner.env_for` (`runner/claude.py:245`), `run_setup`
(`runner/common.py:83`), and `score/verify.py:_env` for verifiers. Two more processes belong to no
unit: OpenCode's harness preflight probe (`harness_preflight`), and each backend's `--version`
check. Claude Code's preflight is HTTP from the runner's own process. `redact.py` already scrubs
secret-looking environment values from logged events (`env_secrets`, `redact`).

## Goals / Non-Goals

**Goals:**
- One rule, applied at every place an environment is built, for which variables a unit's processes
  may see.
- No secret value written by wikiskill anywhere under the run directory, or sent to a judge.

**Non-Goals:**
- Sandboxing the agent's shell. An agent that can read the host's files can still read a credential
  stored in a file; this change covers the environment only.
- Withholding variables a suite does not name. An allowlist was considered and rejected for now:
  it is breaking, and every existing suite would need `env` additions.

## Decisions

- **Union across defaults and task.** Stripping more is never harmful, so a default secret stays
  withheld even when a task adds its own. This differs from `requires` and `guard`, which a task
  replaces; the difference is stated in the schema description.
- **One helper for withheld names.** A function in `runner/common.py` takes an environment and a task
  and returns the environment without its secrets. Every session, export and setup site calls it.
  The verifier builds its own environment and adds the secrets back from the host.
- **No unit, every secret.** A process started for the run but for no one unit, such as a preflight
  probe, runs without the union of all the suite's secrets. The backend receives that union when it
  is built, and a sibling helper drops a list of names rather than one task's.
- **Refuse at start, not per unit.** A missing secret is a configuration error for the whole run;
  failing every unit as `infra_error` would waste a sweep's time. The check runs after preflight
  arguments are parsed and before any unit directory is made.
- **Redact by value.** The verifier's stored output and the logged events pass each secret's host
  value to `redact.redact` as an extra value, so a scorer that echoes its configuration does not
  leak it.

## Risks / Trade-offs

- [Risk] A new environment-building site added later skips the helper → Mitigation: a test runs a
  unit on each backend with a fake secret and asserts its value appears in no file under the run.
- [Risk] A secret's value is short or common and redaction hides unrelated text → Mitigation: values
  under 8 characters are refused at the start-of-run check.
- [Risk] Users read "secrets" as a sandbox → Mitigation: the docs say it covers the environment only,
  and name files on disk as the remaining exposure.
- [Risk] A task's `env` expands a secret (`FOO: $HF_TOKEN`) and hands its value to the session under
  another name → Mitigation: loading refuses an `env` value that refers to a declared secret.
- [Risk] A secret names a variable the runner sets for isolation (`CLAUDE_CONFIG_DIR`, `HOME`) and,
  stripped last, undoes it → Mitigation: one reserved set for both runners is refused at load;
  `ANTHROPIC_API_KEY` is the commented exception, refused at start when the session needs it.
- [Risk] The session's credential is also the grader's (`--api-key-env` naming a secret) →
  Mitigation: `eval` refuses it before a run directory exists.
- [Risk] A verifier writes the secret into the workdir, which a rubric judge is shown →
  Mitigation: everything sent to the judge, and its stored answer, is redacted; the workdir is not
  copied or cleaned, and the docs say to fetch references outside it.
- [Risk] Redaction stops after 101 copies and a verbose scorer keeps the rest → Mitigation: every
  copy is replaced, in `redact.py` and its TypeScript port; only the reported count is capped.
- [Risk] A caller builds a backend without the suite's secrets → Mitigation: `run_suite` and
  `fill_run` add the suite's secrets to the backend's withheld names before preflight.

## Open Questions

None.
