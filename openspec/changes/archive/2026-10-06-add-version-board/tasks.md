## 1. Version axis

- [x] 1.1 `version_board.pool(runs, component)`, on the leaderboard's own suite check, warnings and
  `components(vary=component)`: allow that component's hash to differ, keep every other refusal,
  and key cells by (model, version)
- [x] 1.2 Version labels: `p-NNN` from proposal metadata or a run's `proposal`, else as
  `diff --list` labels them; `--baseline` resolved with `diff.resolve`, default `current`
- [x] 1.3 OFF pooled per model across versions; lift per version; a version without OFF still ranked
- [x] 1.4 `--condition injected|routed`, default injected

## 2. Ranking

- [x] 2.1 Per model: Wilson rates, best version, direction against the baseline by `compare`'s
  rule, regressions beyond the gate's tolerance
- [x] 2.2 Common panel, the models left out, macro mean per version
- [x] 2.3 Paired (model, task) cells against the baseline: won, lost, exact sign test
- [x] 2.4 Best overall, excluding disqualified versions and those regressing a panel model; the
  number of versions compared
- [x] 2.5 `--critical <file>`: parse, check indices against each task's recorded verifiers,
  disqualify, list units, record the file hash

## 3. Output and CLI

- [x] 3.1 `board.md`: per-model table (OFF, each version, best, direction), overall table (mean,
  cells won/lost, sign test, regressions, disqualified), per-model version × task matrix
- [x] 3.2 `board.json` with per-unit verdicts and run ids, under `evals/versions/<component>/`
- [x] 3.3 `cli/leaderboard.py`: `--by-version`, `--baseline`, `--condition`, `--critical`;
  misuse exits 2 for a refused pool or a bad critical file

## 4. Review for one model

- [x] 4.1 `review --model` and `sample --model`: filter eval units by model, drop raw sessions, say
  so in the prompt
- [x] 4.2 Record the model in the proposal's meta when refine reads such a review

## 5. Tests and docs

- [x] 5.1 `tests/test_version_board.py`: pooling and refusals, shared OFF, per-model best and
  direction, panel, macro mean, sign test, regression rule, critical disqualification, labels
- [x] 5.2 Review `--model` tests
- [x] 5.3 README and `docs/data.md`: the board, its output, and critical-check files
- [x] 5.4 `bin/check` passes; `openspec validate add-version-board --strict --no-interactive`
