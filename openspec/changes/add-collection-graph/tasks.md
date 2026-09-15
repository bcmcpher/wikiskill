## 0. Minimal working core

Dependency edges from declarations (1.1) and conflict edges from eval reports (1.3), with `graph show`
(2.1). That already guards description edits. Deferred: co-usage (1.2), until logs are plentiful.

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
