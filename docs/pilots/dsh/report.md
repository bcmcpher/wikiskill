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
- Models under test: `ollama/gemma4:latest` (128k context) and `ollama/qwen3:30b-a3b` (256k). Both
  passed preflight. Thinking was left at each model's default (`--thinking default`, recorded in
  `run.json`), and each turn was capped at 8192 output tokens.
- Maintainer and proposer: `qwen3:30b-a3b` at a 40960-token context. It is also a model under test.
  These roles only read evidence and are never scored.

Every table and figure below is generated from the runs bundled in this directory (`runs/`, listed
in `findings.toml`) by `wikiskill findings tables` and `bin/figures`, and the documents are built
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

## Not run

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
