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
- [ ] 1.5 (Optional, needs the user's approval) Add `.pre-commit-config.yaml` with ruff check and
  format.
- [ ] 1.6 (Optional, outward-facing, needs the user's approval) Add a GitHub Actions workflow
  running `bin/check` on Python 3.11 and 3.12, with bun.

## 2. Errors and the hook fast path (D3, D4; S; `cli.main` only)

- [ ] 2.1 Add `src/wikiskill/errors.py` with `WikiskillError`. Rebase each module's base error onto
  it (20 classes across 17 modules).
- [ ] 2.2 `cli.main` catches `WikiskillError` and `FileNotFoundError`, with the same message format
  and exit code.
- [ ] 2.3 Add a test that every exception class defined in the package derives from
  `WikiskillError`.
- [ ] 2.4 `main` dispatches `hook <event>` and `guard` before `build_parser`. Add a test that the
  fast path and the parser accept the same arguments. Record `import`/wall time for `wikiskill hook`
  before and after (baseline: 113 ms import, against 65 ms for `hooks` alone).

## 3. Type checking, outside the runners (D8, part one; S)

- [ ] 3.1 Add `[tool.pyright]` (basic mode, `include = ["src"]`), and run it from `bin/check`.
- [ ] 3.2 Fix the pyright errors in `cli.py` (544, 886, 889), `runner/run.py:363` and
  `score/derive.py:123` by narrowing. Add `# pyright: ignore` with a reason to the nine in
  `runner/claude.py` until slice 5.

## 4. Shared name matching (D5; M; after step 4 merges)

- [ ] 4.1 Add `src/wikiskill/names.py` (`bare`, `qualify`, `matches`, `model_id`), with a table test
  first: exact, bare, cross-plugin refusal, case folding, and provider stripping.
- [ ] 4.2 Move these sites to it, one commit per module, each keeping its current rule explicitly:
  - `review.py:111`, `:828`
  - `refine.py:269-273`
  - `corrections.py:179`
  - `compare.py:256`
  - `score/route.py:25-31`
  - `hooks.py:66-87`
  - `runner/opencode.py:1167`, `:1357`
  - `score/judge.py:103-105`, `:242`
  - `collection.py:366`
- [ ] 4.3 Run `bin/check`, and confirm the plugin contract test runs (not skipped) and passes.

## 5. Shared runner helpers (D6, D8 part two; M; after step 4 merges)

- [ ] 5.1 Add `Backend.prepare_workdir(unit, root)` with the fixture-copy, setup and `git init`
  block. `OpenCodeBackend.prepare` keeps its seed step before it.
- [ ] 5.2 Move `_split_model`, `_model_id`, `_string_field` and `_git_init`/`_run_setup` to
  `runner/common.py`. Replace `opencode._bound` with `redact.bound`. Move `_default_guard_plugin` to
  `paths`. `runner/claude.py` and `review.py` import no private name from `runner/opencode.py`.
- [ ] 5.3 Declare `run_options()` and `isolation_proof()` on `Backend` with defaults, and drop the
  `getattr` calls at `run.py:362-367`.
- [ ] 5.4 Fix the nine pyright errors in `runner/claude.py` and remove their ignores.

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
- [ ] 7.3 Add `tests/fixtures/parity/redact.json` and `guard.json`, read by the pytest and bun
  suites, plus a test that the Python and TypeScript redaction pattern sources are identical.

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
