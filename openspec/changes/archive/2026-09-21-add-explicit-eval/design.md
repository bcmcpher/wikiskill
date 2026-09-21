## Context

WikiSkill injects every active skill's full text into the system prompt, deliberately removing
retrieval and triggering from what it measures. In OpenCode and Claude Code, triggering is part of
what a skill is: a skill the model never loads contributes nothing. So wikiskill measures both, and
separates them.

OpenCode (1.18.31 or newer) runs headless with `opencode run --format json`, emitting completed tool
parts, step-finish parts with tokens, and errors. `opencode export <sessionID>` returns full
sessions, including child sessions created by the `task` tool. In `run`, any permission set to `ask`
is rejected automatically. Configuration can be supplied inline (`OPENCODE_CONFIG_CONTENT`), project
config disabled (`OPENCODE_DISABLE_PROJECT_CONFIG`), and Claude Code skill discovery disabled
(`OPENCODE_DISABLE_CLAUDE_CODE`). There is no switch to ignore global config, so each run gets its
own XDG directories.

Local open models fail in characteristic ways:
- a context window too small for OpenCode's system prompt and tool schemas
- tool calls emitted as text
- calls that silently do nothing

These must be classified, not scored as wrong answers.

## Goals / Non-Goals

**Goals:**
- Controlled, repeatable comparison of the same components across models and conditions.
- Decompose performance into routing loss and content value.
- Never let a broken endpoint or harness masquerade as a bad skill.

**Non-Goals:**
- **Claude Code backend** — `add-claude-code-adapter` plugs into the interface defined here.
- **Multi-turn simulated users** (as in arXiv 2608.10319) — tasks are single prompt plus optional scripted
  follow-ups.
- **Significance-gated decisions** — statistics are reported, not used to gate.
- **The `opencode serve` API** — `run` plus `export` is enough for v1 (see Open Questions).

## Decisions

**Task format.**

```yaml
suite: dsh-routing
defaults: { repeats: 3, timeout_s: 900, max_steps: 40 }
tasks:
  - id: disseminate-release
    prompt: Cut version 1.0 of the dataset so the paper can cite a fixed version of it.
    split: val                      # train | val | test
    expect: { skill: disseminate/dataset-release, agents: [datalad-doer, archive-doer] }
    verifiers:
      - { kind: command, run: "python3 schemas/validate-ledger.py project.yaml", expect_exit: 0 }
      - { kind: file_exists, path: CHANGELOG.md }
      - { kind: regex, target: final_text, pattern: "v1\\.0" }
    rubric: rubrics/provenance-completeness.yaml
    fixtures: fixtures/minimal-study
    requires: [datalad]
    guard: { deny: ["git push*", "datalad push*"] }
    followups: []                   # optional scripted user turns
```

Suites validate against `schemas/task-suite.schema.json`. The data-science-harness adapter maps
`bench/tasks/*.yaml` (`expected_skill`, `expected_delegates_to`) and `bench/rubrics/*.yaml` into this
shape without copying them.

**Backend interface.** `version()`, `preflight(model)`, `prepare(run)`, `execute(run) -> Trajectory`,
`normalize(trajectory) -> [raw events]`.

**OpenCode isolation per run.**
- A temp root with `XDG_CONFIG_HOME`, `XDG_DATA_HOME`, `XDG_STATE_HOME`.
- A workdir copied from fixtures and `git init`-ed.
- `OPENCODE_CONFIG_CONTENT` carrying:
  - only the target provider block
  - `autoupdate: false`, `share: disabled`, no MCP servers
  - the guard plugin
- `OPENCODE_DISABLE_PROJECT_CONFIG=true` and `OPENCODE_DISABLE_CLAUDE_CODE=1`.
- The collection, when present, is built with the manifest's alias table and installed into the run's
  own XDG config — never the user's.
- Permissions: edits allowed inside the workdir only, `external_directory` denied, web denied, bash
  denied except the suite's allowlist.
- `opencode debug config` is captured into the run manifest to prove what was loaded.

**Conditions.**
- **OFF:** no collection installed.
- **ROUTED:** collection installed; normal discovery.
- **INJECTED:** for a skill, its `SKILL.md` goes into `instructions` and `permission.skill.<name>` is
  `deny`, so the text is present but cannot also be loaded. For an agent, the run uses
  `opencode run --agent <name>`, bypassing delegation.

Derived per task and model:
- routing loss = INJECTED − ROUTED
- content value = INJECTED − OFF

**Trajectory capture.** `opencode run --format json --dir <workdir> -m <provider/model> [--agent]`,
then `opencode export` for the root session and every child session id found in `task` tool metadata.
The result is normalised into raw events with `origin: eval`, the run id, task id, condition, and
repeat index.

**Preflight** runs once per model per suite run. It checks that:
- the endpoint is reachable and the model is listed
- a tool-call probe (one trivial tool schema) returns a structured tool call
- the context window is at least 16k, from the manifest `limit` or Ollama `/api/show`

A failed check aborts that model with an actionable message, for example to set
`OLLAMA_CONTEXT_LENGTH`.

**Outcome classes.**
- `completed`
- `tool_call_as_text`: assistant text containing tool-call-shaped JSON/XML with no tool part
- `step_exhausted`
- `permission_blocked`: guard or permission denial — scored as behaviour
- `api_error`
- `infra_error`: crash, timeout, fixture failure — excluded from scores, counted separately
- `skipped`: `requires` unmet, with reason

**Scoring order.**
1. Route metrics from activation events: `route@1` (first activated skill equals expected on a run),
   `route@k` (expected reached in any of k repeats), `capability@k` (fraction of expected agents
   reached).
2. Verifiers in the workdir after the session.
3. Rubric judge last, using the judge role's endpoint. It sees artifacts and final text, never the
   expected route. The manifest rule makes the judge differ from every target model. One judge by
   default; three when the rubric requires it.

**Metrics and report.** Per task × model × condition:
- pass rate over repeats, tokens, wall time, outcome-class counts

Per suite:
- routing loss and content value
- transfer rate (fails OFF → passes ROUTED)
- regression rate (passes OFF → fails ROUTED)
- a routing confusion matrix
- paired model comparisons: exact McNemar on per-task majority outcome, reported only

Output goes to `<collection>/evals/<run-id>/`: `run.json` (wikiskill, harness, and component
`source_hash` versions, model ids, base URLs without keys, temperatures), `results.jsonl`,
`report.json`, and `report.md`. Unrun and skipped items are listed with reasons.

**Launch.** `/wikiskill-eval <suite> [--models ...]` starts `wikiskill eval` in the background and
returns the run id. Evaluation never happens in the calling session. Workers per endpoint default to
one, because Ollama serves one request at a time by default.

## Risks / Trade-offs

- [Local CPU inference makes suites take hours] → small suites first; per-run `timeout_s` and
  `max_steps`; the preflight states the expected cost; point models at a remote endpoint.
- [Nondeterminism] → repeats; temperature pinned where the provider honours it; report spread.
- [OpenCode JSON output changes between versions] → normaliser contract tests on recorded fixtures;
  `harness_version` in the run manifest.
- [Global config leaks into runs] → isolated XDG dirs and captured `opencode debug config` in every
  run manifest.
- [Judge bias] → verifiers first; judge never a target model; judge blind to the expected route.
- [INJECTED is not identical to loading via the skill tool] → documented as an approximation; the
  routing-loss figure is read as indicative.

## Open Questions

- Move to `opencode serve` plus SSE for pending states, permission events, and per-prompt system
  injection?
- Should scripted `followups` grow into a simulated user conditioned on logged corrections?
