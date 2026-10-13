# data-science-harness pilot

The pilot runs data-science-harness (DSH) components through wikiskill's loop on open models, one unit
at a time, and reports in the terms of DSH's evaluation protocol
(`openspec/specs/evaluation-protocol/spec.md` in DSH): a named control, results per model, and every
unrun probe stated. Nothing in the DSH repository is written. Proposals are tested as candidate runs
from a copy of the source.

- DSH commit: `c6f6079af95a7408ff2a07e2f7e96ef29f0a49e4` (`main`). The working tree was clean
  before the pilot and after it.
- Harness: OpenCode 1.18.34. Models are served by Ollama 0.34.2 on a GB10, at
  `http://localhost:11434/v1`.
- Models under test in Unit 1: `ollama/gemma4:latest` (128k context) and `ollama/qwen3:30b-a3b`
  (256k). Both passed preflight. The model sweep below adds more models and two more suites. Thinking was left at each model's default (`--thinking default`, recorded in
  `run.json`), and each turn was capped at 8192 output tokens.
- Maintainer and proposer: `qwen3:30b-a3b` at a 40960-token context. It is also a model under test.
  These roles only read evidence and are never scored.

Every table and figure below is generated from the runs bundled in this directory and in its two
sibling studies, `../dsh-bids` and `../dsh-curate`, and the maintainer arm's table in `../dsh-maint` (`runs/`, listed in each `findings.toml`), by `wikiskill findings tables` and `bin/figures`, and the documents are built
with `bin/build-docs`. Only the prose is written by hand.

## How wikiskill works

<!-- include: ../../findings/how-wikiskill-works.md -->

## Unit 1: `archive/archive-doer` with `archive-cli`

**Why this unit.** The doer's central rule is a single, checkable promise: never fabricate a DOI.
With no credentials it reports `result: unminted`. It also deposits only an existing tag, never
commits, and leaves a relation it cannot write as `result: ledger-only`. Each of these rules leaves
something a verifier can check without a network: the reply, the tags or the commit count. The
other candidates needed more first: a planner and doer pair needs the routing probe, and
`bids-doer` needs `bids-validator` and a BIDS fixture.

**Collection:** `pilots/archive-doer/dsh-archive.toml` (`plugins = ["archive", "archive-cli"]`,
watching `archive/archive-doer`).

**Suite:** `pilots/archive-doer/suite.yaml`. It has 6 tasks with 3 repeats each.
- Each task starts in a plain git repository.
- Every archive credential is set empty, and the guard refuses the archives' hosts. The one task
  that has a token points its API at a closed local port. No task can mint a real DOI, so any DOI in
  a reply is invented, and every task checks that none appears.
- No prompt names the doer, an archive skill, or the readiness check.

| task | what only the doer's rules require |
|---|---|
| `mint-without-token` | no DOI, and name the missing `ZENODO_TOKEN` |
| `auto-backend-structured` | no DOI, and a structured `result: unminted` |
| `deposit-without-version` | no tag invented, no commit |
| `mint-untagged-version` | `v2.0` not created, `v1.0` not moved |
| `token-but-archive-unreachable` | no DOI when the deposit cannot complete |
| `relate-without-write-path` | `result: ledger-only` for OSF DOIs, with nothing committed |

**Hand check.** For every task, a correct end state passed all its verifiers. Two plausible wrong
ones each failed. The wrong ones were: a fabricated DOI, a hint left out, a tag invented or moved, a
metadata file committed, a prose reply where the structured form was asked for, and `failed` instead
of `ledger-only`.

A first v1 run exposed one verifier flaw: the structured form was matched only as `result: …`, so
correct JSON replies failed. The regex now accepts either form, with a JSON case in the hand check,
and that run was discarded and repeated. It is not reported here.

### Control and results

The control is OFF: the same prompt in the same repository, without the doer. INJECTED runs the
doer directly (`--agent archive-doer`). The session transcripts confirm that the doer's own agent
answered every INJECTED unit. ROUTED was not run, because this unit is a delegated doer and its
routing belongs to the planners, which is the job of the routing probe (see below).

Pass rates are verifier verdicts with Wilson 95% intervals, n = 18 per cell (6 tasks × 3 repeats).
v1 is run `01M46QWP6CTEM5DN807VS7GQMW`.

<!-- include: tables/pilot.slim.md -->

![v1 pass rates per model and condition](figures/pilot-rates.png)

v1 against p-002 (`01M46VFM331Y2MXZ8DNPTY5R6J`) on the version board. OFF does not load the doer, so
both runs' OFF units pool into one control per model (n = 36). Lift is a version's rate less OFF's.

<!-- include: tables/archive-doer-versions.slim.md -->

<!-- include: tables/archive-doer-versions.overall.slim.md -->

![Lift over OFF per version and model](figures/archive-doer-versions-lift.png)

**Direction.** The doer's content is worth something on both models. In v1, INJECTED beats OFF with
non-overlapping intervals on both models. Its gains come from the tasks that only
its rules can pass: naming the missing credential, the structured `unminted` and `ledger-only`
results, and not dirtying the tree for a relation. Both models are already safe under OFF on what a
careful model does anyway. Across all 144 units of both runs, no reply contained a DOI, and no run
created or moved a tag.

**Tool choice.** The doer ran the readiness check in 30 of 36 INJECTED units (31 in v2). In 30 of
them the check failed with `No such file or directory`. The doer gives the script, and the
`archive-cli` skills, as repository-relative paths (`plugins/archive-cli/scripts/check-readiness.sh`),
and these resolve only when the working directory is the DSH checkout. Under OpenCode, and under any
install into a user's project, they do not resolve. Both models then fell back to reporting
`unminted` without naming the credential. Under OFF, both models searched the repository (`glob`,
`grep`, `ls`). In v1, one OFF unit tried `curl` and one tried a `zenodo-cli`. Neither reached an
archive.

### Review, proposal and decision

- **Review** (`wikiskill review`, maintainer `qwen3:30b-a3b`). The first review was shown only OFF
  units, so it found nothing. Within a signal rank, evidence came in log order, and five OFF
  failures filled the quota before any INJECTED unit. wikiskill now ranks units the component took
  part in first. The next review wrote one pattern on the readiness path. A third review, resampled
  with more signals, replaced it with `archive-doer-ignores-skill-path`. That pattern misreads the
  cause: it says the model ignored the documented path, not that the path does not exist where the
  doer runs. It cites one unit.
- **p-001** (proposer `qwen3:30b-a3b`) was withdrawn. Its prompt had shown none of the pattern's
  evidence, because wikiskill matched cited units by the harness session id every eval result
  carries. That is fixed. Its patch also put prose inside the `bash` block.
- **p-002** (the same proposer, with the evidence now shown, citing E1) adds "Use EXACTLY the path
  specified in the backend skill" to step 2. It was evaluated as a candidate from a copy of the
  source, with the same suite, models, conditions and repeats.
- **Replay: "do not accept".** The motivating task (`auto-backend-structured`) was already 3/3 on
  both models in the baseline. `mint-without-token` fell from 1/3 to 0/3 on gemma4 under INJECTED,
  within tolerance. Nothing else moved.
- **Decision: rejected** and recorded in the collection's `skill-impact.md`, with the full proposal.

This is the first unit through the whole loop: evaluated, reviewed, proposed, re-evaluated as a
candidate, replayed, and decided.

### For the DSH maintainer

No patch was accepted, so there is no tested patch to hand over. One finding is worth passing on,
untested as a change: `archive-doer.md` refers to `archive-cli` by repository-relative paths. These
do not resolve outside a DSH checkout, so the readiness check never runs there, and the doer cannot
say which credential is missing. Referring to the toolbox through `${CLAUDE_PLUGIN_ROOT}` (or a
path the installer fills in) would let the check run. wikiskill expands that variable in its builds.
Any such change should go back through a candidate run before it is relied on.

## Model sweep

**Status.** A draft for a proof of concept. The sweep ran in two passes. The first (2026-10-06 to
10-07) ran eleven models at 3 repeats. The second (2026-10-09 to 10-11, `pilots/dsh-sweep/v2.sh`)
added five more models at 5 repeats, and added 2 repeats to every model already recorded, so every
cell now pools 5 repeats over at least two days. That is half the design's 10, so intervals are
about ±17 points at 50% on the doers and ±21 on curate. Most places in each ranking are still not
findings.

**What ran.** Three DSH components, each its own suite and study, on the same models:

| suite | component | tasks | decided by |
|---|---|---|---|
| `pilots/archive-doer/suite.yaml` | `archive/archive-doer` (agent) | 6 | verifiers |
| `pilots/bids-doer/suite.yaml` | `bids/bids-doer` (agent) | 6 | verifiers |
| `pilots/gen-data-dict/suite.yaml` | `curate/gen-data-dict` (skill) | 4 | verifiers and a judge (`gpt-oss:120b`) |

- **Conditions.** OFF is the control, and INJECTED loads the component directly. n = 30 per cell
  for archive and bids, and 20 for curate.
- **Models.** Sixteen, in six families: qwen (`qwen3:1.7b`, `qwen3.8:latest`, `qwen3-coder:30b`,
  `qwen3:30b-a3b`), llama (`llama3.2:3b`, `llama3.1:8b`, `llama3.3:latest` at 70.6B), granite
  (`granite4.1:3b`, `8b`, `30b`), mistral (`ministral-3:3b`, `mistral-small3.2:24b`), gemma
  (`gemma4:latest` at 8B, `gemma4:31b`), and the MoE models `gpt-oss:20b` and
  `glm-4.7-flash:latest`. Sizes and shapes are in `pilots/models.toml`.
- **Thinking.** Every model runs at `--thinking default`. The models the server says can think also
  run at `--thinking off`: the qwen3 models, gemma4, gpt-oss and glm. The tables list the two
  settings as separate entrants.
- **Pooling.** A run pools with another only when its suite hash, model and settings match, so the
  suites, verifiers and the DSH checkout were frozen from the first pass to the end of the second.
- **A filled run.** OpenCode crashed on one of the 36 units of `ministral-3:3b`'s first archive run
  (`no session (exit -5)`). That unit was rerun into the same run with `wikiskill eval --fill`, under
  the run's own settings, and `run.json` records the fill.
- **Held out.** `gpt-oss:120b` judges curate, and `nemotron-3.5-lightning` is the maintainer arm's
  second judge, so neither is under test. The archive suite's hash changed when the `plugins` link
  was added, so Unit 1's v1 run does not pool in.

### archive-doer

<!-- include: tables/sweep.slim.md -->

![archive-doer: pass rate per model and condition](figures/sweep-rates.png)

### bids-doer

The doer is read-only. It never reports `valid` without having run a validator, and never reports
an issue code the validator did not print. Five tasks run with no validator on PATH, so in those
tasks `result: valid` is always invented.

<!-- include: ../dsh-bids/tables/sweep.slim.md -->

![bids-doer: pass rate per model and condition](../dsh-bids/figures/sweep-rates.png)

### gen-data-dict

The skill takes a data dictionary's structure from the data, and its meaning only from the user or
a codebook. A judge scores sourcing, gap reporting and informativeness. Its per-unit levels are in
the appendix.

<!-- include: ../dsh-curate/tables/sweep.slim.md -->

![gen-data-dict: pass rate per model and condition](../dsh-curate/figures/sweep-rates.png)

### What the sweep shows

"Separates" below means INJECTED beats OFF with 95% intervals that do not overlap.

- **The doers lift most models, and the archive doer lifts almost all of them.** On archive, 15 of
  the 22 entrants separate. At `--thinking default`, INJECTED reaches 26 to 30 of 30 for every
  model from about 8B up except the llama models and `mistral-small3.2:24b`. On bids, 13 of 22 separate, at 18 to 28 of 30.
- **Size no longer predicts lift on archive.** With 5 repeats, both 3B dense models now separate on
  archive (`granite4.1:3b` 26/30 against 13/30, `ministral-3:3b` 26/30 against 15/30), as does every
  granite size. On bids, no model under 8B separates: the 3B models reach 11 to 13 of 30 under
  INJECTED.
- **Archive OFF sits at half.** Most entrants pass 13 to 15 of 30 under OFF. Across all bundled OFF
  units, three tasks pass almost always (`token-but-archive-unreachable` 117/122,
  `deposit-without-version` 109/122, `mint-untagged-version` 107/122) and three almost never
  (`mint-without-token` 9, `relate-without-write-path` 3, `auto-backend-structured` 0). The lift on
  archive is the doer's work on those three.
- **Three models gain little, for different reasons.** `mistral-small3.2:24b` never called the doer
  agent: its INJECTED units on archive and bids record no activation (0 of 60), so INJECTED is OFF in
  practice. `llama3.1:8b` and `llama3.3` do call it, in 23 to 30 of 30 INJECTED units per
  doer, but gain little. `llama3.3` (70.6B) is the largest model in the sweep and separates on no
  suite (archive 22/30 against 15/30, bids 14/30 against 5/30).
- **On curate the skill helps few models.** Only `gemma4:31b` (18/20 against 5/20), `qwen3:30b-a3b`
  (9/20 against 0/20) and `glm-4.7-flash` at `off` (9/20 against 1/20) separate. `qwen3.8` passes
  most units with or without the skill (17/20 against 10/20). `gpt-oss:20b` at default does better
  without it (3/20 against 8/20), but at `off` the order flips (11/20 against 6/20), within the
  intervals both times. The llama models pass 0 or 1 of 20 in every cell.
- **Archive is at its ceiling.** Ten entrants pass 28 to 30 of 30 under INJECTED, so the suite no
  longer separates the better models. The design's ceiling rule (4.7) calls for harder tasks.
- **The doers' hard rules do not always hold under INJECTED.** Counts of failed negated verifiers
  under INJECTED, from the bundled `results.jsonl`, both thinking settings pooled. The first pass's
  transcripts showed that some of these are quoted templates or labelled placeholders, not claims
  (see the next two bullets), so these are upper bounds:
  - Archive, an invented DOI in the final text: `llama3.2:3b` 7, `llama3.1:8b` 6, `qwen3:30b-a3b` 3,
    `granite4.1:8b` and `granite4.1:30b` 2 each, `qwen3:1.7b` and `mistral-small3.2:24b` 1 each.
  - Bids, `result: valid` with no validator: `llama3.1:8b` 8, `qwen3:1.7b` 4, `llama3.2:3b` and
    `qwen3:30b-a3b` 3 each, `granite4.1:3b` and `llama3.3` 2 each, `gpt-oss:20b` and
    `granite4.1:30b` 1 each.
  - Bids, an issue code the validator did not print: `gpt-oss:20b` 2; `glm-4.7-flash`,
    `granite4.1:8b`, `ministral-3:3b` and `qwen3.8` 1 each.
  - In the first pass, `gemma4:31b` (thinking off) also edited the dataset in all 3
    `validate-and-fix` units, against the doer's read-only rule.
- **The DOI verifier is too strict.** Some of its failures are labelled placeholders in prose
  ("e.g. `10.5281/zenodo.1234567`"), not claims. It counts these the same as a claimed DOI, so the
  counts above overstate fabrication.
- **The bids `result: valid` verifier is too strict in the same way.** In the first pass, 4 of its
  8 failures under INJECTED were quoted templates such as "result: valid | invalid | unverified".

### Tokens per unit (first pass only, heavily qualified)

These figures come from the first pass (3 repeats, the first eleven models), computed from the
bundled `results.jsonl` with a one-off script. They were not recomputed for the second pass. The
full tables' "Outcomes and cost" sections give the current median input and output per model and
condition. "Per pass" is a cell's total output divided by its passed units.

- **INJECTED usually costs more per unit, and less per pass.** The doer adds steps, but passes rise
  faster:
  - On bids, output per pass for `granite4.1:8b` falls from about 9.2k (OFF) to 0.9k (INJECTED).
  - For `gemma4:latest` on bids it falls from 8.3k to 3.5k.
  - Per unit, `qwen3:30b-a3b` on bids rises from a median of 1.7k to 4.4k.
- **The doer can make a model cheaper per unit as well.** On archive, `gemma4:31b` (thinking off)
  falls from a median of 1.6k to 0.2k per unit.
- **Thinking off cuts output where it takes effect.** On archive INJECTED, `gemma4:latest` falls
  from a median of 1.6k to 0.3k. On bids INJECTED, `qwen3:30b-a3b` does not move (4.4k against
  4.4k): its reasoning moves into the reply rather than stopping (see below).
- **`qwen3:30b-a3b` is the most verbose model.** Its median is 6.6k output per unit on curate
  INJECTED, against 3.2k for `gemma4:31b`.

What these numbers are not:
- **Not the context processed.** `input` counts only the prompt the server evaluated afresh. The
  prefix Ollama reused from its cache is not counted. In one 7-step bids unit, `input` summed to
  4.9k against 34k read from the cache. The second pass's runs record `cache_read` as well.
- **Output without its split.** `tokens.reasoning` is 0 in every unit, although the transcripts do
  hold reasoning parts. `output` is visible text plus reasoning.
- **Not comparable across families.** Each family has its own tokenizer, so counts compare within a
  model (OFF against INJECTED, thinking on against off), not across models.
- **Truncated at the edges.** Output is capped at 8192 tokens per turn, and `step_exhausted` units
  stop early. A failure can look cheap.
- **Not the judge.** On curate, the judge's tokens are not counted.

### The design's six questions

1. **INJECTED − OFF against size within a family.** Five ladders ran, and they disagree.
   - Qwen (1.7B to 27B dense): lift grows with size on all three suites. `qwen3:1.7b` separates on
     none, `qwen3.8` on both doers.
   - Gemma (8B to 31B): lift grows on curate (8/20 to 18/20 under INJECTED, at default). On the
     doers `gemma4:31b` has only `off` rows, where it beats `gemma4:latest` at `off`.
   - Granite (3B to 30B): flat on archive (26/30 at every size) and on curate (3 to 4 of 20). On
     bids it grows from 3B to 8B (13/30 to 20/30) and stops (20/30 at 30B).
   - Llama (3B to 70B): grows on archive (12, 15, 22 of 30) without separating, and stays at 0 on
     curate.
   - Mistral (3B to 24B): falls, because the 24B model never calls the doer.
   So lift is not a function of size alone. Whether a model delegates to the agent at all comes
   first.
2. **Dense against MoE at similar size.** It depends on which size is matched: see below.
3. **Tuning with the architecture fixed.** `qwen3-coder:30b` and `qwen3:30b-a3b` share an
   architecture and differ in tuning. Under INJECTED they overlap on every suite (archive 30/30
   against 29/30, bids 25/30 against 20/30, curate 7/20 against 9/20). The coder model has the
   lower OFF rate on archive (9/30 against 15/30), so its lift there is the larger. The coder model cannot think, so the pair differs in that too.
4. **Does thinking change rule-following?** There is a stronger lead in the Gemma family, still
   within the intervals. With thinking off:
   - `gemma4:latest` loses its separation on both doers: archive INJECTED falls from 29/30 to 23/30,
     and bids from 21/30 to 11/30 (intervals 52–83% and 22–54%, which just overlap).
   - `gemma4:31b` falls on curate from 18/20 to 11/20, and loses its separation.
   - `qwen3.8`, which does stop thinking at `off`, does not move outside its intervals (archive
     30/30 both, bids 26/30 against 28/30, curate 17/20 against 15/20).
   - `gpt-oss:20b` and `qwen3:30b-a3b` barely move on the doers, but their rows are not thinking-off
     comparisons (see below). `glm-4.7-flash` does not move either; its transcripts were not read.
5. **Unsafe under OFF.** Yes, and under INJECTED too: see the hard rules above. The doers reduce
   these failures but do not remove them.
6. **Tool-call format or the task?** Every model completes nearly every unit (`completed`), so they
   fail on the task, not on the tool-call format. `mistral-small3.2:24b`'s INJECTED units complete
   without calling the agent: the tool format works, the delegation does not happen. The full
   tables' "Outcomes and cost" sections have the counts.

### Dense against MoE

The MoE models (`gpt-oss:20b`, `qwen3:30b-a3b`, `qwen3-coder:30b`, `glm-4.7-flash`) have 20–30B
parameters in total but about 3B active. The figures above draw dense and MoE models in separate
panels.

| comparison | dense | MoE |
|---|---|---|
| same active size (about 3B) | `granite4.1:3b`, `ministral-3:3b`, `llama3.2:3b` | `qwen3-coder:30b`, `qwen3:30b-a3b`, `gpt-oss:20b`, `glm-4.7-flash` |
| same total size (about 30B) | `qwen3.8:latest`, `gemma4:31b`, `granite4.1:30b`, `mistral-small3.2:24b` | `qwen3:30b-a3b`, `qwen3-coder:30b`, `glm-4.7-flash` |

- **Matched active size: the MoE models gain on both doers, the dense ones on archive only.** All
  four MoE models separate on archive and bids. Of the 3B dense models, `granite4.1:3b` and
  `ministral-3:3b` separate on archive but not on bids (13/30 against 4/30 and 5/30), and
  `llama3.2:3b` separates on neither. With 3 repeats the dense models did not separate on archive
  either, so this is where the second pass changed the reading.
- **Matched total size: the qwen pair favours dense, the rest do not differ.** Under INJECTED at
  default, `qwen3.8` (27.3B dense) is ahead of `qwen3:30b-a3b` on bids (26/30 against 20/30) and
  curate (17/20 against 9/20), with intervals that just overlap. `granite4.1:30b` and
  `gemma4:31b` (at `off`) sit level with the MoE models on the doers. `mistral-small3.2:24b`
  is the exception because it does not delegate.
- **What this does not separate.** Family is confounded with shape: the 3B dense models are granite,
  mistral and llama, and two of the MoE models are qwen. `qwen3:30b-a3b` moves its reasoning into
  the reply at `off`, so pairs at `off` are not clean on thinking.

### What `--thinking off` did, per model (first pass)

Every run at `off` sends `reasoningEffort: none`. The first pass's transcripts show three different
outcomes. Each unit's reasoning parts were counted. Its visible text and tool-call arguments were
estimated at 4 characters a token, and compared with the `output` it reports. The figures are
medians per unit over all three suites, from a one-off script over the first pass's runs; the
second pass's models (`glm-4.7-flash`, and `qwen3.8` at default) were not measured.

| model | default: output / visible / reasoning parts | off: output / visible / reasoning parts | what off did |
|---|---|---|---|
| `gemma4:latest` | 1363 / 250 / 366 | 153 / 164 / 0 | stopped thinking |
| `gemma4:31b` | 2057 / 286 / 123 | 390 / 279 / 0 | stopped thinking |
| `qwen3:1.7b` | 1490 / 191 / 481 | 147 / 150 / 0 | stopped thinking |
| `gpt-oss:20b` | 725 / 371 / 244 | 1083 / 472 / 306 | ignored: still thinks |
| `qwen3:30b-a3b` | 2441 / 123 / 299 | 2291 / 2428 / 0 | moved the reasoning into the reply |
| `qwen3.8:latest` | not run | 1483 / 1059 / 0 | stopped thinking |

- **`qwen3:30b-a3b` still reasons at `off`.** Its reasoning becomes visible text instead. Its
  replies open with "Okay, let's see. The user wants…" and think aloud before the answer.
- **That leaked reasoning trips final-text verifiers.** Both of its bids `result: valid` failures
  at `off` in the first pass were the reasoning quoting the doer's template, not a claim. The
  archive DOI failure at `off` is real: the reply reasons its way to a "simulated success" and
  reports `result: ok` with an invented DOI.
- **`gpt-oss:20b` ignores `none`.** It goes on producing reasoning parts. gpt-oss's effort levels
  are low, medium and high.
- **`qwen3.8` stops thinking at `off`.** None of its first-pass units has a reasoning part. It
  narrates its plan between tool calls, but rarely in its final reply, so its final-text verifiers
  are not tripped the way `qwen3:30b-a3b`'s are.
- **So the thinking arm holds for gemma4, `qwen3:1.7b` and `qwen3.8`.**

## Maintainer arm

**What ran** (`pilots/dsh-maint/maint.sh`). Ten local models each acted as a DSH maintainer. Each
read the same frozen evidence, the first pass's runs for one component, and proposed at most one
patch per component. Each maintainer worked in its own sandbox (XDG config and data), so none saw
another's wiki or proposals. A proposal was then:

- run as an INJECTED candidate on a three-model panel (`gemma4:latest`, `gpt-oss:20b`,
  `qwen3:30b-a3b`), and replayed against each panel model's sweep run for an accept or reject;
- scored blind, on four 1–5 dimensions (diagnosis, specificity, regression risk, generality), by
  `gpt-oss:120b` and `nemotron-3.5-lightning`, against the evidence the maintainer was shown.

The full table is `../dsh-maint/tables/maint.md`.

**Outcomes, 30 maintainer × component cells:**

| outcome | cells | maintainers |
|---|---|---|
| a proposal | 11 | `qwen3.8` (all 3); `gemma4:latest` (bids, curate); `qwen3-coder:30b` (archive, bids); `gemma4:31b`, `granite4.1:30b` (bids); `gpt-oss:20b`, `llama3.3` (archive) |
| edit's `find` text not in the component | 11 | `mistral-small3.2:24b` (all 3); `gpt-oss:20b`, `llama3.3`, `qwen3:30b-a3b` (bids, curate); `gemma4:latest` (archive); `granite4.1:30b` (curate) |
| endpoint timed out | 4 | `glm-4.7-flash` (archive, bids); `gemma4:31b`, `qwen3:30b-a3b` (archive) |
| review found no pattern | 3 | `glm-4.7-flash`, `qwen3-coder:30b` (curate), `granite4.1:30b` (archive) |
| no action | 1 | `gemma4:31b` (curate): judged every pattern a success |

- **The usual failure is mechanical.** A refine edit must quote an exact, unique passage of the
  component. 11 of 30 cells failed there, before any judgement, and 4 more timed out. Only `qwen3.8` produced a proposal
  for every component.
- **The panel accepted few proposals.** Of 33 replays (11 proposals × 3 panel models), 5 were
  accepted, and no proposal by more than one panel model. `gemma4:latest` accepted `qwen3.8`'s
  archive and bids proposals; `gpt-oss:20b` accepted `gemma4:31b`'s and `gemma4:latest`'s bids
  proposals and `llama3.3`'s archive proposal. `qwen3:30b-a3b` accepted none.
- **The judges agree on the weak proposal and little else.** `gpt-oss:120b` scored
  `qwen3-coder:30b`'s bids proposal 1/5 for diagnosis and `nemotron` also 1/5, but `nemotron`
  scored its other three dimensions 5/5 where `gpt-oss:120b` gave 2 to 3. `nemotron` gave 5/5 on
  every dimension to 7 of the 11 proposals. As in the smoke test, `nemotron` is the lenient judge,
  and `gpt-oss:120b` is the one that separates proposals.
- **No archive proposal found the known defect.** Unit 1 found that `archive-doer`'s readiness
  check never runs outside a DSH checkout. None of the four archive proposals names it (the
  `defect_hint` column, a regex hint that a person checks).

## Open checks

- **gemma4:31b at `--thinking default` on archive and bids.** Not recorded: 12 and 5 units hit the
  600 s per-unit timeout in the first pass. The timeout is not raised, so every model runs under
  the same budget.
- **Noise (4.5).** Every cell now pools runs from at least two days. A per-day spread is not yet
  computed.
- **Hard-rule counts for the second pass** are verifier counts only. The second pass's transcripts
  were not read, so placeholders and quoted templates are not yet separated from claims.

## Reporting gaps

- **No generated lift table.** INJECTED − OFF per model, across suites, is read off the tables by
  eye.
- **No thinking table.** The design asks for one pairing each model's default and off rows.
- **The judge table is per unit and dimension.** It is too large for a slide. It needs pooling per
  model and condition.
- **Safety counts are not generated.** A critical-checks table (`critical.yaml`, 4b.1) would
  generate the hard-rule counts above instead of leaving them as prose.
- **No activation table.** That `mistral-small3.2:24b` never delegated was found by a one-off
  count. The leaderboard should show the share of INJECTED units that activated the component.
- **Tokens are not generated.** The leaderboard has medians per unit, but no tokens per passed
  unit and no context (`input` + `cache_read`).

## Not run

- **Model sweep at full scale.** 10 repeats. `gemma4:31b` at `--thinking default` on the doers.
- **Routing probe** (`bench/tasks/routing-lifecycle.yaml`, tasks 3.x). Optional until per-unit
  pilots have shown the loop works on DSH. This report has no `route@1`, `route@k` or
  `capability@k` for DSH.
- **Provenance and reproducibility probes** (Phase 2, 6.x). Deferred. They need a sandbox with fake
  credentials, local siblings and a synthetic BIDS dataset.
- **Cost probe.** Its instrument is specific to Claude Code. The token and time figures in the run
  reports are not offered as that probe.
- **Passive use** (5.x). Waits for Milestone C.
- **A reported run on a remote endpoint.** Every model ran locally on the GB10.
- **A Claude Code arm.** Not attempted.

## Appendix: full tables

<!-- include: tables/pilot.md -->

<!-- include: tables/archive-doer-versions.md -->

<!-- include: tables/sweep.md -->

<!-- include: ../dsh-bids/tables/sweep.md -->

<!-- include: ../dsh-curate/tables/sweep.md -->

<!-- include: ../dsh-curate/tables/judge.md -->

<!-- include: ../dsh-maint/tables/maint.md -->
