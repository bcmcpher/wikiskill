## 0. Minimal working core

One more unit through the whole loop, after `datalad/datalad-doer` (done in `add-minimal-loop`), and
a DSH pilot report covering both units (1.x, 2.x, 4.1).

Deferred:
- the routing probe over the whole collection (3.x), which is optional until per-unit pilots show
  the loop works on DSH
- passive logging (5.x), until the loop is in regular use
- Phase 2 (6.x)

## 1. Choose units

- [ ] 1.1 Pick the next unit and record why. Candidates:
  - `archive/archive-doer` with `archive-cli`, whose rule is never to fabricate a DOI
  - a planner and doer pair such as `govern/preregister` with `datalad-doer`
  - `bids/bids-doer`, once `bids-validator` and a BIDS fixture are available
- [ ] 1.2 For each unit, `pilots/<unit>/<collection>.toml` with `plugins = [...]`, and
  `wikiskill collection check` passing.

## 2. Per-unit loop

- [ ] 2.1 `pilots/<unit>/suite.yaml`:
  - `setup` builds each starting state
  - the guard denies anything that leaves the machine
  - some tasks only the unit's own rules can pass
- [ ] 2.2 Check every task by hand: a correct solution passes all its verifiers, and a plausible
  wrong one fails.
- [ ] 2.3 v1 run under OFF and INJECTED (or ROUTED, for a skill), with repeats chosen up front.
  Check live that INJECTED ran the unit itself.
- [ ] 2.4 `wikiskill review`, `wikiskill refine`, apply by hand, v2 run with the same repeats, then
  `wikiskill compare --record`.

## 3. Routing probe (optional)

- [ ] 3.1 `pilots/dsh/routing.suite.yaml` reading `bench/tasks/routing-lifecycle.yaml`, with guard
  rules and `env: { DATALAD_AUTOSAVE: "0" }`.
- [ ] 3.2 Smoke run: one model, OFF and ROUTED, k=3.
- [ ] 3.3 Reported run: at least two open models from different families plus INJECTED, with the judge
  from a third family for `handoff@k`.

## 4. Report

- [ ] 4.1 `docs/pilots/dsh.md`, written in the protocol's terms:
  - the control named
  - per unit and per model: pass rates with intervals, the direction, and tool choice
  - the proposals and the decisions on them
  - unrun probes and runs, with reasons
- [ ] 4.2 Hand accepted patches to the data-science-harness maintainer, with their comparisons.

## 5. Passive use

- [ ] 5.1 Install the logger for a unit's collection in OpenCode and use it in a real session.
- [ ] 5.2 After a week of use, run `wikiskill review` on that unit and record what live sessions add
  beyond the evals.

## 6. Phase 2 (deferred)

- [ ] 6.1 Specify the sandbox: fake Zenodo/OSF credentials, local git siblings, and a synthetic BIDS
  dataset. (Blocked: not started until the per-unit pilots report.)
- [ ] 6.2 Map `schemas/validate-ledger.py` and `tests/e2e-smoke.sh` assertions to command verifiers.

## 7. Verify

- [ ] 7.1 `wikiskill suite check` passes for every pilot suite, with no prompt naming its expected
  component.
- [ ] 7.2 `git -C ~/Projects/claude/data-science-harness status --porcelain` is unchanged by every
  step, apart from patches the user applied.
- [ ] 7.3 `openspec validate add-dsh-pilot --strict --no-interactive`.
