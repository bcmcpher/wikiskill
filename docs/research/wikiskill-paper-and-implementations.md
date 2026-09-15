# WikiSkill: the preprint and two unofficial implementations

Status: research notes, 2026-09-15. Sources were read, not executed. Claims were spot-checked against
the arXiv HTML and shallow clones of both repositories; anything that could not be confirmed is marked
*(unverified)*.

- Paper: **WikiSkill: Compiling Agent Experience into Persistent Knowledge for Skill Evolution** —
  Tang, Rashtchian, Ferng, Tomkins, Juan, Vu (Google Research), arXiv
  [2608.27454](https://arxiv.org/abs/2608.27454) (v1, 27 Aug 2026). No official code release.
- Implementation **A**: [ashutoshsinghpr7/wikiskill](https://github.com/ashutoshsinghpr7/wikiskill)
- Implementation **B**: [Stahl-G/wikiskill](https://github.com/Stahl-G/wikiskill)

---

## 1. The paper

### Problem

Prior skill-evolution methods (Trace2Skill, EvoSkill, SkillOpt) optimise skill text directly from
traces, so what the optimiser learns is lost between iterations — it lives only in scattered
optimisation histories. WikiSkill inserts a persistent, growing knowledge base between raw traces and
skills, and makes the skill proposer consult it.

### State: three layers

The system state is the pair *(S_k, W_k)* — skill set and wiki — both empty at the start.

| Layer | Contents | Written by |
|---|---|---|
| **Raw** (`raw/`) | Immutable execution traces: reasoning, tool calls, outputs, final answers | Harness |
| **Wiki** (`wiki/`) | `patterns/*.md` (one page per failure mode or success strategy, with workarounds); `index.md` (one line per pattern: problem, root cause, fix); an evolution log; `skill-impact.md` | Wiki Maintainer; `skill-impact.md` is appended programmatically by the harness after gating |
| **Skills** (`skills/`) | One directory per skill: `SKILL.md` (frontmatter name/description; sections for when to apply, when not to apply, instructions) and `PURPOSE.md` (origin, patterns addressed, evolution history) | Skill Proposer, subject to the gate |

### Algorithm (Algorithm 1, paraphrased)

0. Score the empty skill set on validation → `R_best`.
1. For each iteration *k*:
   1. Stop early if `R_best` is already 1.0.
   2. **Inference Agent** runs every training task with the current skills. All active skills are
      injected in full into the system prompt (a `{skill_section}` slot), so retrieval/triggering
      cannot confound results. The Inference Agent does **not** see the wiki.
   3. **Sample traces** (Appendix C): up to 8 per iteration — at most 5 failing, up to 3 passing — each
      capped at 15,000 characters before prompt injection.
   4. **Wiki Maintainer** updates the wiki from the sample. Its output is a JSON object that creates
      patterns, updates patterns through span edits (append / replace / insert-after), rewrites the
      full index, and appends a log entry.
   5. **Skill Proposer**, a ReAct-style agent, starts from the wiki index, `skill-impact.md`, and a
      summary of all training outcomes (pass/fail, predictions and ground truth). It has two tools —
      `read_file(path)` and `finish(proposal)` — and its prompt requires reading "at least 4 execution
      traces" before proposing. It submits one atomic proposal: `create`, `patch`, or `no_action`.
   6. **Gate**: apply the proposal and score on validation. Accept only if the new score is *strictly
      greater* than `R_best` (Eq. 4); otherwise roll back the **skills only**. The wiki is never rolled
      back. The harness appends the proposal, diff, score and verdict to `skill-impact.md`.

### Evaluation

- Scoring is task-native, `f ∈ [0, 1]` per task. No LLM judge, no generated test cases.
- Five benchmarks, fixed splits (Table 6, train/val/test): LiveMath 35/18/124, SealQA 16/10/85,
  SpreadsheetBench 80/40/280, OfficeQA 50/24/172, ALFWorld 39/18/134.
- Inference models: Qwen-3.5-4B, Qwen-3.5-9B, Qwen-3.6-27B, Gemma-4-31B, Gemini-3.5-Flash.
- Whole training set per iteration; test scores averaged over three full evolution runs; paired
  bootstrap (1,000 resamples) for significance.

### Key results

**Table 1 — average score, no skill → WikiSkill** (margin over best baseline in brackets):

| Model | No skill | WikiSkill |
|---|---|---|
| Qwen-3.5-4B | 26.2 | 38.5 (+3.3) |
| Qwen-3.5-9B | 29.9 | 47.4 (+5.1) |
| Qwen-3.6-27B | 39.4 | 63.3 (+10.0) |
| Gemma-4-31B | 41.3 | 54.9 (+5.8) |
| Gemini-3.5-Flash | 49.5 | 68.1 (+12.0) |

**Table 3 — ablation of wiki access** (Gemini-3.5-Flash, 4-benchmark average):

| Inference Agent sees wiki | Proposer sees wiki | Avg |
|---|---|---|
| — (no skill) | — | 40.4 |
| yes | no | 45.3 |
| no | no | 48.7 |
| yes | yes | 60.9 |
| **no** | **yes** (default) | **63.7** |

The checkmark columns do not survive HTML text extraction. Rows 3–5 are confirmed by the paper's prose
(48.7 → 63.7 when the Proposer gains wiki access; 63.7 → 60.9 when the Inference Agent also gets it).
The 45.3 row is assigned by elimination.

Two findings matter for design: the wiki is the main driver (+15 points), and **giving the executing
agent the wiki hurts** — the paper hypothesises the agent over-relies on raw notes instead of
distilled skills.

**Table 4 — activity per run.** By benchmark, skill creations proposed/accepted range 1.9–4.9 /
0.9–1.8 and pattern pages created 4.4–9.8; by model, creations 2.3–4.8 / 1.2–1.6 and patterns
6.3–8.9. Acceptance is rare: most proposals are rejected.

**Table 5 — when acceptances happen.** Iterations 0–1 account for 39–52% of accepted updates across
models (39–58% across benchmarks); refinement continues into later iterations.

**Cross-model transfer.** Skills evolved with one model can help another and can beat self-evolved
skills — e.g. Qwen-3.5-9B on ALFWorld reaches 70.2 with Qwen-3.6-27B-evolved skills vs 63.4 with its
own. Evolved skills also let a small model overtake a larger one without skills (9B with WikiSkill
47.4 vs 27B without, 39.4).

### Stated limitations

- Full injection sidesteps skill retrieval and triggering entirely.
- The strict gate discards neutral proposals.
- No wiki pruning or consolidation.
- No very long-horizon tasks.

---

## 2. Implementation A — ashutoshsinghpr7/wikiskill

**Shape.** Zero-dependency Python (≥3.10) CLI, published to PyPI as `wikiskill`. Small codebase
(~2.6k source lines) with a pytest suite and multi-version CI *(repository stats reported at time of
review; a shallow clone cannot confirm commit/star counts)*. Not a Claude Code or OpenCode plugin: it
drives external agent CLIs through backends.

| Concern | Where |
|---|---|
| Algorithm 1 loop (baseline, early stop, sample, maintain, propose, gate) | `wikiskill/harness.py` (`evolve`) |
| Proposal application and gate | `wikiskill/gating.py` (`apply_proposal`, strict `r_val > prev_best`) |
| Skill rollback | `skills/active` is its own git repo; rejection resets it |
| Wiki (git-versioned, never reset) | `wikiskill/wiki.py` (creates `log.md`, `skill-impact.md`, `index.md`) |
| Prompts, skill-impact entries | `wikiskill/prompts.py` (`gate_outcome_entry` records diff + full proposal JSON) |
| Scoring | `wikiskill/scoring.py` — binary graders: exact, contains, json_field, code_stdout |
| Benchmark | `wikiskill/bench.py` — small synthetic suite, no paper benchmarks |
| Backends | `wikiskill/backends/{hermes,claude,codex,copilot}.py`; `claude.py` runs `claude -p --output-format stream-json` |
| Extras | `wikiskill/compare.py` (exact binomial on discordant pairs), `wikiskill/transfer.py` |
| Live-run record | `docs/RUNS.md` — no accepted skill recorded |

**Divergences from the paper.**

- **Skills are provisioned, not injected.** `set_active_skills` (`wikiskill/backends/claude.py:79` and
  siblings) symlinks skills into the agent's skills directory; `inference_prompt`
  (`wikiskill/prompts.py:21`) does not include them. The agent must *trigger* a skill, which
  reintroduces the confound the paper removed.
- **Maintainer is a multi-turn file-editing agent**, not a single call returning a JSON contract; no
  15k-character trace cap.
- **Proposer** writes a proposal JSON file instead of calling `finish`; the four-trace rule exists only
  as prompt text (`wikiskill/prompts.py:104`); the outcome summary omits predictions and ground truth.
- **Uncaught error path.** `apply_proposal` raises `ValueError` for a missing patch target or unknown
  op (`wikiskill/gating.py:92–104`), and `evolve` calls it without a `try` (`wikiskill/harness.py:151`),
  so one malformed proposal aborts the run (read, not executed).
- No test split, repeated runs, or bootstrap.

## 3. Implementation B — Stahl-G/wikiskill

**Shape.** Python ≥3.11 with pydantic, package `wikiskill-research`; larger codebase (~11k lines with
tests) and cross-platform CI that recomputes published results *(stats as reported at review time)*.
`NOTICE.md` says it was extracted from a prior project. It contains **three distinct engines**.

### B1. Legacy research engine

`src/wikiskill/engine.py`, driving `codex exec`.

- Adapters for all five paper benchmarks, with fixed split ID lists.
- Skills are **fully injected** into the prompt via a skill-section slot (e.g.
  `src/wikiskill/sealqa/rollout.py:50`) — faithful to the paper.
- But the skill is a **single monolithic markdown document**, and proposals are whole-document
  rewrites or `no_action`, with line and diff-size caps (`src/wikiskill/skill_proposer.py`).
- The Maintainer contract differs: whole-page pattern replacement, harness-regenerated index, log
  appended to `logs.md` (`src/wikiskill/wiki_maintainer.py`).
- 5-fail / 3-pass sampling in `src/wikiskill/officeqa/wiki_agents.py`; however
  `docs/research-update-20260907.md` discloses that the examined maintainer samples actually held 12
  failures and no successes.
- Strong bookkeeping: append-only event ledger, hash-locked prompts, infrastructure failures separated
  from wrong answers, typed skill-impact verdicts (`src/wikiskill/wiki.py`).

### B2. Paper-aligned isolated study

`src/wikiskill/paper_alignment/contracts.py`, `src/wikiskill/isolated/tools_server.py`,
`src/wikiskill/spreadsheet/study.py`.

- Prompt transcriptions kept under `src/wikiskill/resources/paper_alignment/prompts/*.paper.md`.
- Enforces the Maintainer's four-key JSON contract, unique patch targets, the create/patch/no_action
  proposal shape, required `SKILL.md`/`PURPOSE.md` sections, a ban on evaluator vocabulary, and **at
  least four distinct trace reads** tracked by the tool server (`contracts.py:122`).
- 15k-character trace cap in `src/wikiskill/paper_alignment/evidence.py`.
- Narrow scope: SpreadsheetBench only, one round, a handful of tasks, macOS + LibreOffice.

### B3. Product path

`src/wikiskill/product.py`, `product_cli.py`, `native_agents.py`, entry skill `skills/wikiskill/SKILL.md`.

- Ships Claude Code subagents under `src/wikiskill/resources/product/agents/claude-code/`
  (`wikiskill-{executor,maintainer,proposer}.md`) plus Codex equivalents.
- The controller makes no model calls; it hands work requests to the host agent and records results.
- Simplified wiki (named entries with required source citations); human feedback can be written into
  it. No patch ops, index/log contract, or trace sampling.
- Proposer submits a whole `SKILL.md` or `no_action`. Gate is strict but configurable (direction,
  `min_improvement`), with an explicitly trusted external scorer (`src/wikiskill/scorer_trust.py`).
- README states live Claude Code inference is unverified.

**Evidence.** `docs/research-*.md` report McNemar tests, bootstrap intervals and Bonferroni correction;
a frozen Spreadsheet skill improved held-out accuracy, SealQA was inconclusive, and contamination
incidents are disclosed. These results came from the originating harness, not the shipped CLI.

---

## 4. Reconciliation

| Paper component | A | B | Verdict |
|---|---|---|---|
| Raw / wiki / skills layers | Yes, closely mirrored directories | Legacy: wiki + skill files + attempt dirs; product: journal + artifacts | Both; A's layout closer |
| Skill = directory with `SKILL.md` + `PURPOSE.md`; many skills | Yes | Legacy/product: one file; B2: dict of skills with both files | A faithful by default |
| Full skill injection into prompt | **No** — symlinked, must be triggered | Yes | B faithful; A's largest divergence |
| Inference Agent has no wiki access | Prompt-level instruction | Role-level prohibition; B2 runtime enforces | B stronger |
| Sample ≤8 traces (5 fail / 3 pass), 15k cap | 5/3, no cap | 5/3 in code, cap only in B2; docs disclose 12/0 in practice | Partial in both |
| Maintainer = one call returning JSON edit contract | Multi-turn agent editing files | Legacy: modified contract; B2: exact contract | B2 most faithful |
| Log filename | `log.md` | `logs.md` | Paper inconsistent (see §5) |
| Proposer: ReAct, `read_file` + `finish`, ≥4 traces | Writes JSON file; ≥4 prompt-only | B2 enforces both; legacy single call; product neither | B2 most faithful |
| Atomic `create` / `patch` / `no_action` | Yes | Legacy/product: full rewrite or `no_action`; B2: yes | A faithful by default |
| Baseline, strict `>`, early stop at 1.0 | Yes | Yes (product adds margin) | Agree |
| Roll back skills only; wiki persists | git reset on skills; wiki committed | Incumbent pointer in ledger; wiki persists | Agree |
| `skill-impact.md`: proposal, diff, score, verdict | Diff + full proposal JSON | Typed records with diff, hashes, verdict | Agree; A also keeps full rejected content |
| Paper benchmarks, test split, bootstrap, 3 runs | None (toy suite, binomial compare) | All five adapters, held-out paired tests, not 3-seed | B much closer |

## 5. Ambiguities in the paper that explain the divergence

1. **Log filename.** §3.1 names the evolution log `logs.md`; the Appendix E.2 Maintainer prompt lists
   `wiki/log.md`. A followed the prompt, B the prose.
2. **Maintainer: agent or call?** Described as an agent in §3.2, but costed as a single LLM call with
   traces injected into the prompt (Appendix C/D). A built a tool agent; B a single call.
3. **Patch edits vs full index.** Pattern updates are span edits, yet the index must be rewritten in
   full each time. B's legacy engine regenerates the index in code instead.
4. **Atomic single-skill proposals vs monolithic baselines.** The paper targets one skill per
   proposal, but its SkillOpt-style baselines optimise one document — B's legacy/product engines drifted
   toward a single skill.
5. **What `skill-impact.md` stores.** §3.2 says a unified diff; the E.3 Proposer prompt says it
   contains the full content of rejected proposals. A stores both.
6. **`no_action` handling.** Not represented in Algorithm 1. Both repos skip validation and count the
   iteration.
7. **Iteration budget and numbering.** *K* is never stated; Table 5 counts from iteration 0 while
   Algorithm 1 counts from 1. Defaults differ (A 3, B 4).
8. **Ground-truth leakage.** The Proposer's outcome summary includes ground-truth answers, a leakage
   path into skills. A omits them; B bans answer/evaluator vocabulary in skills.
9. **Enforcing wiki isolation** for the Inference Agent is unspecified.
10. **Infrastructure failures** (timeouts, crashes, API errors) have no stated treatment. B excludes
    them from scores; A scores a missing deliverable as 0 and warns on zero-tool-call sessions.

## 6. Conclusion

- The **loop logic** — baseline, sample, maintain, propose, strict gate, skills-only rollback,
  persistent wiki — is equivalent in A and B, and matches Algorithm 1.
- **A** is more faithful on the **skill layer**: multiple skill directories with `PURPOSE.md` and
  atomic patch proposals, runnable by default.
- **B's paper-aligned study path (B2)** is more faithful on **agent contracts and measurement**: full
  injection, the exact Maintainer contract, trace cap, enforced four-trace reads, real benchmarks and
  statistics. B's main engines drift further than A (single monolithic skill, whole rewrites,
  simplified product wiki).
- The single largest divergences are **A's symlinked (triggered) skills** and **B's monolithic skill**.

**Reference behaviour adopted for this project:** A's skill layer + B2's contracts, trace cap, enforced
reads, infra-failure separation and statistics. The deliberate departure — evaluating *triggered*
skills as well as injected ones — is explained in [`../design/architecture.md`](../design/architecture.md).
