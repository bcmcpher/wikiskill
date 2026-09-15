## 0. Minimal working core

The minimum is a routing-only evaluation on OpenCode for a single model:
- the suite format (1.1–1.2)
- the OpenCode backend with isolation and preflight (2.1–2.5)
- ROUTED and OFF conditions (3.1)
- route metrics and a markdown report (4.1, 4.4)

Deferred:
- INJECTED (3.2)
- command verifiers and fixtures (4.2)
- the rubric judge (4.3)
- the multi-model matrix statistics (4.5)

## 1. Task suites

- [ ] 1.1 `schemas/task-suite.schema.json` and `src/wikiskill/suite.py` loader/validator (unique ids,
  split values, `requires`, verifier kinds).
- [ ] 1.2 `wikiskill suite check <file>` flags any prompt that names an expected skill, plugin, or agent.
- [ ] 1.3 data-science-harness adapter reading `bench/tasks/*.yaml` and `bench/rubrics/*.yaml` in place.

## 2. Runner and OpenCode backend

- [ ] 2.1 `src/wikiskill/runner/base.py` backend interface; run ids; run directory layout.
- [ ] 2.2 `runner/opencode.py`:
  - isolated XDG root and fixture workdir
  - inline config with only the target provider
  - project and Claude Code discovery disabled
  - collection built and installed into the run's own config
- [ ] 2.3 `harness/opencode/guard/` plugin blocking the suite's denied command patterns via
  `tool.execute.before`.
- [ ] 2.4 Capture `opencode run --format json` and `opencode export` for the root and child sessions;
  normalise into raw events with `origin: eval`.
- [ ] 2.5 Preflight: reachability, model listing, tool-call probe, and context of at least 16k, with
  actionable failure messages.
- [ ] 2.6 Outcome classification including `tool_call_as_text`, `infra_error`, and `skipped` with reason.

## 3. Conditions, repeats, matrix

- [ ] 3.1 OFF and ROUTED; `repeats`; a model list from the manifest or `--models`.
- [ ] 3.2 INJECTED for skills (`instructions` plus a skill deny) and agents (`--agent`).
- [ ] 3.3 A per-endpoint worker limit (default 1), plus `timeout_s` and `max_steps` enforcement.

## 4. Scoring and reports

- [ ] 4.1 Route metrics `route@1`, `route@k`, `capability@k`, and the confusion matrix.
- [ ] 4.2 Verifiers `command`, `file_exists`, and `regex`, run in the workdir after the session.
- [ ] 4.3 Rubric judge on the judge role endpoint, blind to the expected route; 1 or 3 judges per rubric.
- [ ] 4.4 `report.json` and `report.md`: pass rate, tokens, time, outcome classes, unrun/skipped with
  reasons.
- [ ] 4.5 Derived routing loss, content value, transfer and regression rates; exact McNemar across
  models, reported only.
- [ ] 4.6 `harness/source/commands/wikiskill-eval.md` launching `wikiskill eval` in the background.

## 5. Verify

- [ ] 5.1 `uv run pytest tests/test_suite.py tests/test_score.py`: schema validation, route metrics, and
  outcome classification on recorded trajectories.
- [ ] 5.2 `uv run pytest tests/test_runner_opencode.py`: the normaliser over recorded
  `run --format json` and `export` fixtures, including a child session.
- [ ] 5.3 Isolation check: `run.json` shows no MCP servers, no project config, and no skills beyond
  the collection's.
- [ ] 5.4 Smoke test: a 3-task toy suite, OFF and ROUTED, one small local model. Each run should end
  with a report and no `infra_error`, or with the preflight's failure message. Record whichever
  happened.
- [ ] 5.5 `openspec validate add-explicit-eval --strict --no-interactive`.
