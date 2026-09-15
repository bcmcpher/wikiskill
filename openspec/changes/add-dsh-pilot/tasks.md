## 0. Minimal working core

The collection manifest and build (1.1–1.3) and the routing probe smoke run under OFF and ROUTED on one
small local model (2.1–2.2), with its report (3.1). Deferred:
- the reported multi-model run (2.3), until an endpoint is chosen
- passive logging (4.x)
- Phase 2 (5.x)

## 1. Collection

- [ ] 1.1 Extend `examples/collections/data-science-harness.toml`: `claude-plugin` layout sources, a
  small/large alias table, and the watch list from design.md.
- [ ] 1.2 `wikiskill build --collection data-science-harness --harness opencode` into a temp dir. No
  name collisions; `tools:` translated into permissions.
- [ ] 1.3 `git -C ~/Projects/claude/data-science-harness status` is unchanged after build.

## 2. Routing probe

- [ ] 2.1 `pilots/dsh/routing.suite.yaml` referencing `dsh:bench/tasks/routing-lifecycle.yaml` with guard
  rules and `DATALAD_AUTOSAVE=0`.
- [ ] 2.2 Smoke run: one small local model, OFF and ROUTED, k=3.
- [ ] 2.3 Reported run: at least two open models from different families plus INJECTED, with the judge
  from a third family for `handoff@k`.

## 3. Report

- [ ] 3.1 `docs/pilots/dsh-routing.md`, written in the protocol's terms:
  - the control named
  - per-model `route@1`, `route@k`, `capability@k`
  - near-miss confusion pairs
  - routing loss and content value
  - unrun probes and runs stated with reasons
- [ ] 3.2 Hand the most common confusions to the maintainer, as eval-origin evidence for the wiki.

## 4. Passive use

- [ ] 4.1 Install the logger for the data-science-harness collection in OpenCode and use it in a real
  session.
- [ ] 4.2 After a week of use, run `/wikiskill-review` and record the patterns produced in the pilot doc.

## 5. Phase 2 (deferred)

- [ ] 5.1 Specify the sandbox: fake Zenodo/OSF credentials, local git siblings, and a synthetic BIDS
  dataset. (Blocked: not started until Phase 1 reports.)
- [ ] 5.2 Map `schemas/validate-ledger.py` and `tests/e2e-smoke.sh` assertions to command verifiers.

## 6. Verify

- [ ] 6.1 `wikiskill suite check pilots/dsh/routing.suite.yaml` passes, with no prompt naming its
  expected skill.
- [ ] 6.2 The smoke run's `report.md` exists and lists every task, or lists the preflight failure.
- [ ] 6.3 `openspec validate add-dsh-pilot --strict --no-interactive`.
