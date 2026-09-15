# Related work: what generalises WikiSkill to skill collections and subagents

Status: research notes, 2026-09-15. Papers were skimmed (abstract, method, evaluation) from arXiv
listings linked by the Hugging Face page for [2608.27454](https://huggingface.co/papers/2608.27454).
Titles confirmed via the arXiv API. Numbers are as reported by a first-pass skim; treat them as
indicative and re-check before citing.

Goal lens: evaluate and refine (a) **collections** of skills, (b) **composite subagents** with tools
and multi-step trajectories, (c) **data-science** tasks whose outputs are code, notebooks and
statistics that can be checked.

## Summary table

| arXiv | Title | Core idea | Evaluation | Tuning | Rel. | Borrow |
|---|---|---|---|---|---|---|
| [2608.16544](https://arxiv.org/abs/2608.16544) | VCE-Skill: Enhancing Skill Self-Evolution with Version-Change Experience | Adds a second evolution signal mined from public skill version histories (diff → event → pattern → insight) | 5 benchmarks × 4 models; mean and cross-model transfer gains; human audit of judge decisions | Weighted fusion of external vs self proposals, adjusted by which source produced accepted edits | High | Event→pattern→insight abstraction for a library-wide change history; **attribute credit** to the proposal source that caused an accepted edit |
| [2607.28048](https://arxiv.org/abs/2607.28048) | SKILL-KD: Contrastive Skill Distillation for LLM Agents | Diff a strong teacher's successful trajectory against a weak student's failure on the same task → textual skill patch for a frozen student | 5 benchmarks, native success/exact-match | Patch → rerun → consolidation agent revises (≤3 rounds); drift-aware consolidation with trace-linked add/modify/delete/skip | High | **Contrastive step-level diffs** (gold analysis vs attempt: wrong join, wrong test); **trace-linked edit ops** to prevent library drift |
| [2608.06880](https://arxiv.org/abs/2608.06880) | SkillAligner: Treating Retrieved Skills as Adaptable Drafts at Execution Time | Training-free: treat retrieved skills as drafts and compile a per-task guide (Primary / Checks / Avoid / Fallback) resolving conflicts between skills | ALFWorld, WebShop, 7 search-QA sets, 3 backbones, 10 baselines; **transfer vs regression** rates; judge-classified regression causes | None persistent; one-shot three-stage adaptation per task | High | Report **transfer and regression** per instance with a **cause taxonomy** (inter-skill, skill-environment, skill-task); per-fragment usage modes (direct / guarded / abstain) |
| [2608.15071](https://arxiv.org/abs/2608.15071) | Evo-Harness: Context-to-Harness Skill Compilation for Self-Evolving Agents | Online harness learning: failures → candidate memories (`lesson, trigger, evidence, scope_hint`) → evolver compiles two-tier harness via add/merge/revise/skip | 5 benchmarks with **different verifier types** (programmatic state, Docker, unit tests, rubric, DB state); 3 seeds; rich ablations incl. same- vs cross-model solver/evolver | Continuous across task batches | High | **`trigger / evidence / scope_hint`** memory schema pinned to the failing step; pair each skill with a **matching verifier type**; cross-model solver/evolver test |
| [2608.06153](https://arxiv.org/abs/2608.06153) | Learning Globally Reusable Skills for Coding Agents | Co-evolve skills and a **Skill Relation Graph** (dependency / co-usage / conflict); cluster consolidation; **replay-driven verification** | Bug-revealing test generation and false-positive bug-report filtering with objective ground truth; held-out-project protocol; two open agents + industrial deployment | Proposed updates propagate to graph neighbours; candidate bank accepted only if replayed historical cases hold or improve | High | **Relation graph** before touching any one skill; **replay gate** on historical cases; classification-style ground truth over free-text judging |
| [2607.25853](https://arxiv.org/abs/2607.25853) | HiSkill: Empowering LLM Agents with Hierarchical Skill Graphs | Graph of skill nodes and atomic-op nodes with typed edges (decomposes, follows, compatible, supports, recovers); rule-based execution over retrieved subgraph | ALFWorld, WebShop, ScienceWorld seen/unseen; success rate **and token consumption** | No optimisation loop; structure only | Med | `supports` / `recovers_with` edges for error-recovery routing in pipelines; **token cost as a first-class metric** |
| [2608.10319](https://arxiv.org/abs/2608.10319) | Do Personalized Skills Help Coding Agents? An Empirical Study of Developer Interaction Histories | Do skills distilled from one developer's history help that developer more than pooled skills? | 206 real sessions / 13 developers; **trajectory-conditioned simulated user** for replay; judge completion + interaction efficiency + execution behaviour; paired tests over seeds | None (empirical) | Med | **User-correction histories** as signal; simulated user for multi-turn replay; **pooled baseline first** — personalisation gave small, non-significant gains |

## Ranked ideas to borrow

1. **Verifier-first metrics** (GSE, Evo-Harness). Prefer task-native checks — correct route, test
   passes, statistic within tolerance, ledger validates, notebook re-executes — over holistic LLM
   judging. Use a judge only for rubric dimensions that have no verifier.
2. **Skill relation graph** (GSE; HiSkill's typed edges). Model dependency, co-usage and conflict
   explicitly. Editing one component can silently break or steal triggers from another; this is the
   key step from single-skill tuning to collection tuning.
3. **Regression-first gating** (GSE replay; SkillAligner transfer/regression). Report what broke as
   well as what improved, classify why, and require no regression on a replay bank before accepting.
4. **Attributable, step-pinned lessons** (Evo-Harness `trigger/evidence/scope_hint`; SKILL-KD
   trace-linked edits; VCE-Skill source attribution). Essential for composite subagents, where the
   failure is at one delegation or tool call, not the final answer.
5. **User interaction as signal** (2608.10319). Corrections and follow-ups are evidence; a simulated
   user enables replay of interactive sessions.
6. **Token and cost reporting** (HiSkill). Cheap to add; matters when comparing local models.

## Conflicts and how this project resolves them

- **Pooled vs specialised.** VCE-Skill, SKILL-KD and GSE pursue fine-grained specialisation;
  2608.10319 found pooled skills beat personalised ones under limited data. → Default to general
  edits; fork a model- or user-specific variant only with repeated evidence.
- **Execution-time adaptation vs persistent evolution.** SkillAligner adapts per task without editing
  the library; WikiSkill, GSE, Evo-Harness and VCE-Skill evolve a persistent library. → Complementary
  fast/slow layers. This project implements the slow layer; any change must declare which layer it
  targets.
- **Executor access to accumulated knowledge.** WikiSkill's ablation shows the executing agent does
  worse when it sees the wiki; Evo-Harness compiles lessons into the harness the solver uses. → The
  executing agent sees only compiled skills, never raw wiki pages.
