# wikiskill architecture

Status: design, 2026-09-15. Nothing described here is implemented yet; implementation is sequenced as
OpenSpec changes under [`openspec/changes/`](../../openspec/changes/).

Background: [paper and implementations](../research/wikiskill-paper-and-implementations.md),
[related work](../research/related-work.md).

## 1. What this is

An **in-harness** package — used from inside the agent harness, like skill-creator — that points at a
collection of skills and subagents and:

1. **records** what each component does with a given model, and what the user had to correct;
2. **distils** those records into a persistent wiki of patterns;
3. **refines** components through gated, reviewable proposals;
4. **compares** the same components across models and harnesses.

Targets:

- **Primary:** OpenCode, driven by open models behind any OpenAI-compatible endpoint (Ollama,
  llama.cpp, vLLM, LM Studio, hosted open-model APIs).
- **Secondary:** Claude Code, where most development happens — with local models via an
  Anthropic-compatible endpoint, or Anthropic models as a frontier baseline.
- **First collection:** `data-science-harness` (DSH), which already installs into both harnesses.

## 2. Mapping the paper onto a harness

| WikiSkill layer | Paper component | wikiskill component |
|---|---|---|
| Raw | Inference Agent traces from benchmark runs | **Logger**: OpenCode plugin / Claude Code hooks recording real sessions, plus eval runs, into a harness-neutral JSONL log |
| Raw (new) | — | **Correction signal**: follow-up user turns, later edits to agent output, explicit `/wikiskill-note` |
| Wiki | Wiki Maintainer (one call, JSON contract) | **Maintainer agent** + `/wikiskill-review` |
| Skills | Skill Proposer (ReAct, `read_file` + `finish`) | **Proposer agent** + `/wikiskill-refine <component>` |
| Gate | Strict `>` on validation, skills-only rollback | **Refinement gate**: human approval + replay + no-regression, recorded in `skill-impact.md` |
| Evaluation | Fixed benchmarks, full injection | **Explicit eval**: task suites in fresh headless sessions under OFF / ROUTED / INJECTED conditions |

What is kept from the paper: three layers; wiki never rolled back; atomic proposals; `PURPOSE.md`
alongside `SKILL.md`; the executing agent never reads the wiki; trace sampling with caps; enforced
evidence reading; `skill-impact.md` including rejected content.

What changes, and why:

- **Triggering is part of what is evaluated.** The paper injects every skill to remove retrieval as a
  confound. In a harness, whether the right skill or subagent is *chosen* is half the behaviour. Both
  are measured, separately (§4).
- **Real use is a data source.** The paper only learns from benchmark traces. Here, ordinary sessions
  and user corrections feed the same raw log.
- **The gate is stricter** (§7).

## 3. Two modes over one log

```
          real sessions ─┐                         ┌─ /wikiskill-review ─► wiki/
 (logger + corrections)  ├─► raw/ (JSONL, per ─────┤
                         │   collection)           └─ /wikiskill-refine ─► proposal ─► gate ─► skill source
   explicit eval runs ───┘
 (fresh headless sessions)
```

**Passive mode.** The logger records sessions that touch a watched component. Corrections are
captured automatically and via `/wikiskill-note`. Periodically the user runs `/wikiskill-review`
(maintainer) and `/wikiskill-refine <component>` (proposer). No task suite is required; the gate
relies on human approval plus replay of logged cases once the runner exists.

**Explicit mode.** `/wikiskill-eval` runs a task suite. Runs happen in **fresh headless sessions**
spawned from a script (as skill-creator spawns `claude -p`), never in the calling session, to avoid
contaminating results with the evaluator's context. Results are written into the same raw log with
`origin: eval`.

## 4. Evaluation conditions

Every explicit task can run under three conditions:

| Condition | Setup | Measures |
|---|---|---|
| **OFF** | Collection absent | Baseline — the paper's empty skill set; DSH's required control |
| **ROUTED** | Collection installed normally | End-to-end: trigger → delegation → outcome |
| **INJECTED** | Component text forced into the system prompt; component denied as a tool | Content quality alone, as in the paper |

- `INJECTED − OFF` isolates the value of a component's content.
- `ROUTED − INJECTED` isolates routing loss (wrong or missing trigger/delegation).

Harness mechanics:

| | OpenCode | Claude Code |
|---|---|---|
| ROUTED | Normal discovery of `skills/` and `agents/` | `--plugin-dir <build>` |
| INJECTED | `instructions: [<component file>]` + `permission.skill.<name>: deny` | `--append-system-prompt` + disallow the Skill |
| Trace capture | `opencode run --format json`, then `opencode export` for root and child sessions | `claude -p --output-format stream-json` |
| Skill load signal | tool part with `tool == "skill"` | `Skill` tool_use |
| Delegation signal | `task` tool part; child `sessionId` in metadata | `Agent` tool_use `subagent_type` |

## 5. Components

### 5.1 Harness-neutral core (Python, uv)

- raw-log schema (versioned) and validation;
- collection manifest loading;
- trace sampling and capping;
- maintainer/proposer contract validation, with bounded retries for weak models;
- eval runner orchestration, verifiers, statistics, reports.

### 5.2 Harness adapters (thin)

| Concern | OpenCode (primary) | Claude Code (secondary) |
|---|---|---|
| Logger | TS plugin: `event`, `tool.execute.after` | `hooks.json`: `PostToolUse`, `UserPromptSubmit`, `Stop`, `SubagentStop` → Python script by explicit path |
| Follow-up turns | `chat.message` / message events | `UserPromptSubmit` |
| Post-output edits | session snapshot / diff | git diff of files the agent touched |
| Mutation guard (eval) | plugin `tool.execute.before` throws; permission deny rules | `PreToolUse` hook; `--disallowedTools` |
| Eval backend | `opencode run` in isolated XDG dirs + `OPENCODE_CONFIG_CONTENT`, `OPENCODE_DISABLE_PROJECT_CONFIG` | `claude -p --setting-sources project --strict-mcp-config --permission-mode dontAsk --max-budget-usd` |

Both loggers are **fail-open**: a logging error never interrupts the session, and logging makes no
model calls.

OpenCode isolation note: there is no switch to ignore global config in 1.18.x, so each eval run gets
its own temporary `XDG_CONFIG_HOME`, `XDG_DATA_HOME` and `XDG_STATE_HOME`. In `opencode run`,
permissions set to `ask` are auto-rejected, so eval profiles are deny-by-default with explicit allows.

### 5.3 Single-source packaging

Skills, commands and the meta-agents (maintainer, proposer, judge) are authored once. A build step
emits:

- **OpenCode layout**: `skills/`, `agents/` (`mode: subagent`, `permission:` blocks), `commands/`,
  `plugins/`;
- **Claude Code plugin**: `.claude-plugin/plugin.json`, `skills/`, `agents/` (`tools:` lists),
  `commands/`, `hooks/hooks.json`;
- **per-harness model alias tables** — the pattern DSH `bin/install.sh` already uses, extended to
  open-model providers.

The same build step can package a *target* collection (e.g. DSH) for either harness.

## 6. Data

### 6.1 Storage

```
${XDG_DATA_HOME:-~/.local/share}/wikiskill/<collection>/
  raw/            # JSONL, append-only, per day or per session
  wiki/           # git repo; never rolled back
    index.md
    log.md
    skill-impact.md
    patterns/<id>.md
  runs/           # eval run artefacts (exports, reports)
```

The wiki lives per collection, outside both the working project and the skill source repo, so lessons
accumulate across every project that uses the same skills.

### 6.2 Collection manifest

- name and source directories (OpenCode layout or Claude-plugin layout);
- **watch list** of skills/agents — only sessions touching these are logged (opt-in);
- per-role model endpoints (§8);
- per-harness model alias tables.

### 6.3 Raw event (sketch)

Every event carries `schema_version`, `origin` (`session` | `eval`), `harness`, `provider`, `model`,
`session_id`, `parent_session_id`, `component` (if attributable), `kind` (skill-load, delegation,
tool-call, step, user-turn, file-edit, note, error), timestamps, token and cost fields, and a
redacted payload. For eval runs: `task_id`, `condition`, `repeat`, `outcome`.

### 6.4 Wiki pattern page

Paper fields (problem, root cause, fix, workaround) plus:

- `trigger` — the situation in which the pattern arises;
- `evidence` — trace IDs with step indices;
- `scope_hint` — including **model/harness scope**: universal, or specific to a model family/harness;
- `cause` — `routing-miss` | `inter-skill` | `skill-environment` | `skill-task` | `user-preference`;
- linked components.

## 7. Refinement and the gate

**Proposer contract.** One atomic `create | patch | no_action` against one component, submitted only
after the harness has recorded at least *N* distinct trace reads. Proposals must not contain evaluator
or answer vocabulary. Default to **pooled, general** edits; a model-specific variant needs repeated
evidence across sessions. Proposals are delivered as a patch or branch against the skill's source
repository — never silently applied in place.

**Gate.**

1. **Human approval** is always required.
2. When the eval runner is available: **replay** logged failing and corrected cases, and require **no
   regression** on a bank of previously good cases — including cases for the component's graph
   neighbours (conflict and co-usage edges).
3. Scores use *k* repeats; accept only if mean improves by at least `min_improvement`.
4. Paired statistics (McNemar / bootstrap) are reported, not used as the gate.
5. A held-out split is never shown to the proposer.
6. Every outcome — accepted or rejected, with full proposal content — goes to `skill-impact.md`.

**Why stricter than the paper's `>`.** The paper gates on validation sets of 10–40 tasks with a
strict `>`; with sampling nondeterminism, weak local models, and small sets, a single-run `>`
accepts noise. Replay and no-regression catch the failure mode that matters most for collections — an
edit that helps one component while breaking a neighbour.

**Description refinement** is collection-aware: a rewritten description must not take triggers from
conflict neighbours (checked against the routing confusion matrix).

## 8. Models

Every meta-role has its own endpoint and model in the manifest:

| Role | Default | Rule |
|---|---|---|
| Target (executing agent) | Model(s) under test | Any list of models |
| Judge | Open model | Must differ from the target model |
| Maintainer | Open model | Output validated against the JSON contract; bounded retries |
| Proposer | Open model | Enforced evidence reads |

## 9. Scoring

Priority order:

1. **Deterministic verifiers**: exact route/delegation match, file and command checks, domain
   validators (for DSH: `schemas/validate-ledger.py`, `tests/e2e-smoke.sh` assertions, bids-validator).
2. **Rubric judge** for dimensions without a verifier (e.g. DSH
   `bench/rubrics/provenance-completeness.yaml`).
3. **Cost**: tokens, wall-clock, tool calls.

Outcome classes are kept separate from scores: `completed`, `tool-call-as-text` (model emitted a tool
call as plain text — common with local models), `api-error`, `infra-failure`, `timeout`,
`step-exhausted`. Infrastructure failures never count as wrong answers.

Metrics: pass rate, route@1 / route@k, capability@k (partial credit over delegates), transfer and
regression rates with cause, tokens.

## 10. Comparison matrix

Explicit eval runs one suite across a list of models and, once the Claude Code adapter lands, both
harnesses. Reports are **component × model × harness × condition**, with paired comparisons and
**cross-model transfer**: a component refined from evidence on model X, evaluated on model Y. Wiki
scope tags let the report separate universal lessons from model-specific ones.

## 11. Compute caveat

The development laptop is CPU-only (i7-1185G7, 4 cores, 31 GB RAM, no discrete GPU), and its Ollama
service runs with a 4096-token context — too short for either harness's system prompt and tool
schemas. Consequences:

- the design is endpoint-agnostic; serious runs are expected on a remote GPU server or hosted
  open-model API;
- every eval begins with a **preflight** that checks the endpoint answers, the model emits structured
  tool calls, and the effective context is at least 16k tokens — failing fast with a stated reason;
- the laptop is suitable for smoke tests with small (2–4B) tool-calling models.

## 12. Roadmap (OpenSpec changes)

Order and rationale: [`ROADMAP.md`](../../ROADMAP.md).

| # | Change | Capabilities | Hard dependencies |
|---|---|---|---|
| 1 | `add-trace-logging` | collection-config, trace-log, harness-packaging | — |
| 2 | `add-explicit-eval` | task-suite, eval-runner, eval-scoring | 1 |
| 3 | `add-dsh-pilot` (Phase 1) | dsh-pilot | 2 |
| 4 | `add-correction-capture` | correction-signal | 1 |
| 5 | `add-claude-code-adapter` | claude-code-adapter (+ harness-packaging, correction-signal, eval-runner) | 1, 2, 4 |
| 6 | `add-experience-wiki` | experience-wiki | 1, 4 |
| 7 | `add-skill-refinement` | refinement-proposal, refinement-gate | 2, 6 |
| 8 | `add-collection-graph` | collection-graph | 1, 2, 7 |

## 13. Open questions

- Should neutral-but-simpler proposals ever pass the gate?
- Wiki pruning and consolidation policy (the paper has none).
- Simulated user for replaying interactive, multi-turn sessions.
- Credit assignment when a failure in a composite subagent spans several components.
- Correction attribution confidence: when does a follow-up turn count as a correction of a specific
  component rather than a change of mind?
