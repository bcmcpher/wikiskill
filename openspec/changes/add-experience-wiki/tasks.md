## 0. Minimal working core

Sampling and digests (1.1–1.3), the contract and validator (2.1–2.3), the wiki layout with
apply-and-commit (3.1–3.3), and headless review (4.2). Deferred: the in-harness command (4.1) until
the headless path produces sensible patterns on real logs.

## 1. Sampling and digests

- [ ] 1.1 `src/wikiskill/sample.py`: select sessions since the watermark by signal priority, up to the
  configured counts.
- [ ] 1.2 `src/wikiskill/digest.py`: render a session into a digest within the per-digest budget
  derived from the maintainer model's context.
- [ ] 1.3 `wikiskill sample --collection <c> [--component X] [--resample]` writes digests to a run
  directory and prints their ids.

## 2. Maintainer contract

- [ ] 2.1 `schemas/maintainer-output.schema.json`.
- [ ] 2.2 `src/wikiskill/maintain.py` validator: slug, anchor-uniqueness, evidence, universal-scope, and
  enum checks, each with an actionable message.
- [ ] 2.3 Retry loop: re-prompt with errors, at most two retries, then record the failure and stop.

## 3. Wiki

- [ ] 3.1 `src/wikiskill/wiki.py`: initialise the layout as a git repo; apply creates, patches, index, and
  log.
- [ ] 3.2 Watermark update only after a successful apply and commit.
- [ ] 3.3 `components/<name>.md` created on a component's first pattern.

## 4. Maintainer agent and command

- [ ] 4.1 `harness/source/agents/wikiskill-maintainer.md` (read-only digest access) and
  `harness/source/commands/wikiskill-review.md`; build for OpenCode.
- [ ] 4.2 `wikiskill review --headless` runs the agent via `opencode run --agent` with the maintainer
  role's model, then validates and applies.

## 5. Verify

- [ ] 5.1 `uv run pytest tests/test_maintain.py`: validator accepts a good fixture and rejects a
  duplicate anchor, an unknown evidence id, and `universal` with single-model evidence.
- [ ] 5.2 `uv run pytest tests/test_wiki.py`: apply, commit, and watermark behaviour, plus
  exhausted-retries leaving the wiki unchanged.
- [ ] 5.3 End-to-end on recorded fixtures: `wikiskill review --headless` with a stub maintainer that
  replays a fixed JSON response. `git -C <wiki> log` shows one commit, and the index lists the new
  pattern.
- [ ] 5.4 Live run against a real endpoint on logs from `add-trace-logging`. If none is reachable, record it as
  unrun with the reason.
- [ ] 5.5 `openspec validate add-experience-wiki --strict --no-interactive`.
