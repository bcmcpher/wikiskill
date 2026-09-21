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
  - **Amended 2026-09-21, after reading a real suite.** The check refused six of the 42 tasks in
    data-science-harness's routing suite. Five were the word "project" meaning the study, colliding
    with its `project/` plugin; one asked for a "reporting checklist", which is what a journal calls
    the artefact and what `disseminate/reporting-checklist` is named after. Neither hands over a
    route, and a check that fires on "this project" is one people switch off.
  - The qualified slug stays an error — nobody writes `disseminate/reporting-checklist` in a prompt
    by accident. A bare half is now a warning that `suite check` prints and a reader judges, and
    `Suite.warnings` carries them.
- [x] 1.3 data-science-harness adapter reading `bench/tasks/*.yaml` and `bench/rubrics/*.yaml` in place.
  - DSH's `bench/README.md` sets the terms: read in place, write nothing, and *"do not add fields to
    these fixtures to suit a consumer... a runner that needs something these files do not declare
    supplies it on its own side."* So `adapters/dsh.py` translates rather than negotiates.
  - `suite.load` recognises a DSH document by the two things it has and a wikiskill suite does not —
    a `probe`, and tasks stating `expected_skill` — and translates before the ordinary validation.
    DSH's fixtures are then held to exactly the same checks as a hand-written suite.
  - The two things wikiskill supplies on its own side: the **split**, which DSH does not declare
    (`--split`, default `val`), and the **agent behind a plugin**, since `expected_delegates_to`
    names plugins. Resolved from the collection's own components where there is one — the same
    repository DSH derives its ground truth from — and otherwise by DSH's `<plugin>-doer`
    convention, recorded as the assumption it is.
  - Rubrics need no adapter at all: `bench/rubrics/*.yaml` is already the shape `rubric.py` reads.
  - **Verified on the real fixture, 2026-09-21.** `bench/tasks/routing-lifecycle.yaml` loads in
    place: 42 tasks, every one judged, agents resolved, and a test asserts the files' mtimes are
    unchanged by reading them.

## 2. Runner and OpenCode backend

- [x] 2.1 `src/wikiskill/runner/base.py` backend interface; run ids; run directory layout.
- [x] 2.2 `runner/opencode.py`:
  - isolated XDG root and fixture workdir
  - inline config with only the target provider
  - project and Claude Code discovery disabled
  - collection built and installed into the run's own config
- [x] 2.3 `harness/opencode/guard/` plugin blocking the suite's denied command patterns via
  `tool.execute.before`.
  - **Amended 2026-09-21. The guard had never run.** OpenCode calls *every* export of a plugin
    module as a plugin factory, so `export class GuardBlocked` made the whole file fail to load:
    `failed to load plugin ... error="Cannot call a class constructor GuardBlocked without |new|"`.
    That is one ERROR line in a log nobody reads, after which the run continues unguarded. Proved
    live on 2026-09-21: a task prompting `curl https://example.com` — a `BASE_DENY` pattern — ran
    the command and fetched the page. The plugin's unit tests all passed throughout; they tested
    pure functions, never the contract with the loader.
  - Fixed by moving every name into `harness/opencode/guard/wikiskill/guard.ts` and leaving the
    plugin file exporting the factory and nothing else, mirroring the logger's layout.
    `test/guard.test.ts` now calls every export of the plugin module as a factory, which is the
    assertion that would have caught it.
- [x] 2.4 Capture `opencode run --format json` and `opencode export` for the root and child sessions;
  normalise into raw events with `origin: eval`.
  - **Amended 2026-09-21. Every session over 64 KiB was being thrown away.** `opencode export` exits
    without draining a pipe, so `capture_output=True` returned exactly 65536 bytes of a 230 KB
    session — unparseable, and the parse failure was swallowed, leaving an empty session list. The
    unit then scored `completed` with no activations and no tokens: a routing miss that never
    happened. Only short sessions had ever been checked, which is why the fixtures all passed.
  - Exports now go to a file under the unit's `exports/` (the full 230 KB arrives that way, and the
    evidence stays on disk beside the run), and a failed or unreadable export raises rather than
    returning nothing, so the unit is `infra_error` instead of a silent zero.
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
- [x] 2.6 Outcome classification including `tool_call_as_text`, `infra_error`, and `skipped` with reason.
  - Six of the seven classes were already produced and tested; `step_exhausted` was in `OUTCOMES`
    and in the spec but unreachable, because nothing counted steps. It is reachable now (see 3.3),
    and is checked *before* `permission_blocked`, which its message also matches: the guard is what
    throws, but running out of steps is something the model did.
  - Recorded from a real run rather than fabricated:
    `tests/fixtures/opencode/{run,session}-step-exhausted.*` is a one-step budget against a task
    needing three writes.

## 3. Conditions, repeats, matrix

- [x] 3.1 OFF and ROUTED; `repeats`; a model list from the manifest or `--models`.
- [x] 3.2 INJECTED for skills (`instructions` plus a skill deny) and agents (`--agent`).
  - A skill task installs the collection as ROUTED does, then points OpenCode's `instructions` at
    the built `SKILL.md` and sets `permission.skill.<name>: deny`. The neighbourhood has to be the
    same in both conditions or the difference measures the neighbourhood, not the routing.
  - An agent task needs none of that: `--agent <name>` bypasses delegation directly.
  - A task that names no component is skipped under INJECTED with that reason. There is nothing to
    force into context, and its number would be a second OFF wearing a label.
  - **Verified live on 2026-09-21.** `permission.skill` is honoured: under INJECTED the model
    reached for the skill and OpenCode refused it — *"The user has specified a rule which prevents
    you from using this specific tool call"* — while the same call completed under ROUTED. The
    refusal is recorded at `tests/fixtures/opencode/session-skill-denied.json` (trimmed to the
    messages holding the skill call).
- [x] 3.3 A per-endpoint worker limit (default 1), plus `timeout_s` and `max_steps` enforcement.
  - `max_steps`: `opencode run` has no step limit of its own, so the guard counts tool calls and
    refuses the one past the budget (`WIKISKILL_MAX_STEPS`). Counted before the deny check, so a
    model cannot buy steps by making calls it knows will be refused. Verified live on 2026-09-21:
    `max_steps: 1` against a three-file task ended `step_exhausted` with the budget's own message,
    and its `file_exists` verifier failed because the third file was never written.
  - `timeout_s` was already enforced as the `subprocess` timeout and classified `infra_error`, which
    is what the design asks for — a timeout is not a verdict about the model.
  - `--workers N` (default 1) applies *inside* a model, not across the run: every unit of one model
    shares one endpoint, and models still run one after another so an endpoint holding one model in
    memory is never asked to hold two. Results keep submission order however the lanes finish, and
    `run.json` records the lane count, since it changes what a wall time means.

## 4. Scoring and reports

- [x] 4.1 Route metrics `route@1`, `route@k`, `capability@k`, and the confusion matrix.
  - **Amended 2026-09-21, found while verifying 3.2.** A tool call the harness refused was counted
    as an activation, so INJECTED — where the expected skill is denied by construction — scored a
    perfect `route@1` for a route it had just made impossible. A refused call is now recorded with
    `blocked: true` and excluded from the route metrics: the model reached for the component, and
    did not reach it. OFF and ROUTED are unchanged, since nothing is refused there.
- [x] 4.2 Verifiers `command`, `file_exists`, and `regex`, run in the workdir after the session.
  - `score/verify.py` holds the three kinds, harness-agnostic: it is given a workdir, the final
    text and the transcript, never a backend. `negate` inverts any kind. A `regex` on a file that
    was never written is a fail, not a crash.
  - The line that matters is between a check that *fails* and one that cannot be *carried out*. A
    command exiting 1 when 0 was expected is a verdict about the model; a command that times out,
    or a workdir that is gone, raises `VerifierError` and the unit is recorded `infra_error` and
    excluded from scores. Verifiers run only on a unit that actually ran.
  - `results.jsonl` gains `verifiers` and `passed` (`None` when a task declares none, so "nothing
    checked" never reads as "everything passed"). `report.py` is now verifier-first: a task with
    verifiers takes its pass rate from them and reports routing as a separate dimension, and every
    row's `pass_basis` says `verifier`, `route`, or `not measured`. `report.md` names which check
    failed.
  - The loader now rejects at read time what the schema only describes: an absolute or `..` path, a
    pattern that does not compile, and `target: file` with no `path`.
  - **Verified end to end on 2026-09-21** against `opencode/big-pickle`, the endpoint that passes
    preflight. `unrelated-control` — the toy suite's verifier-only task — moved from
    `pass_basis: "not measured"` to `"verifier"` with a real failure under both OFF and ROUTED:
    `/count/ not found in the final text`, outcome `completed`, so a failed check reads as a failed
    task rather than a broken harness. A second report carried both bases side by side:
    `inspect-history` at `pass_basis: "route"` (route@1 0%) next to `unrelated-control` at
    `"verifier"`. This is Milestone A's first pass/fail number.
- [x] 4.3 Rubric judge on the judge role endpoint, blind to the expected route; 1 or 3 judges per rubric.
  - `rubric.py` loads the format data-science-harness already writes: dimensions with named anchors,
    `type: binary` where a dimension has two states, and an optional `judges: 3`. Anchor order *is*
    the scale, so nothing assumes `none`/`partial`/`complete`.
  - `score/judge.py` enforces the three rules rather than documenting them. Blind: the prompt
    carries the rubric, the artifacts and the final answer, and never the expected route — there is
    a test that reads the sent payload and looks for it. Not a model under test: refused before the
    first unit runs, not after the matrix has been graded by a model grading itself. Its own
    endpoint, from `roles.judge`.
  - A judge never touches `passed`. It runs after the verifiers, its dimensions are counted rather
    than averaged (the mean of `partial` and `complete` is not a thing), and a judge that cannot be
    reached is an absent opinion, not a failed unit.
  - Three judges settle by majority; a tie between two levels goes to the worse one, because the
    benefit of the doubt is not the judge's to give, and a genuine three-way split is reported as
    `split` rather than averaged away. The settled level keeps the winning judge's own words.
  - **Verified live on 2026-09-21** with `gemma2:2b` on local Ollama grading a `big-pickle` run —
    a judge that is not a model under test, and one that does not need tool calling, which is why
    a local model that fails preflight can still serve. Both dimensions scored with real reasons
    (*"The notes explicitly name specific files and folders, including `.git/`..."*), beside a
    verifier verdict the judge could not touch.
- [x] 4.4 `report.json` and `report.md`: pass rate, tokens, time, outcome classes, unrun/skipped with
  reasons.
- [x] 4.5 Derived routing loss, content value, transfer and regression rates; exact McNemar across
  models, reported only.
  - `score/derive.py`. Routing loss and content value are per model, because both are facts about
    one model reading one description. Transfer and regression ask the same question per task
    rather than on average, since a suite whose mean is flat can still be churning underneath.
  - A pair whose two halves rest on different bases is dropped rather than subtracted: a verifier
    pass rate minus a routing one is a number with no meaning. Every measure reports how many tasks
    it rests on, and a run missing a condition says which rather than reporting zero.
  - Exact McNemar on the paired per-task outcomes, two-sided from the binomial tail over the
    discordant pairs. Reported, never used to gate — on a suite of a dozen tasks it will usually
    say the difference could be a coin flip, and saying so is the point.
- [x] 4.6 `harness/source/commands/wikiskill-eval.md` launching `wikiskill eval` in the background.
  - The command's first instruction is that it must never run the suite in the calling session,
    which is the `eval-runner` spec's "Launch from inside OpenCode" scenario: an evaluation run from
    here would put this conversation's context, skills and MCP servers into the thing being
    measured.
  - It checks the suite, costs the run with `--preflight-only` first (on a harness-served model the
    probe itself spends tokens), starts the real run detached with its output in a file, reports the
    run id and where the report will be, and stops. It does not poll.
  - `tests/test_build.py` asserts those three things survive the build, whitespace-normalised so the
    assertion does not depend on where a line wrapped.

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
- **Noted 2026-09-21, not yet acted on.** Roughly half the runs against `opencode/big-pickle` that
  day failed preflight with `the probe did not finish within 300s`, then passed on an immediate
  retry — the free tier queues. `PROBE_TIMEOUT_S` is one number and the probe has no retry, so an
  otherwise healthy model is refused on a coin flip. Worth a retry or a longer budget before any
  long matrix run.
