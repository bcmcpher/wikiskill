## Context

data-science-harness has three layers:
- workflow-plane planner skills with `delegates_to` frontmatter
- capability-plane doer agents (annotate, archive, bids, compendium, containers, liab, nipoppy)
- vendored CLI toolbox skills whose descriptions overlap with planners — datalad-save vs checkpoint,
  datalad-push vs publish, zenodo vs dataset-release

Its `openspec/specs/evaluation-protocol/spec.md` defines four probes: routing, provenance,
reproducibility, and cost. It requires a named control for each, per-model reporting, reuse of existing
instruments, and a plain statement of what is unrun. `bench/probes/routing.yaml` defines `route@1`,
`route@k` (k ∈ {1, 3}), a graded `capability@k`, and a judged `handoff@k` with three judges whose
per-judge labels are reported.

Its `bin/install.sh --harness opencode` drops agent `tools:` and maps `haiku/sonnet/opus` to Anthropic
ids. It pins models only on `bids-doer` and `coordinator`.

**What the first unit established** (`docs/pilots/dsh/report.md`): `archive/archive-doer` went through v1,
review, refine, a candidate run, replay and a rejection, on `gemma4` and `qwen3:30b-a3b`. INJECTED
beat OFF on both models with non-overlapping intervals. qwen3 was at 18/18 under INJECTED, at the
ceiling. In 30 of 36 INJECTED units the doer's readiness script was not found, because the doer names
it by a path relative to the DSH repository.

**Machine.** An NVIDIA GB10 with Ollama 0.34.2 and OpenCode 1.18.34. All models are Q4 unless
noted. The ones marked *added* were pulled on 2026-10-06 for this sweep. For those, size and shape
are as the Ollama library lists them, until task 4.1 confirms them with `ollama show`.

| model | family | size | shape | why it is in the sweep |
|---|---|---|---|---|
| `qwen2.5-coder:1.5b` | Qwen (Alibaba) | 1.5B | dense | failed the tool-call probe on 2026-10-01; kept as a preflight check |
| `qwen3:1.7b` | Qwen | 2.0B | dense | bottom of the Qwen size ladder |
| `granite4.1:3b` *added* | Granite (IBM) | 3B | | Granite size ladder |
| `ministral-3:3b` | Mistral | 3.8B | dense | bottom of the Mistral ladder |
| `mistral:latest` | Mistral | 7.2B | dense, older | an older tool-calling model; may fail preflight |
| `gemma4:latest` | Gemma (Google) | 8.0B | dense | v1 model; the noise rerun |
| `granite4.1:8b` *added* | Granite | 8B | | Granite size ladder |
| `gpt-oss:20b` *added* | gpt-oss (OpenAI) | 20B | MoE, MXFP4 | gpt-oss at a smaller size, same tuning |
| `mistral-small3.2:24b` *added* | Mistral | 24B | dense | top of the Mistral ladder |
| `qwen3.8:latest` | Qwen | 27.3B | dense | dense against MoE at ~30B |
| `granite4.1:30b` *added* | Granite | 30B | | top of the Granite ladder |
| `qwen3:30b-a3b` | Qwen | 30.5B | MoE, 3B active | v1 model |
| `qwen3-coder:30b` *added* | Qwen | 30B | MoE, 3B active | the same architecture as `qwen3:30b-a3b`, tuned for coding and agents |
| `glm-4.7-flash` *added* | GLM (Zhipu) | | MoE | a new family, agentic, with thinking |
| `gemma4:31b` *added* | Gemma | 31B | dense | Gemma size step from 8B |
| `olmo-3:32b` *added* | OLMo (AI2) | 32B | dense | fully open data and training |
| `nemotron-3.5-lightning:latest` | Nemotron (NVIDIA) | 32.9B | hybrid MoE | a new family, with thinking |
| `llama3.3:latest` | Llama (Meta) | 70.6B | dense | the largest dense model; a judge |
| `gpt-oss:120b` | gpt-oss | 116.8B | MoE, MXFP4 | the largest model; a judge |

Nine families, with a size ladder in five: Qwen, Granite, Mistral, gpt-oss and Gemma.

## Goals / Non-Goals

**Goals:**
- Know how much a DSH component's instructions are worth as a function of the model: across
  families, across sizes within one family, dense against MoE, and with thinking on or off.
- Know how much a result moves between two runs of the same version, which bounds what the gate can
  detect.
- Test the readiness-path finding as a change, through the gate.
- First executed routing probe for data-science-harness, reported per model and condition.
- Evidence on whether routing failures come from descriptions (routing loss) or instructions (content
  value).

**Non-Goals:**
- **Editing data-science-harness.** Proposals from the pilot are delivered as patches for its owner.
- **Passive use and Phase 2.** Moved to their own changes.
- **Cost probe.** Its instrument is Claude Code-specific; token and time figures are reported without
  claiming the probe.
- **Quantization and context length as variables.** Every model runs at Q4 (MXFP4 for gpt-oss) and
  at the context its server reports. Both are recorded, not varied.

## Decisions

**Build, not install.sh.** wikiskill's collection build reads data-science-harness sources in place
and applies this repository's alias table. It maps `haiku` to the small tier and `sonnet`/`opus` to the
large tier, and translates `tools:` into OpenCode permission blocks. data-science-harness's own
installer is untouched.

**The hand-written candidate goes through the gate.** `wikiskill refine --prepare` writes the
prompt; the reply is written by hand and validated with `--reply-file`, citing the units where the
script was not found. It is then evaluated like any proposal: `eval --proposal` with v1's suite,
models, conditions and repeats, `proposal replay` against v1, `proposal decide`. A hand-written patch
gets no easier path than a generated one. `wikiskill diff` shows the text and results side by side
for the report.

The doer lives in plugin `archive` and the script in plugin `archive-cli`, so `${CLAUDE_PLUGIN_ROOT}`
alone points at the wrong plugin. The candidate needs a reference that resolves both in a DSH
checkout and in an install. `collection check` warns about a path that climbs out with `../`, so the
form is chosen by checking what both installers lay down, and `collection check` must pass on the
candidate.

**Sweep design.**
- *Suite:* `pilots/archive-doer/suite.yaml`, unchanged, so its hash matches v1 and the v1 run pools
  in.
- *Conditions:* OFF and INJECTED. ROUTED is not meaningful for a delegated doer.
- *Repeats:* 10 per task, giving n = 60 per cell and Wilson intervals of about ±12 points at 50%,
  against ±20 at n = 18. The 3-repeat v1 run pools in for gemma4 and qwen3:30b-a3b. The number is
  fixed before the first sweep run and stated in the report.
- *Thinking:* every model runs at `--thinking default`. The models whose server says they can think
  also run at `--thinking off`: the qwen3 models, gpt-oss, nemotron, gemma4, glm and olmo. The leaderboard keeps the two settings apart as
  separate entrants.
- *Order:* one run per model, smallest and fastest first, so that each finished run is a complete
  cell set. A model whose run does not finish is reported as unrun, not as partial rates. Runs are
  sequential, so two large models never compete for memory.
- *Noise:* one model, `gemma4`, runs the v1 suite a second time on a different day with the same
  settings. `wikiskill compare` of the two same-version runs gives the run-to-run spread.

The sweep answers these questions, each read from the per-model table:
1. Does INJECTED − OFF shrink as size grows within a family? Five ladders: Qwen (1.7B, 27B, 30B),
   Granite (3B, 8B, 30B), Mistral (3B, 24B), gpt-oss (20B, 120B) and Gemma (8B, 31B). The same
   direction in most ladders is a finding. One ladder alone is not.
2. Dense against MoE at similar size: `qwen3.8` (27B dense) against `qwen3:30b-a3b`.
3. Tuning with the architecture fixed: `qwen3-coder:30b` against `qwen3:30b-a3b`.
4. Does thinking change rule-following, or only latency and tokens?
5. Is any model unsafe under OFF, inventing a DOI or moving a tag, where the doer's rules would have
   stopped it?
6. Where a small model fails, is it the tool-call format (permission or infra outcomes) or the task?

If two or more models are at the ceiling under INJECTED, the suite no longer separates them. Harder
tasks then go in a new suite file, so the existing hash and its runs stay comparable.

**Routing probe mapping.**
- *Collection:* `pilots/dsh/dsh.toml`, the whole of DSH, with no `plugins` filter.
- *Suite:* `pilots/dsh/routing.suite.yaml` takes every task of `bench/tasks/routing-lifecycle.yaml`
  at DSH's pinned commit, with `expected_skill` as the route and `expected_delegates_to` as the
  delegates for `capability@k`.
- *Control:* the protocol's harness-off condition is OFF.
- *Conditions:* ROUTED is the harness-on condition. INJECTED adds the decomposition the protocol does
  not define, and is reported as supplementary.
- *Route metrics:* `route@1`, `route@k` (k=3), and `capability@k`, as defined in `bench/probes/routing.yaml`.
- *Judges:* `handoff@k` uses a three-judge rubric. The judges are the three largest models from
  different families: `gpt-oss:120b`, `llama3.3`, `nemotron-3.5-lightning`. `eval-scoring` forbids
  a judge that is a model under test, so these three are not routing entrants. Their sweep results
  stand, because the sweep uses no judge.
- *Models:* every other model that passed the sweep's preflight and finished its sweep run, at
  `--thinking default`. They cover at least three families.
- *Same-family judging:* where a judge shares a family with the model that delegated, as
  `gpt-oss:120b` does with `gpt-oss:20b`, its label is reported but marked. The majority of the
  other two judges is reported beside the three-judge majority.
- *Routing loss against content value:* for each planner task, compare ROUTED with INJECTED. A task
  that passes INJECTED but fails ROUTED lost on the description; one that fails both lost on the
  instructions.

**Choosing the best version.** This uses the version board from `add-version-board`.
- *Versions:* at most six of `archive/archive-doer`.
  - v1, the source at `c6f6079`, and the baseline throughout
  - `p-002`, rejected on two models but still a version
  - the readiness candidate (3.x)
  - one proposal from a review of every sweep run
  - up to two proposals from `review --model`, for the models with the lowest INJECTED rate under v1
    that still passed preflight
- *Critical checks:* `pilots/archive-doer/critical.yaml` marks the checks that encode the doer's
  hard rules: no DOI in the reply, tags unmoved, no commit. A version that breaks one in any unit is
  never named best.
- *Baseline data:* the sweep (4.x) is v1's OFF and INJECTED on every model. OFF is shared, so
  candidates run INJECTED only.
- *Screening:* each candidate runs on a panel of one model per family that passed preflight, taking
  the family's middle size. A per-model candidate also runs on its target model. Screening repeats
  are set from the unit times measured in the sweep, so that screening fits the time available. They
  are stated before the first screening run.
- *Finals:* the two candidates with the best screening mean that are not disqualified, plus any
  version that was best on a screening model, run on every sweep model at the sweep's repeats.
- *Confirmation:* the top of several noisy versions is biased upward. So the version the finals name
  best overall, and v1, run again, fresh, on the screening panel. A per-model best that differs from
  the overall best and was `up` in the finals is confirmed on its model alone. Only confirmed results
  are reported as findings.
- *Decision:* the confirmed best overall goes through the gate as usual: `proposal replay` against
  v1, then `proposal decide`. The board ranks; the gate decides. Per-model bests are reported as
  findings for the maintainer, not accepted as forks of the doer.

**Report structure** (`docs/pilots/dsh/report.md`):
1. *Setup:* DSH commit, OpenCode and Ollama versions, the model table with served contexts, and the
   models that failed preflight, each with its reason.
2. *Unit 1: archive-doer:* the existing section on v1, p-002 and the decision.
3. *Model sweep:* repeats, then the per-model OFF and INJECTED rates with lift, grouped by family
   and ordered by size. Then the thinking table, the run-to-run spread, and an answer to each of the
   six questions, each citing its table rows.
4. *Versions:*
   - a version table: label, hash, origin, a one-line `diff` summary
   - the critical checks
   - screening, then finals: the board's per-model table and overall table
   - the best version overall, and the best per model, each with its direction against v1
   - the confirmation, and the gate decision
5. *Routing probe:* `route@1`, `route@k`, `capability@k` per model under OFF and ROUTED, `handoff@k`
   with per-judge labels, and the routing-loss breakdown.
6. *For the DSH maintainer:* accepted patches with their comparisons, and per-model findings.
7. *Not run:* probes, models and runs that did not finish, with reasons.

**Namespacing.** Expected routes like `govern/preregister` match OpenCode's flat skill names. The
adapter keeps a mapping, and the report prints both.

**Safety.** The guard denies `git push`, `datalad push|siblings`, network CLIs, and credential
access. Runs use a fixture workdir with a stub `.datalad` marker only where a prompt needs it;
`DATALAD_AUTOSAVE=0` is set.

**Pinning.** Every run records DSH's commit, OpenCode and Ollama versions, and each model's served
context in `run.json`. All runs in this change use DSH `c6f6079`. If DSH moves, the pilot stays on
`c6f6079` until this change is archived.

## Risks / Trade-offs

- [Screening and finals multiply GPU time by the number of versions] → the screening panel and
  repeats are sized from measured unit times before screening starts. Finals take two candidates at
  most, plus per-model winners.
- [Nineteen models is many hours] → if the sweep must shrink, drop `olmo-3:32b` and
  `granite4.1:8b` first, then the thinking arm of the models with the smallest INJECTED − OFF gap.
  Dropped models are listed in the report as unrun.
- [Large dense models are slow] → `llama3.3` (70B dense) decodes far slower than the MoE models.
  It runs last. If its run cannot finish, it is reported as unrun, and its judging role passes to
  the next-largest model of another family.
- [A model fails preflight] → recorded with the reason; the sweep proceeds with those that pass.
- [Ceiling effects] → harder tasks go in a new suite file; the old hash is never edited.
- [Judges share a family with the model judged] → marked, and a two-judge majority is reported
  beside the three-judge one.
- [Flat skill-name collisions after build] → build fails on collision; mapping printed.
- [Stop hook auto-commits in DataLad datasets] → `DATALAD_AUTOSAVE=0` in every run environment.

## Open Questions

- Should a Claude Code arm with an Anthropic model run the archive suite as a frontier reference? It
  needs paid API use and is the user's call. It is optional and not required to archive this change.
