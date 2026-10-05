## 0. Minimal working core

Dependency edges from declarations (1.1) and conflict edges from eval reports (1.3), with `graph show`
(2.1). That already guards description edits. Deferred: co-usage (1.2), until logs are plentiful.

## 0a. Rebase onto add-skill-refinement

- [ ] 0a.1 `add-skill-refinement` built the gate in `src/wikiskill/gate.py`. Replay compares a
  baseline and a candidate run (`wikiskill eval --proposal`) of one suite: the motivating cases are
  the suite tasks the cited patterns came from, and the regression bank is every other task. It
  does not choose or run suites itself. Restate "neighbours are added to replay" and "description
  edits replay conflict neighbours' routing tasks" against that design, as `MODIFIED`/`ADDED`
  deltas on `refinement-gate`. For example, replay could warn when the runs leave out a neighbour's
  tasks, rather than add runs.

## 1. Graph construction

- [ ] 1.1 Dependency edges from `delegates_to` frontmatter and body mentions, with evidence locations.
- [ ] 1.2 Co-usage edges from raw logs, with a minimum session count.
- [ ] 1.3 Conflict edges from eval routing confusion matrices, keeping per-model values.
- [ ] 1.4 `wiki/graph.json` written and committed by `wikiskill graph build`.

## 2. Use

- [ ] 2.1 `wikiskill graph show` and `wikiskill graph neighbours <component>`.
- [ ] 2.2 Gate integration: add neighbour replay sets to replay, capped, with capped items reported.
- [ ] 2.3 Trigger-theft check for `description` edits against conflict neighbours.

## 3. Verify

- [ ] 3.1 `uv run pytest tests/test_graph.py`: data-science-harness fixture frontmatter produces a
  dependency edge from `disseminate/dataset-release` to the archive doer; a recorded confusion matrix
  produces a checkpoint↔release conflict edge.
- [ ] 3.2 `uv run pytest tests/test_gate.py -k theft`: a candidate description lowering a neighbour's
  `route@1` is listed as a regression.
- [ ] 3.3 `openspec validate add-collection-graph --strict --no-interactive`.
