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
sibling studies, `../dsh-bids` and `../dsh-curate` (`runs/`, listed in each `findings.toml`), by `wikiskill findings tables` and `bin/figures`, and the documents are built
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

## Model sweep (preliminary)

**Status.** This is a draft for a proof of concept. The sweep is smaller than the design's: 3
repeats per task, not 10, and seven models of the eighteen in the catalogue. Intervals are
therefore about ±20 points at 50%, and most places in each ranking are not findings. A fuller
sweep is left for a later report.

**What ran.** Three DSH components, each its own suite and study, on the same models:

| suite | component | tasks | decided by |
|---|---|---|---|
| `pilots/archive-doer/suite.yaml` | `archive/archive-doer` (agent) | 6 | verifiers |
| `pilots/bids-doer/suite.yaml` | `bids/bids-doer` (agent) | 6 | verifiers |
| `pilots/gen-data-dict/suite.yaml` | `curate/gen-data-dict` (skill) | 4 | verifiers and a judge (`gpt-oss:120b`) |

- **Conditions.** OFF is the control, and INJECTED loads the component directly. n = 18 per cell
  for archive and bids, and 12 for curate.
- **Models.** `qwen3:1.7b`, `llama3.2:3b`, `gemma4:latest` (8B), `granite4.1:8b`, `gpt-oss:20b`,
  `qwen3:30b-a3b` and `gemma4:31b`. They run in that order, smallest first, by
  `pilots/dsh-sweep/sweep.sh`.
- **Thinking.** Every model runs at `--thinking default`. The models the server says can think also
  run at `--thinking off`: the qwen3 models, gemma4 and gpt-oss. The tables list the two settings as
  separate entrants.
- **Left out.** `llama3.3` was left out for time, and `gpt-oss:120b` because it is curate's judge.
  The archive suite's hash changed when the `plugins` link was added, so Unit 1's v1 run does not
  pool in.

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

### What the sweep shows so far

- **The doers are worth something from about 8B up.** At `--thinking default`, INJECTED beats OFF
  with intervals that do not overlap for every model of 8B or more on bids. On archive the same
  holds for every such model except `granite4.1:8b` (16/18 against 9/18, which just overlap).
  Below 8B (`qwen3:1.7b`, `llama3.2:3b`), the two conditions overlap on every suite.
- **On curate the skill helps only the largest model.** Only `gemma4:31b` at
  `--thinking default` separates. With thinking off it no longer does (7/12 against 3/12). `gpt-oss:20b`
  does better without the skill (OFF 5/12, INJECTED 2/12), within the intervals.
- **Archive is at its ceiling.** Six entrants pass 16 to 18 of 18 under INJECTED, so the suite no
  longer separates them. The design's ceiling rule (4.7) calls for harder tasks.
- **Curate is hard for everyone.** Under INJECTED, only `gemma4:31b` passes most units. Most models
  are at 0–2 of 12 under both conditions.
- **The doers' hard rules do not always hold under INJECTED.** These counts come from per-verifier
  results in the bundled `results.jsonl`, not from a generated table:
  - `qwen3:30b-a3b` (both thinking settings) and `llama3.2:3b` gave a structured `result: ok` with
    an invented `10.5281/zenodo.1234567`, while the archive was unreachable or unset.
  - On bids, five models reported `result: valid` with no validator on PATH.
  - `gemma4:31b` (thinking off) edited the dataset in all 3 `validate-and-fix` units, against the
    doer's read-only rule.
- **The DOI verifier is too strict.** Some of its failures are labelled placeholders in prose
  ("e.g. `10.5281/zenodo.1234567`"), not claims. The verifier counts these the same as a claimed
  DOI, so the archive DOI counts overstate fabrication. Unit 1's statement that no reply contained
  a DOI holds only for its two models.

### Tokens per unit (heavily qualified)

Each unit records `tokens` summed over every model call it made, child sessions included. The full
tables' "Outcomes and cost" sections give the median input and output per model and condition.
The figures below are output tokens, computed from the bundled `results.jsonl` with a one-off
script. They are not a generated table. "Per pass" is a cell's total output divided by its passed
units.

- **INJECTED usually costs more per unit, and less per pass.** The doer adds steps, but passes rise
  faster:
  - On bids, output per pass for `granite4.1:8b` falls from about 9.2k (OFF) to 0.9k (INJECTED).
  - For `gemma4:latest` on bids it falls from 8.3k to 3.5k.
  - Per unit, `qwen3:30b-a3b` on bids rises from a median of 1.7k to 4.4k.
- **The doer can make a model cheaper per unit as well.** On archive, `gemma4:31b` (thinking off)
  falls from a median of 1.6k to 0.2k per unit, and passes all 18.
- **Thinking off cuts output where it takes effect.** On archive INJECTED, `gemma4:latest` falls
  from a median of 1.6k to 0.3k. On bids INJECTED, `qwen3:30b-a3b` does not move (4.4k against
  4.4k), which is the same signal as the open check below.
- **`qwen3:30b-a3b` is the most verbose model.** Its median is 6.6k output per unit on curate
  INJECTED, against 3.2k for `gemma4:31b`, which passes twice as often.

What these numbers are not:
- **Not the context processed.** `input` counts only the prompt the server evaluated afresh. The
  prefix Ollama reused from its cache is not counted. In one 7-step bids unit, `input` summed to
  4.9k against 34k read from the cache. So `input` varies with how warm the cache was, and is not
  reported here. From this change on, runs also record `cache_read`, but these runs predate it.
- **Output without its split.** `reasoning` is 0 in every unit: Ollama's OpenAI-compatible endpoint
  does not report it separately. `output` is visible text plus any reasoning, in unknown
  proportion.
- **Not comparable across families.** Each family has its own tokenizer, so counts compare within a
  model (OFF against INJECTED, thinking on against off), not across models.
- **Truncated at the edges.** Output is capped at 8192 tokens per turn, and `step_exhausted` units
  stop early. A failure can look cheap.
- **Not the judge.** On curate, the judge's tokens are not counted.
- **Small n.** These are medians of 18 units per cell (12 on curate), from one run each.

### The design's six questions

1. **INJECTED − OFF against size within a family.** Only two ladders ran. Lift grows with size in
   the Qwen ladder (1.7B to 30B) on archive and bids. It also grows in the Gemma ladder (8B to 31B)
   on all three suites. That ladder is compared at `--thinking off` on archive and bids, the only
   setting `gemma4:31b` has there. Two ladders are not a finding.
2. **Dense against MoE at similar size.** Pending: see below.
3. **Tuning with the architecture fixed.** Pending: `qwen3-coder:30b` against `qwen3:30b-a3b`.
4. **Does thinking change rule-following?** There is a lead in the Gemma family, not yet a
   finding.
   - With thinking off, `gemma4:latest` loses its separation on both doers: archive INJECTED falls
     from 17/18 to 14/18, and bids from 12/18 to 6/18.
   - `gemma4:31b` loses its separation on curate: INJECTED falls from 10/12 to 7/12.
   - `gpt-oss:20b` loses separation on bids (12/18 to 10/18).
   - The other pairs barely move. `--thinking off` may not take effect on every model (see the
     open checks).
5. **Unsafe under OFF.** Yes, and under INJECTED too: see the hard rules above. The doers reduce
   these failures but do not remove them.
6. **Tool-call format or the task?** The small models complete nearly every unit (`completed`), so
   they fail on the task, not on the tool-call format. The exception is `qwen3:30b-a3b` on bids
   OFF: 5 of its 18 units are `permission_blocked`. The full tables' "Outcomes and cost" sections
   have the counts.

### Dense against MoE (running)

The MoE models (`gpt-oss:20b`, `qwen3:30b-a3b`) have 20–30B parameters in total but about 3B
active. There is no small MoE model to compare, so four more models are queued to test both
readings of "similar size":
- **Matched active parameters.** `granite4.1:3b` and `ministral-3:3b`, both dense, against the MoE
  models.
- **Matched total parameters.** `qwen3.8:latest` (27B, dense) at `--thinking off`, against
  `qwen3:30b-a3b`.
- **Tuning.** `qwen3-coder:30b` (MoE) against `qwen3:30b-a3b`, for question 3.

Their rows will appear in the tables above once they are recorded.

### Open checks

- **Is `--thinking off` effective?** Every run sends `reasoningEffort: none`. `qwen3:1.7b`'s output
  falls about fourteen-fold on bids, but `qwen3:30b-a3b`'s barely changes, and `gpt-oss:20b`'s
  rises. gpt-oss may accept only low, medium and high effort. Transcripts carry no reasoning parts,
  and `tokens.reasoning` is 0 in every unit, so reasoning cannot be separated from output. To
  settle it, call the server directly with `reasoning_effort: none` on each model.
- **gemma4:31b at `--thinking default` on archive and bids.** Not recorded: 12 and 5 units hit the
  600 s per-unit timeout. The timeout is not raised, so every model runs under the same budget.
- **Noise (4.5).** No second-day run has been made, so the run-to-run spread is unknown.

### Reporting gaps

- **No generated lift table.** INJECTED − OFF per model, across suites, is read off the tables by
  eye.
- **No thinking table.** The design asks for one pairing each model's default and off rows.
- **The judge table is per unit and dimension.** It is too large for a slide. It needs pooling per
  model and condition.
- **Safety counts are not generated.** A critical-checks table (`critical.yaml`, 4b.1) would
  generate the hard-rule counts above instead of leaving them as prose.
- **Tokens are not generated.** The leaderboard has medians per unit, but no tokens per passed
  unit and no context (`input` + `cache_read`). The token figures above come from a one-off script.
- **The rates figure is portrait.** It is too tall for a 16:9 slide once there are 11 or more
  entrants.

## Not run

- **Model sweep at full scale.** 10 repeats, and the catalogue's other models: `llama3.3`, the
  larger granite and mistral models, `glm-4.7-flash` and `nemotron-3.5-lightning`.
- **Routing probe** (`bench/tasks/routing-lifecycle.yaml`, tasks 3.x). Optional until per-unit
  pilots have shown the loop works on DSH. This report has no `route@1`, `route@k` or
  `capability@k` for DSH.
- **Provenance and reproducibility probes** (Phase 2, 6.x). Deferred. They need a sandbox with fake
  credentials, local siblings and a synthetic BIDS dataset.
- **Cost probe.** Its instrument is specific to Claude Code. The token and time figures in the run
  reports are not offered as that probe.
- **Passive use** (5.x). Waits for Milestone C.
- **A reported run on a remote endpoint.** Both models ran locally. They are mid-size open models
  from two families, and the results above are the pilot's reported run for this unit, not smoke
  figures. No judge was used, because every task is decided by verifiers.
- **A Claude Code arm.** Not attempted for this unit.

## Appendix: full tables

<!-- include: tables/pilot.md -->

<!-- include: tables/archive-doer-versions.md -->

<!-- include: tables/sweep.md -->

<!-- include: ../dsh-bids/tables/sweep.md -->

<!-- include: ../dsh-curate/tables/sweep.md -->

<!-- include: ../dsh-curate/tables/judge.md -->
