## 0. Minimal working core

Dependency edges from declarations (1.1) and conflict edges from eval runs (1.3), with `graph show`
(2.1). That already guards description edits.

Deferred: co-usage (1.2). Every raw log on this machine was counted on 2026-10-05: 48 eval units and
2 live sessions activated one component, 1 eval unit activated two, and no live session activated
two. Co-activation inside an eval reflects the suite's design, not use, so the edge waits for live
logs.

## 0a. Rebase onto add-skill-refinement

- [x] 0a.1 `add-skill-refinement` built the gate in `src/wikiskill/gate.py`. Replay compares a
  baseline and a candidate run (`wikiskill eval --proposal`) of one suite: the motivating cases are
  the suite tasks the cited patterns came from, and the regression bank is every other task. It
  does not choose or run suites itself. Restate "neighbours are added to replay" and "description
  edits replay conflict neighbours' routing tasks" against that design, as `MODIFIED`/`ADDED`
  deltas on `refinement-gate`. For example, replay could warn when the runs leave out a neighbour's
  tasks, rather than add runs.
  - Done. `specs/refinement-gate/spec.md` modifies "Replay covers motivating cases and a regression
    bank on every model": with a graph, replay names each neighbour and the suite tasks expecting it,
    lists uncovered neighbours, and adds no runs. It adds "Description edits must not steal neighbour
    triggers". The replay cap was dropped: nothing is added, so nothing needs capping.

## 1. Graph construction

- [x] 1.1 Dependency edges from `delegates_to` frontmatter and body mentions, with evidence locations.
  - A `delegates_to` entry naming a plugin points at its agents (weight 1.0); one naming a component
    points at it; one naming nothing in the collection is kept as unresolved. Mentions (0.5) are a
    full `plugin/name` as a whole word, or a bare name in backticks. Evidence: file and line.
- [ ] 1.2 (deferred) Co-usage edges from raw logs, with a minimum session count. See section 0.
- [x] 1.3 Conflict edges from eval routing confusion, keeping per-model values; candidate runs left out.
  - Under ROUTED, per expected route and model, the share of scored repeats whose first activation
    was another component, pooled over runs; models that never confused them are kept at 0.
  - Read-only build on this machine's runs: `my-skills` has `analysis-plan` and `analysis-refactor`
    confused both ways (ministral-3:3b 1.00 one way, qwen3:1.7b 1.00 the other, gemma4 0.00), and
    `wikiskill-self` has `wikiskill-trace -> wikiskill-maintainer` at 0.40 on qwen3:1.7b. The p-002
    candidate run was skipped.
- [x] 1.4 `wiki/graph.json` written and committed by `wikiskill graph build`.

## 2. Use

- [x] 2.1 `wikiskill graph show` and `wikiskill graph neighbours <component>`.
- [x] 2.2 Replay coverage: with a graph, replay names each neighbour and the suite tasks expecting
  it, and lists uncovered neighbours. No runs are added, so there is nothing to cap.
- [x] 2.3 Trigger-theft check: `refine` records `description_changed`; replay compares conflict
  neighbours' `route@1` per model for description edits, and an uncovered conflict neighbour blocks
  "accept".
  - Older proposals without the field fall back to the source while it still has the proposal's
    `source_hash`. Without a graph, a description edit gets a reason saying theft was not checked.

## 3. Verify

- [x] 3.1 `uv run pytest tests/test_graph.py`: a fixture modelled on data-science-harness frontmatter
  produces a dependency edge from `disseminate/dataset-release` to the archive doer; a recorded
  confusion produces a checkpoint→release conflict edge.
  - 8 passed, including one that builds from the real `~/Projects/claude/data-science-harness`
    (`disseminate` and `archive` plugins, read only) and finds `disseminate/dataset-release ->
    archive/archive-doer` at 1.0. It skips where that checkout is absent.
- [x] 3.2 `uv run pytest tests/test_gate.py -k "theft or neighbour"`: a candidate description lowering
  a conflict neighbour's `route@1` is listed as a trigger-theft regression; an uncovered neighbour is
  listed.
  - 4 selected, 4 passed. Whole suite: 700 passed.
- [x] 3.3 `openspec validate add-collection-graph --strict --no-interactive`.
