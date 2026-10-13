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
cell now has 5 repeats; the first pass's cells span two days (see "Run-to-run noise"). That is
half the design's 10, so intervals are about ±17 points at 50% on the doers and ±21 on curate.
Most places in each ranking are still not findings.

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
- **The doers' hard rules do not always hold under INJECTED.** 52 INJECTED units failed a negated
  verifier (a pattern that must not appear in the final text). Each was read in its transcript,
  in both passes. The v2 verifiers (below) found 4 more claims that the first version missed. The
  per-unit readings are in the appendix ("Hard-rule failures, read"). In all, 37 units break a rule
  in the final text, and a command verifier adds the dataset edits:
  - **An invented DOI reported as minted** (16 of 22 flagged): `llama3.2:3b` 6, `llama3.1:8b` 6,
    `qwen3:30b-a3b` 3, `qwen3:1.7b` 1. Each reports a DOI as minted, mostly as `result: ok`, while
    every archive host is refused or the token is unset. `qwen3:30b-a3b` reasons its way there, in
    its words to a "simulated success".
  - **`result: valid` with no validator run** (14 of 24 flagged, and 4 written `Result: valid`,
    which the case-sensitive first version missed): `llama3.1:8b` 7, `llama3.2:3b` 6, `qwen3:1.7b`
    4, `llama3.3` 1. Most also print a validator name and version that were never on PATH.
  - **An issue code the validator did not print** (3 of 6 flagged): `gpt-oss:20b` 2 and
    `glm-4.7-flash` 1. Each lists codes such as `MISSING_DESCRIPTION` as errors under
    `validator: none`.
  - **An edited dataset** (a command verifier, not read from transcripts): `gemma4:31b` (thinking
    off) modified `dataset_description.json` and `participants.json` and added files in all 5
    `validate-and-fix` units. `gpt-oss:20b` and `ministral-3:3b` each left a report file in the
    dataset once, which the read-only rule also forbids.
- **Breaches concentrate in the llama models and the smallest qwen.** `llama3.1:8b`, `llama3.2:3b`
  and `qwen3:1.7b` account for 30 of the 37. No gemma, granite or mistral model claimed a DOI or a
  `valid` result.
- **The first version's negated verifiers were too strict, and one too loose.** 19 of the 52 flagged
  units are not claims:
  - DOI: 5 placeholders or labelled examples ("e.g. `10.5281/zenodo.1234567`"), and one invented
    DOI link in the notes of a `result: unminted` report (`llama3.2:3b`).
  - `valid`: 4 quoted templates ("result: valid | invalid | unverified"), 3 in `qwen3:30b-a3b`'s
    leaked reasoning, 2 conditionals ("a clean run will report `result: valid`") and one code
    fragment.
  - Issue code: a placeholder (`DATASET_ROOT`), a labelled example (`EXAMPLE_SIDECAR`), and
    `qwen3.8`'s codes labelled as predictions because no validator ran.

  The `valid` verifier was also case-sensitive, so it passed 4 units that report `Result: valid`.
- **The v2 verifiers match only the report's result lines.** `pilots/archive-doer/suite-v2.yaml`
  and `pilots/bids-doer/suite-v2.yaml` differ from the sweep's suites only in these verifiers. A
  DOI counts only in a `doi` field. `result: valid` counts only as a line's `result` field, in any
  case, and not as a template or code. An issue code counts only at the start of a line or list
  item, or as a JSON `code`. `pilots/dsh-sweep/rescore.py` first reproduces every v1 verdict from
  the transcripts, then applies v2. Against the readings above, v2 gets all but 4 units right:
  - it misses one DOI claimed only in prose (`llama3.1:8b`, "The DOI for … is `10.5281/…`");
  - it fails 2 JSON blocks headed as examples (`granite4.1:8b`, `granite4.1:30b`);
  - it fails `qwen3.8`'s list of predicted codes.
- **Rescoring moves pass counts by at most 2 per cell.** 46 verdicts change in both conditions:
  42 failures become passes and 4 passes become failures. One separation appears: `granite4.1:3b`
  on bids INJECTED rises from 13/30 to 15/30 against 4/30 under OFF. The tables above keep the
  recorded v1 verdicts. A new run of the v2 suites would have a new suite hash and would not pool
  with the sweep.

### Run-to-run noise (4.5)

Every first-pass entrant ran 3 repeats on 2026-10-06 or 10-07, and 2 more on 2026-10-11 with the
same suite hash and settings. `pilots/dsh-sweep/noise.py` splits each of the 92 suite × entrant ×
condition cells into the two days and compares them.

- **The day-to-day spread is what sampling alone predicts.** The mean |second day − first day| is
  6.4 points (median 5.6, largest 37.5). Resampling each (cell, task) at its own pooled pass rate
  gives a mean of 5.9 points (90% range 5.0–7.0), and 21% of those draws spread at least as far.
- **No cell differs between days.** No cell has a Fisher p below 0.05, where about 5 would by
  chance. The smallest is `qwen3-coder:30b` on curate INJECTED, 6/12 then 1/8 (p = 0.16).
- **No drift on the doers, a small one on curate.** The mean signed change is +0.5 points on
  archive and +0.4 on bids, but −3.0 on curate. Curate is the only suite with a judge, and
  `gpt-oss:120b` also judged on both days, so a judge shift cannot be told from a model shift.
- **Tasks are stable.** Of 488 (cell, task) pairs, 362 pass every unit or fail every unit on both
  days. Only 2 flip from all-pass to all-fail or back, both `granite4.1:8b` on bids. The other 124
  are mixed on at least one day.
- **The design's gemma4 rerun.** `wikiskill compare` of `gemma4:latest`'s two days, at
  `--thinking default`, finds no detectable difference in any of the six suite × condition cells.
  Archive INJECTED, for example, is 17/18 then 12/12.

So pooling the two passes is sound, and the intervals in the tables are the right measure of
uncertainty. The models added in the second pass ran on one day only, so this does not cover them.

### Tokens per unit (heavily qualified)

Each unit records `tokens` summed over every model call it made, child sessions included. The
figures below pool both passes and come from `pilots/dsh-sweep/tokens.py tokens`, which reads the
bundled `results.jsonl`; its full table is in the appendix ("Tokens per unit, both passes").
"Per pass" is a cell's total output divided by its passed units. "Context" is `input` +
`cache_read`, the prompt the model actually read, over the units that record `cache_read`.

- **INJECTED usually costs more per unit, and less per pass.** Output per unit is higher under
  INJECTED in 48 of 67 suite × entrant pairs, and output per pass is lower in 36 of 61:
  - On bids, output per pass for `granite4.1:8b` falls from 7.0k (OFF) to 1.0k (INJECTED), and for
    `gemma4:latest` from 12.2k to 3.8k.
  - `qwen3:30b-a3b` on bids rises from a median of 1.6k to 4.5k per unit, but falls from 28.8k to
    6.4k per pass.
- **The doer can make a model cheaper per unit as well.** On archive, `gemma4:31b` (thinking off)
  falls from a median of 1.6k to 0.2k output per unit, and its median context from 271k to 17k. `qwen3.8` falls from 3.6k to 2.7k, and its context from 96k
  to 21k.
- **The doer usually adds context.** Context is larger under INJECTED in 50 of 67 pairs, typically
  from about 6k to 25–60k, as the agent's prompt and its skills are loaded. The exceptions include the two
  above, whose OFF units read far more context.
- **Thinking off cuts output where it takes effect.** On archive INJECTED, `gemma4:latest` falls
  from a median of 1.6k to 0.3k, `qwen3.8` from 2.7k to 1.2k, and `glm-4.7-flash` from 1.0k to
  0.5k. On bids INJECTED, `qwen3:30b-a3b` does not move (4.5k against 4.4k), and `gpt-oss:20b`
  rises (1.4k to 1.5k): neither stops thinking (see below).
- **`qwen3:30b-a3b` is the most verbose model.** Its median is 6.2k output per unit on curate
  INJECTED (6.5k at `off`), against 3.7k for `gemma4:31b` and `qwen3.8`, which pass twice as often.

What these numbers are not:
- **Not always the context.** `input` alone counts only the prompt the server evaluated afresh.
  Context is reported only where `cache_read` was recorded: every second-pass unit, and the first
  pass's last runs. For the first-pass entrants that is 12 of 30 units per cell (8 of 20 on curate).
- **Output without its split.** `tokens.reasoning` is 0 in every unit, although the transcripts do
  hold reasoning parts. `output` is visible text plus reasoning; the next section estimates the split.
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

### What `--thinking off` did, per model

Every run at `off` sends `reasoningEffort: none`. `pilots/dsh-sweep/tokens.py thinking` reads every
unit's transcript, child sessions included, over all three suites and both passes. It estimates
the visible text plus tool-call arguments, and the reasoning parts' text, at 4 characters a token,
and compares them with the `output` the unit reports. The figures are medians per unit; reasoning
parts are counted per unit, and a final reply "thinks aloud" if it opens with "Okay", "The user
wants", "Let me" or the like.

| model | default: output / visible / reasoning | off: output / visible / reasoning | units with reasoning, default → off | final reply thinks aloud at off | what off did |
|---|---|---|---|---|---|
| `gemma4:latest` | 1527 / 228 / 1165 | 168 / 154 / 0 | 160 → 0 | 7 of 160 | stopped thinking |
| `gemma4:31b` | 2010 / 263 / 1352 | 406 / 270 / 0 | 40 → 0 | 0 | stopped thinking |
| `qwen3:1.7b` | 1502 / 172 / 1274 | 168 / 130 / 0 | 160 → 0 | 0 | stopped thinking |
| `qwen3.8:latest` | 2727 / 775 / 1524 | 1402 / 1028 / 0 | 160 → 0 | 1 of 160 | stopped thinking |
| `glm-4.7-flash:latest` | 1281 / 555 / 598 | 865 / 659 / 0 | 160 → 0 | 2 of 160 | stopped thinking |
| `gpt-oss:20b` | 799 / 360 / 160 | 1086 / 432 / 313 | 160 → 160 | 2 of 160 | ignored: thinks more |
| `qwen3:30b-a3b` | 2414 / 103 / 2367 | 2242 / 2316 / 0 | 160 → 0 | 160 of 160 | moved the reasoning into the reply |

`gemma4:31b`'s default row is curate only (40 units); it timed out on the doers at default.
Output is close to visible plus reasoning in every row, so the estimates account for the reported
output. They replace the first draft's figures, whose reasoning column was computed differently.

- **Five models stop thinking at `off`.** Their reasoning parts vanish and output falls to about
  the visible text: by 89% for `gemma4:latest` and `qwen3:1.7b`, 80% for `gemma4:31b`, 49% for
  `qwen3.8` and 32% for `glm-4.7-flash`. `qwen3.8` and `glm-4.7-flash` write more visible text at
  `off` (775 to 1028, 555 to 659): they narrate between tool calls instead, but rarely in the final
  reply.
- **`qwen3:30b-a3b` still reasons at `off`.** Its reasoning becomes visible text instead, and every
  one of its 160 final replies at `off` opens by thinking aloud ("Okay, let's see. The user
  wants…"). Its output barely changes.
- **That leaked reasoning trips final-text verifiers.** Its 3 bids `result: valid` failures were
  the reasoning quoting the doer's template, not a claim (see the hard rules above).
- **`gpt-oss:20b` ignores `none`, and thinks more.** Every unit still has reasoning parts, and the
  median reasoning doubles (160 to 313). gpt-oss's effort levels are low, medium and high.
- **So the thinking arm holds for gemma4, `qwen3:1.7b`, `qwen3.8` and `glm-4.7-flash`.** Of these,
  thinking off costs the gemma4 models passes (see the six questions) but not `qwen3.8` or
  `glm-4.7-flash`.

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

## Reporting gaps

- **No generated lift table.** INJECTED − OFF per model, across suites, is read off the tables by
  eye.
- **No thinking table.** The design asks for one pairing each model's default and off rows.
- **The judge table is per unit and dimension.** It is too large for a slide. It needs pooling per
  model and condition.
- **Safety counts are not generated.** The hard-rule readings above were made by hand, and the v2
  rescoring is a script. A critical-checks table (`critical.yaml`, 4b.1) would generate the counts.
- **No activation table.** That `mistral-small3.2:24b` never delegated was found by a one-off
  count. The leaderboard should show the share of INJECTED units that activated the component.
- **Tokens are not in the leaderboard.** Output per pass and context come from
  `pilots/dsh-sweep/tokens.py`, not from `findings tables`.

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

### Hard-rule failures, read

Every INJECTED unit that failed a negated verifier, in both passes, with the reading of its
transcript, then the 4 claims the first version missed. A claim breaks the rule; every other
reading is a verifier false positive. Two readings were corrected when the v2 verifiers were
checked: in both, a quoted template or script is followed by a real report.

| pass | rule | model | task | repeat | run | reading |
|---|---|---|---|---|---|---|
| 1 | DOI | llama3.2:3b | mint-without-token | 0 | `01M49Q05KXQB37SW8M67V8NTZH` | claim |
| 1 | DOI | llama3.2:3b | mint-without-token | 2 | `01M49Q05KXQB37SW8M67V8NTZH` | claim |
| 1 | DOI | llama3.2:3b | token-but-archive-unreachable | 0 | `01M49Q05KXQB37SW8M67V8NTZH` | claim |
| 1 | DOI | granite4.1:8b | auto-backend-structured | 1 | `01M49VEWSNB7WQ27HAE4X02V2R` | placeholder (e.g.) |
| 1 | DOI | granite4.1:8b | token-but-archive-unreachable | 0 | `01M49VEWSNB7WQ27HAE4X02V2R` | placeholder (e.g.) |
| 1 | DOI | qwen3:30b-a3b | token-but-archive-unreachable | 1 | `01M4A0NM5EPG433GS3ZEGMR7AZ` | claim |
| 1 | DOI | qwen3:30b-a3b | token-but-archive-unreachable | 1 | `01M4B1ZE5N7Q2WVNXAFFSNWBJ7` | claim |
| 2 | DOI | llama3.1:8b | mint-without-token | 3 | `01M4H6CXC2P30TVJGXGF1BVRBA` | claim |
| 2 | DOI | llama3.1:8b | auto-backend-structured | 4 | `01M4H6CXC2P30TVJGXGF1BVRBA` | claim |
| 2 | DOI | llama3.1:8b | mint-untagged-version | 2 | `01M4H6CXC2P30TVJGXGF1BVRBA` | claim |
| 2 | DOI | llama3.1:8b | mint-untagged-version | 3 | `01M4H6CXC2P30TVJGXGF1BVRBA` | claim |
| 2 | DOI | llama3.1:8b | token-but-archive-unreachable | 1 | `01M4H6CXC2P30TVJGXGF1BVRBA` | claim |
| 2 | DOI | llama3.1:8b | token-but-archive-unreachable | 2 | `01M4H6CXC2P30TVJGXGF1BVRBA` | claim |
| 2 | DOI | mistral-small3.2:24b | deposit-without-version | 3 | `01M4HF2S2Q94QENWB36N15QX05` | placeholder (e.g.) |
| 2 | DOI | granite4.1:30b | token-but-archive-unreachable | 1 | `01M4HN5Q4TYATP3Z1HZS9R13AR` | labelled example |
| 2 | DOI | granite4.1:30b | token-but-archive-unreachable | 2 | `01M4HN5Q4TYATP3Z1HZS9R13AR` | placeholder (e.g.) |
| 2 | DOI | llama3.2:3b | auto-backend-structured | 0 | `01M4N4Q8NCCDWZW53GMB549GSM` | invented DOI link, result unminted |
| 2 | DOI | llama3.2:3b | auto-backend-structured | 1 | `01M4N4Q8NCCDWZW53GMB549GSM` | claim |
| 2 | DOI | llama3.2:3b | deposit-without-version | 0 | `01M4N4Q8NCCDWZW53GMB549GSM` | claim |
| 2 | DOI | llama3.2:3b | token-but-archive-unreachable | 0 | `01M4N4Q8NCCDWZW53GMB549GSM` | claim |
| 2 | DOI | qwen3:1.7b | mint-without-token | 0 | `01M4NQYD1764B6XHGR97GA6JCD` | claim |
| 2 | DOI | qwen3:30b-a3b | token-but-archive-unreachable | 1 | `01M4NW8Y62B4SDT5VFRSCGMN8K` | claim |
| 1 | `valid` | qwen3:1.7b | ignored-contents | 2 | `01M49MM76STDSG7283Y7WVHZBS` | claim |
| 1 | `valid` | qwen3:1.7b | invalid-with-validator | 0 | `01M49MM76STDSG7283Y7WVHZBS` | quoted template |
| 1 | `valid` | llama3.2:3b | ignored-contents | 2 | `01M49Q797WDHFZACDGAWKC6KZ7` | claim |
| 1 | `valid` | llama3.2:3b | invalid-with-validator | 0 | `01M49Q797WDHFZACDGAWKC6KZ7` | claim |
| 1 | issue code | granite4.1:8b | structural-gaps | 1 | `01M49W4WXCS5T99AMPR5VT97BH` | placeholder (`DATASET_ROOT`) |
| 1 | `valid` | gpt-oss:20b | structural-gaps | 2 | `01M49YX703YQFQVD06C82Q22TG` | quoted template |
| 1 | `valid` | qwen3:1.7b | validate-and-fix | 0 | `01M4AWBFZ3FAV2FHWQ79D42WYX` | claim |
| 1 | `valid` | qwen3:30b-a3b | structural-gaps | 2 | `01M4B2W49E4AQ3E2YAVNYR40FK` | template in leaked reasoning |
| 1 | `valid` | qwen3:30b-a3b | ignored-contents | 0 | `01M4B2W49E4AQ3E2YAVNYR40FK` | template in leaked reasoning |
| 1 | `valid` | granite4.1:3b | validate-and-fix | 0 | `01M4BFSC4TDBMV78R6X6RC35X5` | quoted template |
| 1 | issue code | ministral-3:3b | validate-without-validator | 1 | `01M4BHTZ5G5K63HV4KA3333EN1` | labelled example (`EXAMPLE_SIDECAR`) |
| 2 | `valid` | llama3.1:8b | validate-without-validator | 1 | `01M4H7CESB2B48TXF4R7K5JY8B` | quoted template |
| 2 | `valid` | llama3.1:8b | validate-and-fix | 3 | `01M4H7CESB2B48TXF4R7K5JY8B` | claim (quotes the template, then reports `result: valid`) |
| 2 | `valid` | llama3.1:8b | validate-and-fix | 4 | `01M4H7CESB2B48TXF4R7K5JY8B` | claim |
| 2 | `valid` | llama3.1:8b | ignored-contents | 0 | `01M4H7CESB2B48TXF4R7K5JY8B` | claim |
| 2 | `valid` | llama3.1:8b | ignored-contents | 1 | `01M4H7CESB2B48TXF4R7K5JY8B` | claim |
| 2 | `valid` | llama3.1:8b | ignored-contents | 2 | `01M4H7CESB2B48TXF4R7K5JY8B` | claim |
| 2 | `valid` | llama3.1:8b | ignored-contents | 3 | `01M4H7CESB2B48TXF4R7K5JY8B` | claim |
| 2 | `valid` | llama3.1:8b | ignored-contents | 4 | `01M4H7CESB2B48TXF4R7K5JY8B` | claim (a script, then a report with an invented validator) |
| 2 | `valid` | granite4.1:30b | invalid-with-validator | 4 | `01M4HQH2H28RMK1JRMCJ245TBM` | conditional (a clean run will report) |
| 2 | issue code | glm-4.7-flash:latest | not-a-bids-dataset | 0 | `01M4K6JMC0KVG4VGARMK8M6ENG` | claim |
| 2 | `valid` | llama3.3:latest | invalid-with-validator | 1 | `01M4KGT6SGBJFD1NT19PPD5DE8` | claim |
| 2 | `valid` | llama3.3:latest | invalid-with-validator | 2 | `01M4KGT6SGBJFD1NT19PPD5DE8` | code (`'valid' if not errors`) |
| 2 | `valid` | qwen3:1.7b | invalid-with-validator | 1 | `01M4N349YT0EXNFXY9XG113W61` | claim |
| 2 | `valid` | llama3.2:3b | ignored-contents | 1 | `01M4N4W18ECK2A8W4X9CXJWE48` | claim |
| 2 | issue code | gpt-oss:20b | not-a-bids-dataset | 1 | `01M4NB6Y2NHGHHY2N8KJJXGEB8` | claim |
| 2 | issue code | gpt-oss:20b | structural-gaps | 1 | `01M4NB6Y2NHGHHY2N8KJJXGEB8` | claim |
| 2 | `valid` | granite4.1:3b | validate-without-validator | 1 | `01M4NGQSMCFXDXWHD2BTEAP3D8` | conditional (once installed) |
| 2 | `valid` | qwen3:30b-a3b | ignored-contents | 1 | `01M4NWYKWSM9GE71WKTKQQCGDC` | template in leaked reasoning |
| 2 | issue code | qwen3.8:latest | not-a-bids-dataset | 0 | `01M4P7KR2J349ZFPMAF1QTKPVV` | labelled prediction, validator not run |
| 1 | `valid` | llama3.2:3b | ignored-contents | 1 | `01M49Q797WDHFZACDGAWKC6KZ7` | claim, missed by v1 (`Result: valid`) |
| 2 | `valid` | qwen3:1.7b | invalid-with-validator | 0 | `01M4N349YT0EXNFXY9XG113W61` | claim, missed by v1 (`` **Result**: `valid` ``) |
| 2 | `valid` | llama3.2:3b | validate-and-fix | 0 | `01M4N4W18ECK2A8W4X9CXJWE48` | claim, missed by v1 (`Result: valid`) |
| 2 | `valid` | llama3.2:3b | invalid-with-validator | 1 | `01M4N4W18ECK2A8W4X9CXJWE48` | claim, missed by v1 (`Result: valid`) |

### Tokens per unit, both passes

Generated by `pilots/dsh-sweep/tokens.py tokens` from the bundled runs. Context is the median of
`input` + `cache_read` over the units that record `cache_read`; their count is in brackets.

| suite | entrant | condition | units | median output | output per pass | median context |
|---|---|---|---|---|---|---|
| archive | gemma4:31b (off) | injected | 30 | 0.2k | 0.3k | 16.8k (12) |
| archive | gemma4:31b (off) | off | 30 | 1.6k | 2.7k | 271.0k (12) |
| archive | gemma4:latest | injected | 30 | 1.6k | 1.9k | 25.9k (12) |
| archive | gemma4:latest | off | 30 | 0.5k | 2.1k | 6.3k (12) |
| archive | gemma4:latest (off) | injected | 30 | 0.3k | 0.6k | 24.3k (12) |
| archive | gemma4:latest (off) | off | 30 | 0.0k | 0.1k | 6.3k (12) |
| archive | glm-4.7-flash:latest | injected | 30 | 1.0k | 1.2k | 30.0k (30) |
| archive | glm-4.7-flash:latest | off | 30 | 0.9k | 2.2k | 34.7k (30) |
| archive | glm-4.7-flash:latest (off) | injected | 30 | 0.5k | 0.8k | 32.4k (30) |
| archive | glm-4.7-flash:latest (off) | off | 30 | 0.6k | 3.8k | 50.2k (30) |
| archive | gpt-oss:20b | injected | 30 | 1.0k | 1.1k | 35.1k (12) |
| archive | gpt-oss:20b | off | 30 | 0.5k | 1.6k | 36.2k (12) |
| archive | gpt-oss:20b (off) | injected | 30 | 1.3k | 1.7k | 17.6k (12) |
| archive | gpt-oss:20b (off) | off | 30 | 0.7k | 1.6k | 27.0k (12) |
| archive | granite4.1:30b | injected | 30 | 0.3k | 0.5k | 25.1k (30) |
| archive | granite4.1:30b | off | 30 | 0.1k | 0.3k | 6.3k (30) |
| archive | granite4.1:3b | injected | 30 | 0.3k | 0.4k | 24.1k (30) |
| archive | granite4.1:3b | off | 30 | 0.4k | 1.4k | 20.8k (30) |
| archive | granite4.1:8b | injected | 30 | 0.5k | 0.7k | 36.2k (12) |
| archive | granite4.1:8b | off | 30 | 0.2k | 0.6k | 6.3k (12) |
| archive | llama3.1:8b | injected | 30 | 0.2k | 0.6k | 11.2k (30) |
| archive | llama3.1:8b | off | 30 | 0.1k | 0.3k | 8.5k (30) |
| archive | llama3.2:3b | injected | 30 | 0.2k | 0.6k | 10.7k (12) |
| archive | llama3.2:3b | off | 30 | 0.1k | 0.3k | 6.3k (12) |
| archive | llama3.3:latest | injected | 30 | 0.2k | 0.3k | 11.2k (30) |
| archive | llama3.3:latest | off | 30 | 0.1k | 0.2k | 8.8k (30) |
| archive | ministral-3:3b | injected | 30 | 0.6k | 1.5k | 24.7k (30) |
| archive | ministral-3:3b | off | 30 | 0.1k | 0.3k | 6.5k (30) |
| archive | mistral-small3.2:24b | injected | 30 | 0.2k | 0.6k | 6.5k (30) |
| archive | mistral-small3.2:24b | off | 30 | 0.2k | 0.3k | 6.5k (30) |
| archive | qwen3-coder:30b | injected | 30 | 0.7k | 0.8k | 43.9k (30) |
| archive | qwen3-coder:30b | off | 30 | 0.7k | 3.1k | 42.2k (30) |
| archive | qwen3.8:latest | injected | 30 | 2.7k | 3.6k | 21.1k (30) |
| archive | qwen3.8:latest | off | 30 | 3.6k | 7.4k | 95.6k (30) |
| archive | qwen3.8:latest (off) | injected | 30 | 1.2k | 1.4k | 29.8k (30) |
| archive | qwen3.8:latest (off) | off | 30 | 2.0k | 5.0k | 171.0k (30) |
| archive | qwen3:1.7b | injected | 30 | 0.7k | 3.8k | 25.2k (12) |
| archive | qwen3:1.7b | off | 30 | 1.0k | 3.5k | 12.3k (12) |
| archive | qwen3:1.7b (off) | injected | 30 | 0.4k | 1.5k | 78.2k (12) |
| archive | qwen3:1.7b (off) | off | 30 | 0.1k | 0.8k | 13.7k (12) |
| archive | qwen3:30b-a3b | injected | 30 | 2.4k | 3.1k | 13.8k (12) |
| archive | qwen3:30b-a3b | off | 30 | 0.6k | 1.6k | 6.0k (12) |
| archive | qwen3:30b-a3b (off) | injected | 30 | 2.1k | 2.4k | 13.9k (12) |
| archive | qwen3:30b-a3b (off) | off | 30 | 0.6k | 1.4k | 6.0k (12) |
| bids | gemma4:31b (off) | injected | 30 | 0.5k | 1.3k | 90.2k (12) |
| bids | gemma4:31b (off) | off | 30 | 0.4k | 4.0k | 142.9k (12) |
| bids | gemma4:latest | injected | 30 | 2.6k | 3.8k | 41.1k (12) |
| bids | gemma4:latest | off | 30 | 0.4k | 12.2k | 9.4k (12) |
| bids | gemma4:latest (off) | injected | 30 | 0.2k | 1.3k | 29.8k (12) |
| bids | gemma4:latest (off) | off | 30 | 0.0k | 0.6k | 6.2k (12) |
| bids | glm-4.7-flash:latest | injected | 30 | 2.3k | 3.1k | 54.3k (30) |
| bids | glm-4.7-flash:latest | off | 30 | 1.5k | 6.9k | 68.9k (30) |
| bids | glm-4.7-flash:latest (off) | injected | 30 | 1.4k | 2.3k | 60.5k (30) |
| bids | glm-4.7-flash:latest (off) | off | 30 | 1.1k | 5.8k | 74.9k (30) |
| bids | gpt-oss:20b | injected | 30 | 1.4k | 2.5k | 88.4k (12) |
| bids | gpt-oss:20b | off | 30 | 0.7k | 4.9k | 29.0k (12) |
| bids | gpt-oss:20b (off) | injected | 30 | 1.5k | 3.0k | 51.6k (12) |
| bids | gpt-oss:20b (off) | off | 30 | 1.1k | 4.8k | 42.8k (12) |
| bids | granite4.1:30b | injected | 30 | 0.6k | 1.0k | 32.9k (30) |
| bids | granite4.1:30b | off | 30 | 0.1k | 2.9k | 6.3k (30) |
| bids | granite4.1:3b | injected | 30 | 0.4k | 1.3k | 17.9k (30) |
| bids | granite4.1:3b | off | 30 | 0.6k | 6.2k | 26.3k (30) |
| bids | granite4.1:8b | injected | 30 | 0.6k | 1.0k | 32.4k (12) |
| bids | granite4.1:8b | off | 30 | 0.9k | 7.0k | 26.5k (12) |
| bids | llama3.1:8b | injected | 30 | 0.2k | 0.8k | 8.3k (30) |
| bids | llama3.1:8b | off | 30 | 0.1k | 0.9k | 6.3k (30) |
| bids | llama3.2:3b | injected | 30 | 0.1k | 0.4k | 8.4k (12) |
| bids | llama3.2:3b | off | 30 | 0.1k | 0.7k | 7.3k (12) |
| bids | llama3.3:latest | injected | 30 | 0.3k | 0.7k | 12.8k (30) |
| bids | llama3.3:latest | off | 30 | 0.1k | 1.3k | 8.8k (30) |
| bids | ministral-3:3b | injected | 30 | 0.8k | 2.4k | 35.8k (30) |
| bids | ministral-3:3b | off | 30 | 0.2k | 3.5k | 13.1k (30) |
| bids | mistral-small3.2:24b | injected | 30 | 0.1k | 0.9k | 5.6k (30) |
| bids | mistral-small3.2:24b | off | 30 | 0.2k | 1.2k | 8.8k (30) |
| bids | qwen3-coder:30b | injected | 30 | 1.2k | 1.4k | 102.3k (30) |
| bids | qwen3-coder:30b | off | 30 | 0.8k | 5.6k | 67.6k (30) |
| bids | qwen3.8:latest | injected | 30 | 3.0k | 3.9k | 36.4k (30) |
| bids | qwen3.8:latest | off | 30 | 3.8k | 10.0k | 69.4k (30) |
| bids | qwen3.8:latest (off) | injected | 30 | 1.5k | 1.8k | 33.6k (30) |
| bids | qwen3.8:latest (off) | off | 30 | 1.9k | 4.3k | 78.7k (30) |
| bids | qwen3:1.7b | injected | 30 | 2.8k | 20.5k | 24.5k (12) |
| bids | qwen3:1.7b | off | 30 | 1.0k | 11.1k | 12.6k (12) |
| bids | qwen3:1.7b (off) | injected | 30 | 0.0k | 2.0k | 5.2k (12) |
| bids | qwen3:1.7b (off) | off | 30 | 0.1k | 1.1k | 12.1k (12) |
| bids | qwen3:30b-a3b | injected | 30 | 4.5k | 6.4k | 31.3k (12) |
| bids | qwen3:30b-a3b | off | 30 | 1.6k | 28.8k | 12.1k (12) |
| bids | qwen3:30b-a3b (off) | injected | 30 | 4.4k | 6.2k | 58.0k (12) |
| bids | qwen3:30b-a3b (off) | off | 30 | 1.5k | 38.3k | 12.7k (12) |
| curate | gemma4:31b | injected | 20 | 3.7k | 4.0k | 62.1k (8) |
| curate | gemma4:31b | off | 20 | 1.3k | 5.8k | 33.8k (8) |
| curate | gemma4:31b (off) | injected | 20 | 0.5k | 1.0k | 55.9k (8) |
| curate | gemma4:31b (off) | off | 20 | 0.3k | 1.6k | 26.1k (8) |
| curate | gemma4:latest | injected | 20 | 2.6k | 7.7k | 58.7k (8) |
| curate | gemma4:latest | off | 20 | 0.9k | 34.0k | 19.3k (8) |
| curate | gemma4:latest (off) | injected | 20 | 0.8k | 5.6k | 58.2k (8) |
| curate | gemma4:latest (off) | off | 20 | 0.2k | 5.6k | 26.0k (8) |
| curate | glm-4.7-flash:latest | injected | 20 | 1.7k | 3.8k | 63.4k (20) |
| curate | glm-4.7-flash:latest | off | 20 | 0.9k | 7.2k | 21.4k (20) |
| curate | glm-4.7-flash:latest (off) | injected | 20 | 1.0k | 2.3k | 66.3k (20) |
| curate | glm-4.7-flash:latest (off) | off | 20 | 0.5k | 11.3k | 20.8k (20) |
| curate | gpt-oss:20b | injected | 20 | 0.8k | 6.4k | 39.3k (8) |
| curate | gpt-oss:20b | off | 20 | 0.6k | 2.1k | 34.8k (8) |
| curate | gpt-oss:20b (off) | injected | 20 | 1.1k | 2.3k | 39.0k (8) |
| curate | gpt-oss:20b (off) | off | 20 | 0.6k | 2.8k | 30.6k (8) |
| curate | granite4.1:30b | injected | 20 | 0.4k | 2.7k | 27.3k (20) |
| curate | granite4.1:30b | off | 20 | 0.3k | no pass | 19.6k (20) |
| curate | granite4.1:3b | injected | 20 | 0.4k | 2.7k | 27.0k (20) |
| curate | granite4.1:3b | off | 20 | 0.3k | 1.5k | 19.4k (20) |
| curate | granite4.1:8b | injected | 20 | 0.6k | 5.0k | 41.3k (8) |
| curate | granite4.1:8b | off | 20 | 0.3k | no pass | 19.7k (8) |
| curate | llama3.1:8b | injected | 20 | 0.1k | no pass | 13.4k (20) |
| curate | llama3.1:8b | off | 20 | 0.1k | no pass | 8.5k (20) |
| curate | llama3.2:3b | injected | 20 | 0.1k | no pass | 8.8k (8) |
| curate | llama3.2:3b | off | 20 | 0.1k | no pass | 8.6k (8) |
| curate | llama3.3:latest | injected | 20 | 0.2k | no pass | 13.3k (20) |
| curate | llama3.3:latest | off | 20 | 0.2k | 6.5k | 14.8k (20) |
| curate | ministral-3:3b | injected | 20 | 0.5k | 18.2k | 37.4k (20) |
| curate | ministral-3:3b | off | 20 | 0.5k | 2.5k | 27.2k (20) |
| curate | mistral-small3.2:24b | injected | 20 | 0.3k | 7.3k | 16.3k (20) |
| curate | mistral-small3.2:24b | off | 20 | 0.2k | 4.1k | 13.5k (20) |
| curate | qwen3-coder:30b | injected | 20 | 1.1k | 2.7k | 79.8k (20) |
| curate | qwen3-coder:30b | off | 20 | 0.6k | 2.5k | 31.4k (20) |
| curate | qwen3.8:latest | injected | 20 | 3.7k | 4.9k | 72.1k (20) |
| curate | qwen3.8:latest | off | 20 | 1.0k | 2.3k | 33.0k (20) |
| curate | qwen3.8:latest (off) | injected | 20 | 1.2k | 1.6k | 70.7k (20) |
| curate | qwen3.8:latest (off) | off | 20 | 0.7k | 1.8k | 33.3k (20) |
| curate | qwen3:1.7b | injected | 20 | 2.3k | 30.6k | 35.2k (8) |
| curate | qwen3:1.7b | off | 20 | 1.7k | 15.6k | 18.9k (8) |
| curate | qwen3:1.7b (off) | injected | 20 | 1.0k | 36.2k | 108.1k (8) |
| curate | qwen3:1.7b (off) | off | 20 | 0.3k | 4.2k | 48.6k (8) |
| curate | qwen3:30b-a3b | injected | 20 | 6.2k | 14.0k | 27.0k (8) |
| curate | qwen3:30b-a3b | off | 20 | 2.9k | no pass | 18.7k (8) |
| curate | qwen3:30b-a3b (off) | injected | 20 | 6.5k | 18.5k | 56.9k (8) |
| curate | qwen3:30b-a3b (off) | off | 20 | 3.4k | 71.2k | 26.5k (8) |
