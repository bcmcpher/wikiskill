# OpenSpec in wikiskill

Specs describe what wikiskill must do; changes propose how it gets there. Project-wide context and
authoring rules live in `config.yaml`. Background research and the architecture these changes implement
are in `docs/research/` and `docs/design/architecture.md`.

## Layout

```
openspec/
  config.yaml                 # context + per-artifact rules (read by `openspec instructions`)
  specs/<capability>/spec.md  # main specs — filled as each change is archived
  changes/<change-id>/
    .openspec.yaml  README.md
    proposal.md  design.md  tasks.md
    specs/<capability>/spec.md  # delta specs
  changes/archive/YYYY-MM-DD-<change-id>/
```

## Conventions

- Change ids are kebab-case verbs: `add-…`, `deepen-…`, `fix-…`. Capabilities are kebab-case nouns.
- Every `### Requirement:` states SHALL or MUST in its first sentence and has at least one
  `#### Scenario:` with `- **WHEN**` / `- **THEN**` bullets.
- A new capability's delta spec opens with `## Purpose` (≥ 50 characters).
- Dependencies between changes are prose bullets under `## Impact` in `proposal.md`; OpenSpec has no
  dependency field.
- `tasks.md` opens with `## 0. Minimal working core` and ends with a Verify group of real commands.
- Harness-specific behaviour names the harness. OpenCode is the primary target, Claude Code secondary.

## Roadmap

Implementation order and the reasoning behind it live in [`ROADMAP.md`](../ROADMAP.md). Change ids
carry no order; prose inside changes refers to other changes by id.

Step 1 is done and archived under [`changes/archive/`](changes/archive/); its capabilities are in
[`specs/`](specs/), as is `add-logging-safeguards`, an amendment to two of them rather than a step of
its own.

Step 2's capabilities are in [`specs/`](specs/) too, synced ahead of archiving: its minimal working
core is implemented and `add-explicit-eval` stays active for the rest. Where a synced requirement
runs ahead of the code — INJECTED, verifiers, the rubric judge, the data-science-harness adapter —
the change's `tasks.md` is what says so.

| # | Change | Capabilities | Hard dependencies |
|---|---|---|---|
| 1 ✅ | `add-trace-logging` | collection-config, trace-log, harness-packaging | — |
| 2 | `add-explicit-eval` | task-suite, eval-runner, eval-scoring (+ trace-log) | 1 |
| 3 | `add-dsh-pilot` (Phase 1) | dsh-pilot | 2 |
| 4 | `add-correction-capture` | correction-signal | 1 |
| 5 | `add-claude-code-adapter` | claude-code-adapter (+ harness-packaging, correction-signal, eval-runner) | 1, 2, 4 |
| 6 | `add-experience-wiki` | experience-wiki | 1, 4 |
| 7 | `add-skill-refinement` | refinement-proposal, refinement-gate | 2, 6 |
| 8 | `add-collection-graph` | collection-graph | 1, 2, 7 |

## Commands

```bash
OPENSPEC=~/.claude-node-tools/bin/openspec
$OPENSPEC list
$OPENSPEC status --change <id>
$OPENSPEC validate --all --strict --no-interactive
$OPENSPEC show <id> --deltas-only
```

Workflow commands are installed for both harnesses: `/opsx-propose`, `/opsx-apply`, `/opsx-archive`
(OpenCode) and `/opsx:propose`, `/opsx:apply`, `/opsx:archive` (Claude Code).
