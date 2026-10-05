## 0. Minimal working core

One unit through the whole loop, and a DSH pilot report (1.x, 2.x, 4.1). `add-minimal-loop` built
the loop and ran review and refine live on `datalad/datalad-doer`, but that unit was deleted upstream
before its v1/v2 comparison, so its 6.0c, 6.1, 6.2 and 8.4 move here: the first unit's 2.3–2.4 run
is Milestone A's v1/v2 comparison.

Deferred:
- the routing probe over the whole collection (3.x), which is optional until per-unit pilots show
  the loop works on DSH
- passive logging (5.x), until the loop is in regular use
- Phase 2 (6.x)

All runs used DSH at `c6f6079` (`main`), OpenCode 1.18.34, and Ollama 0.34.2 on a GB10. The models
were `ollama/gemma4:latest` and `ollama/qwen3:30b-a3b`, with `--thinking default`. The maintainer
and proposer were `qwen3:30b-a3b` at a 40960-token context. The report is `docs/pilots/dsh.md`.

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
  `docs/pilots/dsh.md`.
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

## 3. Routing probe (optional)

Deferred: optional by design, and not needed for Milestone A. The archive doer is delegated by
planners, so routing to it is a question about planners, which this probe is for.

- [ ] 3.1 `pilots/dsh/routing.suite.yaml` reading `bench/tasks/routing-lifecycle.yaml`, with guard
  rules and `env: { DATALAD_AUTOSAVE: "0" }`.
- [ ] 3.2 Smoke run: one model, OFF and ROUTED, k=3.
- [ ] 3.3 Reported run: at least two open models from different families plus INJECTED, with the judge
  from a third family for `handoff@k`.

## 4. Report

- [x] 4.1 `docs/pilots/dsh.md`, written in the protocol's terms:
  - the control named
  - per unit and per model: pass rates with intervals, the direction, and tool choice
  - the proposals and the decisions on them
  - unrun probes and runs, with reasons
- [ ] 4.2 Hand accepted patches to the data-science-harness maintainer, with their comparisons.
  Deferred: no patch was accepted. `docs/pilots/dsh.md` notes one untested finding for the
  maintainer: the doer's repository-relative `archive-cli` paths do not resolve outside a DSH
  checkout. Sending it is the user's call.

## 5. Passive use

Deferred until Milestone C, as the roadmap sets out.

- [ ] 5.1 Install the logger for a unit's collection in OpenCode and use it in a real session.
- [ ] 5.2 After a week of use, run `wikiskill review` on that unit and record what live sessions add
  beyond the evals.

## 6. Phase 2 (deferred)

- [ ] 6.1 Specify the sandbox: fake Zenodo/OSF credentials, local git siblings, and a synthetic BIDS
  dataset. (Blocked: not started until the per-unit pilots report.)
- [ ] 6.2 Map `schemas/validate-ledger.py` and `tests/e2e-smoke.sh` assertions to command verifiers.

## 7. Verify

- [x] 7.1 `wikiskill suite check` passes for every pilot suite, with no prompt naming its expected
  component. `pilots/archive-doer/suite.yaml` and `pilots/datalad-doer/suite.yaml` both print `ok`.
  No archive prompt names the doer, a skill or the readiness check.
- [x] 7.2 `git -C ~/Projects/claude/data-science-harness status --porcelain` is unchanged by every
  step, apart from patches the user applied. Checked before the candidate run and after the
  decision: `status --porcelain` was empty, HEAD stayed at `c6f6079`, and no file outside the VCS
  directory changed after the pilot began.
- [x] 7.3 `openspec validate add-dsh-pilot --strict --no-interactive`.
