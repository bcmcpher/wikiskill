## 0. Minimal working core

Done: one unit through the whole loop, and a DSH pilot report (1.x, 2.x, 4.1). `add-minimal-loop`
built the loop and ran review and refine live on `datalad/datalad-doer`. That unit was deleted
upstream before its v1/v2 comparison, so its 6.0c, 6.1, 6.2 and 8.4 moved here: the first unit's
2.3–2.4 run is Milestone A's v1/v2 comparison.

Sections 1–2 used DSH at `c6f6079` (`main`), OpenCode 1.18.34, and Ollama 0.34.2 on a GB10. The
models were `ollama/gemma4:latest` and `ollama/qwen3:30b-a3b`, with `--thinking default`. The
maintainer and proposer were `qwen3:30b-a3b` at a 40960-token context. The report is
`docs/pilots/dsh/report.md`.

Rewritten 2026-10-06 for a broader check across models (sections 3–7). Passive use (old 5.x) and
Phase 2 (old 6.x) moved out to their own changes. Old 4.2 is now 3.5.

## 1. Choose units

- [x] 1.1 Pick the next unit and record why. Candidates:
  - `archive/archive-doer` with `archive-cli`, whose rule is never to fabricate a DOI
  - a planner and doer pair such as `govern/preregister` with `datalad-doer`
  - `bids/bids-doer`, once `bids-validator` and a BIDS fixture are available

  Chose `archive/archive-doer`. Each of its rules leaves something a verifier can check offline:
  - no invented DOI
  - `unminted` with the missing credential
  - only existing tags deposited
  - no commits
  - `ledger-only` for a relation it cannot write

  The pair needs the routing probe, and `bids-doer` needs its fixture. The reasons are in
  `docs/pilots/dsh/report.md`.
- [x] 1.2 For each unit, `pilots/<unit>/<collection>.toml` with `plugins = [...]`, and
  `wikiskill collection check` passing. Done in `pilots/archive-doer/dsh-archive.toml`:
  - `plugins = ["archive", "archive-cli"]`
  - 4 components discovered, with `archive/archive-doer` watched
  - `collection check dsh-archive --sync` printed `ok`
  - `build` mirrors `plugins/archive-cli/scripts/check-readiness.sh`

## 2. Per-unit loop

- [x] 2.1 `pilots/<unit>/suite.yaml`:
  - `setup` builds each starting state
  - the guard denies anything that leaves the machine
  - some tasks only the unit's own rules can pass

  Done in `pilots/archive-doer/suite.yaml`: 6 tasks with 3 repeats each, on plain git
  repositories.
  - Every archive credential is set empty.
  - The guard refuses the archive hosts, `git push`, `git remote add`, `datalad push` and
    `datalad create-sibling`.
  - The one task with a token points `ZENODO_API` at a closed local port.
  - `suite check` printed `ok`.
- [x] 2.2 Check every task by hand: a correct solution passes all its verifiers, and a plausible
  wrong one fails. Each task was built from its `setup` and scored with `verify_task`:
  - Every correct end state passed, including a JSON structured reply.
  - Two wrong ones per task failed: a fabricated DOI, a hint left out, a tag invented or moved, a
    commit, prose instead of the structured form, and `failed` instead of `ledger-only`.
  - The first v1 run found that JSON replies failed `result:` matching. The regexes were fixed and
    a JSON case was added to the hand check. That run was discarded.
- [x] 2.3 v1 run under OFF and INJECTED (or ROUTED, for a skill), with repeats chosen up front.
  Check live that INJECTED ran the unit itself. The v1 run was `01M46QWP6CTEM5DN807VS7GQMW`, with
  3 repeats:
  - 72 units: 71 `completed`, 1 `permission_blocked`.
  - OFF: gemma4 8/18 (44%, 25–66%), qwen3 9/18 (50%, 29–71%).
  - INJECTED: gemma4 16/18 (89%, 67–97%), qwen3 18/18 (100%, 82–100%).
  - Every INJECTED session's messages are from agent `archive-doer`.
  - No DOI appeared in any reply.
  - In 30 of 36 INJECTED units, the doer's repository-relative readiness script was not found.
- [x] 2.4 `wikiskill review`, `wikiskill refine`, apply by hand, v2 run with the same repeats, then
  `wikiskill compare --record`. Run through the step 8 gate instead of applying by hand, because the
  candidate is evaluated from a copy of the source.
  - **Review.** The first review was shown only OFF units. Review then ranked a component's own
    units before OFF ones within a rank (`review._choose`). The next review created a path pattern,
    and a resampled review replaced it with `archive-doer-ignores-skill-path`, which cites one unit.
  - **p-001 was withdrawn.** Its prompt showed no evidence, because `cited_digest` keyed eval results
    by their harness `session_id`. Fixed in `review._ref_key`.
  - **p-002** (proposer `qwen3:30b-a3b`, citing E1) adds "Use EXACTLY the path specified in the
    backend skill".
  - **Candidate run.** `eval --proposal p-002` produced `01M46VFM331Y2MXZ8DNPTY5R6J` with the same
    arguments (candidate hash `sha256:2b8de7d5…`). OFF was unchanged. INJECTED: gemma4 15/18 (83%,
    61–94%), qwen3 18/18.
  - **Replay** recommended "do not accept":
    - The motivating `auto-backend-structured` was already 3/3 on both models.
    - `mint-without-token` on gemma4 fell from 1/3 to 0/3, within tolerance.
  - **p-002 was rejected** and recorded in `skill-impact.md`.

## 3. Readiness-path candidate

- [ ] 3.1 Work out a reference to `archive-cli/scripts/check-readiness.sh` from `archive-doer.md`
  that resolves both in a DSH checkout and after `bin/install.sh` and `wikiskill build`. The doer
  and the script are in different plugins, so `${CLAUDE_PLUGIN_ROOT}` alone is not enough. Record
  what each installer lays down.
- [ ] 3.2 Write the patch by hand as a proposer reply. Submit it with `wikiskill refine
  archive/archive-doer --prepare` and `--reply-file`, citing v1 units where the script was not
  found. `collection check` passes on the candidate with no new unresolved-path warning.
- [ ] 3.3 `eval --proposal` with v1's suite, models, conditions and repeats. Check in the
  transcripts that the readiness script now runs.
- [ ] 3.4 `proposal replay` against v1, `proposal decide`, and `wikiskill diff` of v1 against the
  candidate for the report.
- [ ] 3.5 If accepted, hand the patch and its comparison to the DSH maintainer. Sending it is the
  user's call.

## 4. Model sweep (archive-doer suite)

- [ ] 4.0 `pilots/models.toml`, the model catalogue (`add-pilot-reporting`): family, size and shape
  of every model in the design's table. Point `docs/pilots/dsh/findings.toml`'s `models_file` at it.
  `pilots/archive-doer/sweep.sh`: one eval per model, in the design's order, skipping models with a
  finished run. After each run it calls
  `wikiskill findings add docs/pilots/dsh <run_id> --role sweep` (`add-findings-export`), so the
  study's manifest is the run log.
- [ ] 4.1 Preflight every model in the design's table, at `--thinking default`. Record per model:
  pass or the failure reason, and the served context. Fill in the size and shape of the added models
  from `ollama show`, and which ones the server says can think.
- [ ] 4.2 Fix the repeats before the first run (design: 10 per task, n = 60 per cell) and record
  them in the report.
- [ ] 4.3 One run per model that passed, OFF and INJECTED, smallest first, `llama3.3` last. The
  suite file is unchanged, so its hash matches v1.
- [ ] 4.4 Thinking arm: `--thinking off` for the models that can think (from 4.1), same suite and
  repeats.
- [ ] 4.5 Noise: rerun `gemma4` on the v1 settings on a different day. Use `wikiskill compare`
  for the run-to-run spread.
- [ ] 4.6 Declare a `sweep` leaderboard table over roles `sweep` and `v1` in the study, then run
  `wikiskill findings bundle`, `findings tables` and `bin/figures`. Answer the design's six
  questions from the per-model table.
- [ ] 4.7 Ceiling check. If two or more models are at the ceiling under INJECTED, write harder tasks
  in a new suite file, check them by hand (as 2.2), and run them on the top models.

## 4b. Best version (needs `add-version-board`)

- [ ] 4b.1 `pilots/archive-doer/critical.yaml`: no DOI, tags unmoved, no commit, by task and
  verifier index. `leaderboard --by-version` accepts it against the sweep runs.
- [ ] 4b.2 Candidates: the readiness candidate (3.x), one proposal from a review of every sweep
  run, and up to two from `review --model` for the lowest INJECTED models under v1. At most six
  versions with v1 and `p-002`.
- [ ] 4b.3 Screening: set the panel (one model per family, middle size) and the repeats from the
  sweep's unit times, and record both. Run each candidate INJECTED on the panel, and per-model
  candidates on their target too.
- [ ] 4b.4 Finals: the top two not disqualified by screening mean, plus any per-model screening
  winner, on every sweep model at the sweep's repeats. The version board over finals and sweep.
- [ ] 4b.5 Confirmation: a fresh run of the best overall and v1 on the panel, and of each per-model
  best that was `up`, on its model. Report only confirmed bests as findings.
- [ ] 4b.6 Gate: `proposal replay` of the confirmed best overall against v1, then `proposal
  decide`.

## 5. Routing probe

- [ ] 5.1 `pilots/dsh/dsh.toml` over the whole of DSH. `collection check --sync` passes, and the
  flat-name mapping is printed with no collision.
- [ ] 5.2 `pilots/dsh/routing.suite.yaml` from every task of `bench/tasks/routing-lifecycle.yaml`:
  - `expected_skill` as the route, and `expected_delegates_to` as the delegates
  - guard rules, and `env: { DATALAD_AUTOSAVE: "0" }`
  - `suite check` passes, and no prompt names its expected component
- [ ] 5.3 A three-judge handoff rubric for `handoff@k`, scored against the parameters each doer
  states it requires, with `shows: [delegations]`. Judges: `gpt-oss:120b`, `llama3.3` and
  `nemotron-3.5-lightning` as one `[roles.judge] models` panel (`add-pilot-reporting`); none is a
  routing entrant.
- [ ] 5.4 Smoke run: `gemma4`, OFF and ROUTED, k=3. Read the transcripts: routes are detected and
  delegations are captured.
- [ ] 5.5 Reported run: the models that finished the sweep, except the judges, from at least three
  families. Run OFF, ROUTED and INJECTED, k=3, with the handoff judges.
- [ ] 5.6 Per planner task, compare ROUTED with INJECTED to separate routing loss from content
  value.

## 6. Report

Every section below is written into `docs/pilots/dsh/report.md` and `slides.md`, the study made by
`add-findings-export`. The study lives on the `results/dsh-pilot` branch, not `main`; results are
committed there, and tooling changes on `main` are merged in. Numbers come in through `<!-- include: tables/... -->` lines, never copied
by hand. Each run is added with `findings add` and bundled, and every table is declared in
`findings.toml`. `findings tables --check` passes before a commit, and `bin/build-docs` makes the
`.docx` and `.pptx`.

- [x] 6.1 `docs/pilots/dsh/report.md`, written in the protocol's terms (was 4.1):
  - the control named
  - per unit and per model: pass rates with intervals, the direction, and tool choice
  - the proposals and the decisions on them
  - unrun probes and runs, with reasons
- [ ] 6.2 Add the readiness candidate, with its diff and decision.
- [ ] 6.3 Add the sweep: models that failed preflight, repeats, per-model and thinking tables, the
  run-to-run spread, and answers to the six questions.
- [ ] 6.3b Add the versions section: version table with `diff` summaries, critical checks,
  screening and finals boards, best overall and per model, confirmation and decision.
- [ ] 6.4 Add the routing probe: `route@1`, `route@k`, `capability@k` and `handoff@k` per model,
  with per-judge labels and the routing-loss breakdown.
- [ ] 6.5 Record `datalad/datalad-doer` as retired: its doer was deleted upstream, and
  `pilots/datalad-doer/` is kept for the record and not run. Update the unrun list: provenance,
  reproducibility and cost probes, passive use, and any model or run that did not finish.

## 7. Verify

- [x] 7.1 `wikiskill suite check` passes for every pilot suite, with no prompt naming its expected
  component. `pilots/archive-doer/suite.yaml` and `pilots/datalad-doer/suite.yaml` both print `ok`.
  No archive prompt names the doer, a skill or the readiness check.
- [ ] 7.1b The same for `pilots/dsh/routing.suite.yaml` and any harder archive suite from 4.7.
- [x] 7.2 `git -C ~/Projects/claude/data-science-harness status --porcelain` is unchanged by every
  step, apart from patches the user applied. Checked before the candidate run and after the
  decision: `status --porcelain` was empty, HEAD stayed at `c6f6079`, and no file outside the VCS
  directory changed after the pilot began.
- [ ] 7.2b The same check after sections 3–5.
- [ ] 7.3 `openspec validate add-dsh-pilot --strict --no-interactive`.
