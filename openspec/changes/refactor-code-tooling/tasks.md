## 0. Order

Each slice merges on its own and passes `bin/check` (or, before slice 1 lands, `uv run pytest` and
`ruff check`).

- **Slices 1–3 first.** They touch nothing step 4 (`add-dsh-pilot`) may be editing. Slice 1 is the
  first to do.
- **Slices 4–8 wait** until step 4 merges, then rebase.
- **Slice 8 (the CLI split) is last** and optional.

## 1. Tooling baseline — FIRST SLICE (D1, D2; S; no conflict with step 4)

- [x] 1.1 Move `pytest` and `ruff` from `[project.optional-dependencies] dev` to
  `[dependency-groups] dev`, and add `pyright`. Update the README's `uv sync --extra dev`. Check: in
  a fresh clone, `uv sync && uv run pytest -q && uv run ruff check` works.

  Done 2026-10-05. The group pins `pyright[nodejs]>=1.1.411`: its `nodejs` extra brings Node as a
  wheel, so pyright downloads nothing at first run and needs no Node on the machine. The lockfile
  adds only pyright 1.1.414, nodejs-wheel-binaries and nodeenv; pytest and ruff keep their locked
  versions. `[tool.pyright] include = ["src"]` scopes the report to the source. Unscoped, it also
  checked `tests/`, and gave 57 errors (43 in tests) against the source's 14. The README's
  Development section now says `uv sync` then `bin/check`.

  Fresh clone of this branch in `/tmp`: `uv sync` exited 0, then `bin/check` exited 0. The clone was
  then deleted.
- [x] 1.2 Add `bin/check`. It runs, in order:
  - `ruff check`;
  - `ruff format --check`;
  - `pytest -q`;
  - `bun test test` and `bunx tsc --noEmit` in `harness/opencode/plugin` and in
    `harness/opencode/guard`. Without bun, print that this part was skipped and carry on.

  Exit non-zero on the first failure.

  Done. A POSIX `sh` script, run from any directory. The steps:
  1. `uv run --frozen ruff check` and `ruff format --check`.
  2. `pyright`, report-only: it prints its summary and never fails the run, until slice 3 fixes the
     14 errors.
  3. `pytest -q`.
  4. For each OpenCode package: `bun install --frozen-lockfile` when `node_modules` is missing,
     then `bun test test` and `bun run typecheck` (`tsc --noEmit`).

  bun is looked for on PATH, then `~/.bun/bin`, then `~/.claude-node-tools/bin`, as
  `test_plugin_contract.py` does.

  Fresh-clone run: ruff passed; 209 files already formatted; pyright reported 14 errors, as
  intended; 702 passed; the plugin's 178 bun tests and the guard's 19 passed; both type checks passed.
- [x] 1.3 Run `ruff format` on `tests/test_logtools.py`, `tests/test_packaging.py` and
  `tests/test_rawlog.py` only. Done: 3 files reformatted, and `ruff format --check` is clean across
  the repository.
- [x] 1.4 `tests/test_preflight.py:67`: `serve_forever(poll_interval=0.05)`. Record the suite time
  before and after (baseline: 21.5 s overall, 10.6 s for this file).

  Done. The design's 21.5 s baseline was measured under coverage. Measured again here without it,
  on the same machine:
  - `tests/test_preflight.py`: 10.63 s before, 4.74 s after.
  - The whole suite: 15.78 s and 17.66 s before; 11.16 s and 11.55 s after.

  The 4.7 s left is the tests' deliberate timeouts.
- [x] 1.4a Fix: from the main checkout, `bin/check` failed `ruff format --check`. Ruff walked
  `.claude/worktrees/*`, which holds other agents' checkouts of older commits; there it found 138
  files and 3 that needed reformatting. `[tool.ruff] extend-exclude = [".claude"]` fixes it.
  Neither of the other two tools wanders there: pytest collects only `testpaths = ["tests"]`, which
  is 702 tests with 0 under `.claude`, and pyright reads only `include = ["src"]`, which is 37
  files.

  Checked in the main checkout, read-only, using its existing `.venv`:
  - with the exclude, `ruff check --show-files` lists 0 files under `.claude`;
  - `ruff format --check` gives "197 files already formatted".

  The literal `bin/check` from the main checkout can only run once this merges. Until then, the
  main checkout's `pyproject.toml` lacks the exclude.

  Reproduced in a fresh clone with a fake `.claude/worktrees/stale/src/bad.py` (unformatted, with
  an unused import). `bin/check` exited 0, and ruff with `--isolated` still flagged the file, which
  shows the exclude is what skips it.
- [x] 1.5 (Optional, needs the user's approval) Add `.pre-commit-config.yaml` with ruff check and
  format.

  Approved and done 2026-10-05. `pre-commit>=4.0` is in the dev group; 4.6.2 is locked. Three
  `repo: local` hooks run through `uv run --frozen`, so they use the locked tools and fetch no hook
  repository:
  - `ruff check --force-exclude` on staged Python;
  - `ruff format --check --force-exclude` on staged Python;
  - `bin/check-data`, which parses staged JSON and YAML, multi-document YAML included.

  Tests and bun stay out of the hooks and in `bin/check`.

  `uv run pre-commit run --all-files` passed all three. `bin/check-data` rejected a broken YAML
  file and a JSON file with a trailing comma, and accepted a two-document YAML file.

  The README documents `uv run pre-commit install`. The hook is not installed anywhere. Worktrees
  share the main checkout's `.git/hooks`, which the README says, and that directory holds only
  git's samples.
- [x] 1.6 (Optional, outward-facing, needs the user's approval) Add a GitHub Actions workflow
  running `bin/check` on Python 3.11 and 3.12, with bun.

  Approved and done 2026-10-05. `.github/workflows/check.yml`:
  - runs on `pull_request` and on `push` to `main`, on `ubuntu-latest`, with
    `permissions: contents: read` and a 20-minute timeout;
  - cancels a superseded run on the same ref;
  - runs a matrix of Python 3.11 and 3.12;
  - pins `actions/checkout@v7` and `oven-sh/setup-bun@v2` with bun 1.4.2;
  - pins `astral-sh/setup-uv@v10.2.0` exactly, because setup-uv publishes no floating major tag
    from v8 on (checked with `gh api .../matching-refs/tags/v`). Its uv cache is keyed on
    `uv.lock`;
  - runs `uv sync --locked`, then `bin/check`.

  `uvx --from actionlint-py actionlint` exited 0. The inputs the workflow uses were checked against
  the pinned versions' `action.yml`.

  What the runner lacks:
  - **Ollama, OpenCode, Claude Code.** No test needs them. A run with
    `env -i PATH=<venv>:<bun>:/usr/bin:/bin` (no HOME, so no global git config, and none of those
    tools) passed all 702.
  - **A git identity.** That same run first failed 5 tests (`test_graph`'s build, `test_refine`'s
    patch, and three `test_wiki` tests), because the wiki, the graph and `apply --branch` commit, and
    git had no identity. An autouse `git_identity` fixture in `tests/conftest.py` now sets
    `GIT_AUTHOR_*`/`GIT_COMMITTER_*` for every test, so the tests no longer depend on the machine.
    It is not a CI-only workaround.
  - **The data-science-harness checkout.** Two tests skip themselves when it is absent: one in
    `test_adapter_dsh`, one in `test_graph`.

  The fresh-clone runs (`uv sync --locked --python 3.11` and `3.12`, then `bin/check`) both exited
  0, with 702 passed, 178 and 19 bun tests passed, and both type checks passed.

## 2. Errors and the hook fast path (D3, D4; S; `cli.main` only)

- [x] 2.1 Add `src/wikiskill/errors.py` with `WikiskillError`. Rebase each module's base error onto
  it (20 classes across 17 modules).
  Done 2026-10-05. The 16 module base errors derive from it, so all 20 classes do.
- [x] 2.2 `cli.main` catches `WikiskillError` and `FileNotFoundError`, with the same message format
  and exit code.
  Done: one `(WikiskillError, FileNotFoundError)` replaces the list of twelve, with the same
  `error: {exc}` and `FAILED`. `VerifierError`, `JudgeError`, `RubricError` and `AdapterError`,
  which would have escaped as tracebacks, now print the same way.
- [x] 2.3 Add a test that every exception class defined in the package derives from
  `WikiskillError`.
  Done: `tests/test_entry.py` walks the package and finds 21 classes, the base included.
- [x] 2.4 `main` dispatches `hook <event>` and `guard` before `build_parser`. Add a test that the
  fast path and the parser accept the same arguments. Record `import`/wall time for `wikiskill hook`
  before and after (baseline: 113 ms import, against 65 ms for `hooks` alone).
  Done, in a new `wikiskill.entry` rather than in `cli.main`: the console script imported all of
  `cli` before `main` ran, so a fast path there saved nothing. The console script is now
  `wikiskill.entry:main`; run `uv sync` to rewrite an existing one. Tests check that the parser
  sends every fast-path shape to the same handler, that 8 other shapes reach the parser, and that a
  hook event never imports `wikiskill.cli`. Median wall time: `wikiskill hook Stop` 86 → 50 ms,
  `wikiskill guard` 86 → 14 ms. Most of what is left is importing `hooks` (39–46 ms).

## 3. Type checking, outside the runners (D8, part one; S)

- [x] 3.1 Add `[tool.pyright]` (basic mode, `include = ["src"]`), and run it from `bin/check`.
  Done 2026-10-05. `runner/claude.py` and `runner/run.py` are excluded until slice 5 rewrites them,
  and pyright is now a failing step of `bin/check`: `0 errors, 0 warnings, 0 informations`.
- [x] 3.2 Fix the pyright errors in `cli.py` (544, 886, 889), `runner/run.py:363` and
  `score/derive.py:123` by narrowing. Add `# pyright: ignore` with a reason to the nine in
  `runner/claude.py` until slice 5.
  Done for `cli.py` and `score/derive.py`; the `runner/` errors moved to slice 5 (5.4), which also
  removes the exclusion. `cli.py:544` and `:886/889` assert invariants already enforced
  (`_eval_misuse`, a patch proposal's directory); `derive.py:123` filters the `None` rates
  `_paired` rules out. 14 errors before, 10 after the fixes, 0 with the exclusion. 703 passed.

## 4. Shared name matching (D5; M; after step 4 merges)

- [x] 4.1 Add `src/wikiskill/names.py` (`bare`, `qualify`, `matches`, `model_id`), with a table test
  first: exact, bare, cross-plugin refusal, case folding, and provider stripping.
- [x] 4.2 Move these sites to it, one commit per module, each keeping its current rule explicitly:
  - `review.py:111`, `:828`
  - `refine.py:269-273`
  - `corrections.py:179`
  - `compare.py:256`
  - `score/route.py:25-31`
  - `hooks.py:66-87`
  - `runner/opencode.py:1167`, `:1357`
  - `score/judge.py:103-105`, `:242`
  - `collection.py:366`
- [x] 4.3 Run `bin/check`, and confirm the plugin contract test runs (not skipped) and passes.

  Done 2026-10-05, one commit per module after the module and its 23-case table test
  (`tests/test_names.py`). `build.py:258` also moved. Kept where they are: `opencode._split_model`
  and `_model_id` (slice 5; `_bare` now calls `names.bare` and goes when `claude.py` stops importing
  it), `cli.py:124`, `Component.plugin`, `compare.py:312` (a path) and `hooks.qualified`. Rules that
  differ today stay different, each commented at its site:
  - both sides bare, so two plugins' components match: review evidence, `refine._notes`,
    `opencode._watched`;
  - `names.matches`, where a qualified name matches only itself: `corrections`, `compare`;
  - bare, stripped and lowercased: `route.bare`, judge self-judging;
  - a model's last segment for an endpoint payload (review, judge) against provider-only stripping
    (`names.model_id`: `compare._event_model`, `refine.model_names`, the review evidence key);
  - `hooks.watched_name` stays glob-based; `collection._model_forms` keeps both lowercased forms.
  `names` was already a local in `corrections.py` and `compare.py`; those locals were renamed.
  After rebasing onto slices 2 and 3, `bin/check` exits 0 with 743 passed and pyright clean;
  `test_plugin_contract.py` ran all 14 tests, none skipped.

## 5. Shared runner helpers (D6, D8 part two; M; after step 4 merges)

- [ ] 5.1 Add `Backend.prepare_workdir(unit, root)` with the fixture-copy, setup and `git init`
  block. `OpenCodeBackend.prepare` keeps its seed step before it.
- [ ] 5.2 Move `_split_model`, `_model_id`, `_string_field` and `_git_init`/`_run_setup` to
  `runner/common.py`. Replace `opencode._bound` with `redact.bound`. Move `_default_guard_plugin` to
  `paths`. `runner/claude.py` and `review.py` import no private name from `runner/opencode.py`.
- [ ] 5.3 Declare `run_options()` and `isolation_proof()` on `Backend` with defaults, and drop the
  `getattr` calls at `run.py:362-367`.
- [ ] 5.4 Fix the pyright errors in `runner/claude.py` and `runner/run.py:363`, and remove their
  `exclude` from `[tool.pyright]`.

## 6. Meta-role client (D7; M; after step 4 merges)

- [ ] 6.1 Add `src/wikiskill/roles.py` with `role_asker`, `endpoint_asker`, `harness_asker`,
  `harness_flatten` and one `chat()` request. Keep the error messages word for word.
- [ ] 6.2 `review`, `refine`, `cli` and `score/judge.ask_once` use it, and `review.py` drops about
  210 lines.

## 7. Small cleanups (D10; S each; after step 4 merges)

- [ ] 7.1 Add `compare.runs(collection)` and a public `compare.rate`. Use them in `review.py:114-126`,
  `graph.py:191-195` and `gate.py:447`.
- [ ] 7.2 Remove `run.load_results`, `gate.PROPOSED`, the unused `root` parameters (`wiki.py:374`,
  `runner/claude.py:240`) and the commented-out code at `runner/claude.py:155`.
- [x] 7.3 Add `tests/fixtures/parity/redact.json` and `guard.json`, read by the pytest and bun
  suites, plus a test that the Python and TypeScript redaction pattern sources are identical.
  Done 2026-10-05. `tests/fixtures/parity/redact.json` (38 cases) and `guard.json` (56) are read by
  `tests/test_parity.py` and by `harness/opencode/{plugin,guard}/test/parity.test.ts`; a
  pattern-table test compares `redact.py` with `redact.ts`. Five known divergences are recorded,
  each with both sides' current output: `\b` after a non-ASCII letter (Python leaves the secret
  unredacted), an env value the marker contains (TypeScript re-replaces up to 101 times), `bound()`
  length outside the BMP, and step budgets `"1e2"`/`"0x10"` (TypeScript reads a number). The
  per-side tests are kept; removing them needs the user's approval. `bin/check`: pytest 840, bun
  216 and 75.


## 8. CLI package (D9; L; last, optional)

- [ ] 8.1 Record `--help` for every subcommand as a temporary fixture.
- [ ] 8.2 Split `cli.py` into `cli/__init__.py` (main, exit codes, errors, the fast path),
  `cli/_common.py` (`misuse()`, the shared `--collection`) and one `cli/<group>.py` per command
  group with `register()` and its handlers. Import heavy modules inside handlers.
- [ ] 8.3 Check that `--help` matches the fixture for every subcommand. Then delete the fixture.
- [ ] 8.4 Measure `wikiskill --version` and `wikiskill hook` time again.

## 9. Verify

- [ ] 9.1 Each slice: `bin/check` passes, and the test count does not drop.
- [ ] 9.2 `openspec validate refactor-code-tooling --strict --no-interactive`.
