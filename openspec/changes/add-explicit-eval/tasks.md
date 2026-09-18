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

- [x] 1.1 `schemas/task-suite.schema.json` and `src/wikiskill/suite.py` loader/validator (unique ids,
  split values, `requires`, verifier kinds).
- [x] 1.2 `wikiskill suite check <file>` flags any prompt that names an expected skill, plugin, or agent.
- [ ] 1.3 data-science-harness adapter reading `bench/tasks/*.yaml` and `bench/rubrics/*.yaml` in place.

## 2. Runner and OpenCode backend

- [x] 2.1 `src/wikiskill/runner/base.py` backend interface; run ids; run directory layout.
- [x] 2.2 `runner/opencode.py`:
  - isolated XDG root and fixture workdir
  - inline config with only the target provider
  - project and Claude Code discovery disabled
  - collection built and installed into the run's own config
- [x] 2.3 `harness/opencode/guard/` plugin blocking the suite's denied command patterns via
  `tool.execute.before`.
- [x] 2.4 Capture `opencode run --format json` and `opencode export` for the root and child sessions;
  normalise into raw events with `origin: eval`.
- [x] 2.5 Preflight: reachability, model listing, tool-call probe, and context of at least 16k, with
  actionable failure messages.
  - **Amended 2026-09-18.** The probe now takes the path a unit takes. A direct HTTP probe is right
    only when wikiskill addresses the endpoint itself; when the harness holds the credential it is
    wrong twice over — OpenCode's free tier answers a direct POST with
    `FreeTierError: OpenCode's free tier can only be used from within OpenCode`, so the gate would
    refuse a model the runner can drive, and it tests a path no unit uses. `--base-url` is now
    opt-in: without it `OpenCodeBackend.harness_preflight` lists models with `opencode models`,
    probes with `opencode run` in its own isolated root, and reads the context from the models.dev
    catalog that run fetched. Verified both ways on 2026-09-18: `opencode/big-pickle` passes
    (`probe_tools: ['write']`, 200000-token context, exit 0) and `ollama/qwen2.5-coder:1.5b` still
    fails on both its original counts. Added `--preflight-only`, since on a harness-served model the
    check itself costs tokens and the answer decides whether a suite is worth starting.
- [ ] 2.6 Outcome classification including `tool_call_as_text`, `infra_error`, and `skipped` with reason.

## 3. Conditions, repeats, matrix

- [x] 3.1 OFF and ROUTED; `repeats`; a model list from the manifest or `--models`.
- [ ] 3.2 INJECTED for skills (`instructions` plus a skill deny) and agents (`--agent`).
- [ ] 3.3 A per-endpoint worker limit (default 1), plus `timeout_s` and `max_steps` enforcement.

## 4. Scoring and reports

- [x] 4.1 Route metrics `route@1`, `route@k`, `capability@k`, and the confusion matrix.
- [ ] 4.2 Verifiers `command`, `file_exists`, and `regex`, run in the workdir after the session.
- [ ] 4.3 Rubric judge on the judge role endpoint, blind to the expected route; 1 or 3 judges per rubric.
- [x] 4.4 `report.json` and `report.md`: pass rate, tokens, time, outcome classes, unrun/skipped with
  reasons.
- [ ] 4.5 Derived routing loss, content value, transfer and regression rates; exact McNemar across
  models, reported only.
- [ ] 4.6 `harness/source/commands/wikiskill-eval.md` launching `wikiskill eval` in the background.

## 5. Verify

- [x] 5.1 `uv run pytest tests/test_suite.py tests/test_score.py`: schema validation, route metrics, and
  outcome classification on recorded trajectories.
- [x] 5.2 `uv run pytest tests/test_runner_opencode.py`: the normaliser over recorded
  `run --format json` and `export` fixtures, including a child session.
- [x] 5.3 Isolation check: `run.json` shows no MCP servers, no project config, and no skills beyond
  the collection's.
  - Recorded 2026-09-18 from a real run: `isolation.off.mcp` and `isolation.routed.mcp` are both
    `{}`; the only provider is the target's; the only plugin is the evaluation guard. Skills are
    `[customize-opencode]` under OFF and `[customize-opencode, wikiskill-trace]` under ROUTED —
    `customize-opencode` is OpenCode's own built-in, so nothing of the user's reached the run.
- [x] 5.4 Smoke test: a 3-task toy suite, OFF and ROUTED, one small local model. Each run should end
  with a report and no `infra_error`, or with the preflight's failure message. Record whichever
  happened.
  - **What happened, 2026-09-18:** the preflight failure message, as expected on this CPU-only
    machine. `examples/suites/toy-routing.yaml` on `ollama/qwen2.5-coder:1.5b` under OFF and ROUTED:
    preflight refused the model on two counts — it answers the tool-call probe with text rather than
    a structured call, and Ollama serves it with the default 4096-token context against the 16k
    minimum. All 6 units were `skipped` with that reason, `report.md` listed all 7 not-run entries
    (6 units plus the model), no `infra_error` occurred, and `wikiskill eval` exited 1 because
    nothing was scored. Isolation was still captured for both conditions (see 5.3).
- [x] 5.5 `openspec validate add-explicit-eval --strict --no-interactive`.
