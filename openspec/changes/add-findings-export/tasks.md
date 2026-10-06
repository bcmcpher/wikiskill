## 0. Minimal working core

The smallest shippable slice: a `findings.toml`, `findings bundle`, and `findings tables` writing the
full leaderboard fragment and the CSV, plus `bin/build-docs` turning a report with one include into
`.docx`. The DSH study can then be bundled and built while the sweep runs.

Deferred to later sections:
- the slim fragments, `--check` and the version-board and report table kinds
- figures and slides
- the three refactors

## 1. Rate formatting (refactor, first so every new output uses it)

- [x] 1.1 `src/wikiskill/present.py`: `rate`, `count`, `pct`, `MISSING = "—"`, `table`. Unit tests
  cover `9/10 (90%, 60-98%)`, `0/0` giving `—`, and signed percent.
- [x] 1.2 Replace `_fmt`/`_pct`/`_rate_text` in `compare`, `leaderboard`, `version_board`, `gate`
  and `report` with `present`. `grep -n "def _fmt\|def _pct\|def _rate_text" src/wikiskill` finds
  nothing, and `bin/check` passes after string assertions are updated.
- [x] 1.3 README: one sentence on the rate format, and on the dash and the dropped `CI` prefix.

## 2. Report as a view over the pool (refactor)

- [x] 2.1 `report.build_report` takes each row's `pass_rate`, `outcomes`, `tokens` and
  `wall_time_ms` from `leaderboard.pool([run])` cells. Route metrics stay in `score`.
  `report.json` keys are unchanged, as a test diffing the key sets before and after shows.
- [x] 2.2 Run `wikiskill report` on the v1 (`01M46QWP…`) and p-002 (`01M46VFM…`) runs before and
  after. List any changed number in this task with its cause. The expectation is none.
  Result: both reports' JSON and markdown are identical before and after. One difference exists in
  principle, and a test pins it: a task with no verifiers was given its route@1 as a pass rate under
  every condition. It is now measured only under ROUTED, as the pooled-results requirement says.
  Neither pilot run has such a task.

## 3. One call classifier (refactor)

- [x] 3.1 Before moving anything, pin both runners' normalized events on their existing fixtures
  with a golden test that compares the event list, including `delegation` and `component_activated`.
- [x] 3.2 `src/wikiskill/calls.py`: tool-name sets, agent fields, `target()` and
  `delegation()`. The Claude Code and OpenCode runners use it. The golden tests from 3.1 pass
  unchanged.
- [x] 3.3 `judge.delegations` and `hooks` use `calls`. The judge delegation tests pass unchanged, and
  `grep -n "_AGENT_TOOLS\|_TASK_TOOLS\|_AGENT_FIELDS\|^AGENT_TOOLS" src/wikiskill` names only
  `calls.py`.

## 4. Study manifest and bundle

- [x] 4.1 `src/wikiskill/findings.py`: load and validate `findings.toml` (`[study]`, `[[runs]]`,
  `[[tables]]`). Tests cover the refusals for an unknown kind, an unknown role and a duplicate run.
- [x] 4.2 `wikiskill findings bundle <study>`: copy `run.json` and `results.jsonl` per run. Tests
  cover:
  - skipping a bundled run
  - refusing a changed one
  - reporting a missing one and bundling the rest
  - that no `units/` file is copied
- [x] 4.3 `wikiskill findings add <study> <run_id> --role R [--label L]`: append one run and refuse a
  duplicate. Covered by tests.

## 5. Tables and data

- [x] 5.1 `wikiskill findings tables <study>`: full `leaderboard` fragments from the bundle, with no
  evals directory present. A test runs with `XDG_DATA_HOME` pointing at an empty directory.
- [x] 5.2 The `version-board` kind, labelled from the run entries without a version store, and the
  `report` kind, giving the per-judge tables for the named runs. Covered by tests.
- [x] 5.3 Slim fragments of at most six columns, through `present`. A test checks the column count
  for each kind.
- [x] 5.4 The long CSV in the design's schema. A test checks every markdown rate against a CSV row,
  and that pooled rows have an empty `task`.
- [x] 5.5 `--check`: it writes nothing and exits non-zero listing the stale fragments. A test covers
  a fresh state, then one changed after a new run is bundled.

## 6. Figures and documents

- [x] 6.1 `bin/figures <study>` (PEP 723, `matplotlib`): the forest plot and the lift figure from
  `findings.csv`. Run it on a test study. `pyproject.toml` and `uv.lock` are unchanged.
- [x] 6.2 `bin/build-docs <study>`:
  - include expansion, refusing a missing include
  - `pandoc` for `report.docx` and `slides.pptx` (`--slide-level 2`), with optional reference
    templates
  - atomic writes, and `build.txt` with the pandoc version
  - a missing pandoc refused with nothing written

  Tests cover include expansion and the missing-pandoc refusal by putting an empty directory on
  `PATH`.
- [x] 6.3 `.gitignore`: `docs/**/*.docx`, `docs/**/*.pptx` and `docs/**/build.txt`. After a build,
  `git status --porcelain docs` shows no office file.
- [x] 6.4 `docs/findings/how-wikiskill-works.md` and `how-wikiskill-works.slides.md`, in the terms
  of the main specs. Check them against `openspec/specs/eval-scoring`, `version-board` and
  `refinement-gate` by reading them side by side.

## 7. The DSH study

- [x] 7.1 Move `docs/pilots/dsh.md` to `docs/pilots/dsh/report.md`, and fix every link to it
  (`grep -rn "pilots/dsh.md"` finds none). Write `docs/pilots/dsh/findings.toml` with the v1 and
  p-002 runs under role `versions`, and tables `pilot` (leaderboard) and `archive-doer-versions`
  (version board).
- [x] 7.2 Bundle, then generate tables and figures. `report.md` includes "how wikiskill works" and
  the pilot fragments in place of its hand-copied numbers. The numbers match the hand-copied ones
  they replace: gemma4 16/18 against 15/18, qwen3 18/18 both, and OFF pooled n=36.
- [x] 7.3 `docs/pilots/dsh/slides.md` follows the design's report structure, one section per part,
  with speaker notes. Parts with no data yet are stated as pending, not left out.
- [x] 7.4 Build both documents. QA: open them with the document skills' `validate.py`, render
  `slides.pptx` to images through LibreOffice, and look at every slide for overflow.
- [x] 7.5 `add-dsh-pilot` tasks 4.0 and 6.x name the study: `sweep.sh` calls `findings add` per
  finished run, and the report tasks write into `docs/pilots/dsh/report.md` and `slides.md`.

## 8. Verify

- [x] 8.1 `bin/check` passes.
- [x] 8.2 From a fresh clone (`git clone . /tmp/wsclone`) run
  `uv run wikiskill findings tables docs/pilots/dsh --check`. It passes with no XDG data.
- [x] 8.3 `bin/build-docs docs/pilots/dsh` writes `report.docx` and `slides.pptx`. Both open in
  LibreOffice (`soffice --headless --convert-to pdf`).
- [x] 8.4 `openspec validate add-findings-export --strict --no-interactive`.
