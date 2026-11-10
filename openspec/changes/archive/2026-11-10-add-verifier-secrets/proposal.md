## Why

A verifier may need a credential the agent must not have, such as a token that fetches a hidden
reference answer. Today the OpenCode session inherits the whole host environment
(`runner/opencode.py:587`) and Claude Code strips only its own prefixes (`runner/claude.py:72`), so
any such variable on the host reaches the model under test. A suite has no way to say "this is for
the grader only".

## What Changes

- A suite may declare `secrets`: names of host environment variables that only command verifiers
  receive. Declared in `defaults`, on a task, or both; the two lists are joined.
- Both runners remove every secret the suite declares from every harness process of every unit:
  the session, and OpenCode's export step. Setup commands and the `requires` check do not get them
  either. A verifier gets only its own task's secrets.
- A run whose declared secret is not set on the host, too short, or padded with whitespace refuses
  to start and names the variable.
- `run.json` records the secret names, never their values. Values are redacted from records and
  from the harness's raw files in the unit directory.
- No task `env` entry may name or expand a declared secret.
- The docs state that this is not a sandbox: a session running as the same user can still read the
  value from the host.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `task-suite`: a new requirement for declaring verifier-only secrets.
- `eval-runner`: a new requirement that secrets are withheld from sessions and kept out of records.

## Impact

- `schemas/task-suite.schema.json` and `src/wikiskill/suite.py`: the `secrets` field and its checks.
- `src/wikiskill/runner/opencode.py`, `runner/claude.py`, `runner/common.py`: one shared rule that
  removes secrets from each environment they build.
- `src/wikiskill/score/verify.py`: a command verifier gets the secrets; its stored output is
  redacted using `src/wikiskill/redact.py`.
- `src/wikiskill/runner/run.py`: the start-of-run check and the names in `run.json`.
- Docs: `docs/evaluate-and-refine-a-skill.md` §3 and `docs/writing-suites.md`.
- The suite hash covers the names, as they are in the suite file. A suite without `secrets` keeps its
  hash and its behaviour.
- No dependency on other open changes. `add-scored-verifier` is independent; together they cover a
  grader that fetches a hidden reference.
