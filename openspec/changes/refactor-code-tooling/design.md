## Context

Measured on `main` at 8d8c17b (2026-10-05), in a clean worktree:

| Measure | Value |
|---|---|
| Python source | 15,647 lines in 37 modules. Largest: `runner/opencode.py` 1622, `cli.py` 1474, `runner/claude.py` 986, `review.py` 932, `hooks.py` 812, `refine.py` 746 |
| TypeScript | 3,723 lines, logger plugin and guard |
| Functions | 701 in all; 28 over 60 lines, 6 over 100. Longest: `cli._add_eval_parser` 122, `preflight.check` 116, `run.run_suite` 110, `OpenCodeBackend.execute` 110 |
| Complexity (ruff C901, report only) | 15 functions over 10; none over 13 |
| Import graph | no cycles. Function-local imports only to `collection` (from `hooks`, `install`, `adapters.dsh`). Fan-out: `cli` 27; `run`, `claude`, `review`, `refine`, `gate` 10–11 each |
| Pyright 1.1.411, default mode | 14 errors: 9 `runner/claude.py`, 3 `cli.py`, 1 `run.py`, 1 `score/derive.py`. All are Optional narrowing or Literal-list typing; no confirmed runtime bug |
| Tests | 702 pass in 21.5 s; line coverage 89%. Lowest: `run.py` 77%, `rubric.py` 79%, `opencode.py` 81%, `preflight.py` 81%, `logtools.py` 83%, `cli.py` 84%, `review.py` 84% |
| Slowest tests | `test_preflight.py`: 14 tests, 10.6 s, half of the suite's time. About 5.5 s of that is shutting down the test server (`serve_forever`'s default `poll_interval=0.5`, `tests/test_preflight.py:67`); the rest is intended timeouts (2 s, 1 s, 1 s) |
| Import time | `import wikiskill.cli` 113 ms, `import wikiskill.hooks` 65 ms, bare interpreter 12 ms. `wikiskill hook` goes through `cli` (`cli.py:329`) |
| Ruff extras, report only | TRY003 117, PERF401 17, PTH 8, FBT 3, ARG 2, N818 2, ERA 1, BLE 1. Only ARG and ERA point at something worth changing |
| Format drift | `tests/test_logtools.py`, `test_packaging.py`, `test_rawlog.py`. `test_compare.py` is already clean |

**Tooling state:**
- No CI, no pre-commit, no type checker configuration.
- `pytest` and `ruff` are an optional extra (`[project.optional-dependencies] dev`). A plain `uv sync`
  leaves them out, and `uv run ruff` then fails with `Failed to spawn: ruff`. The README says
  `uv sync --extra dev`, but nothing enforces it.
- The OpenCode logger and the guard are two separate bun packages, each with its own
  `bun test test` and `tsc --noEmit`. Nothing runs both.
- `tests/test_plugin_contract.py` runs the plugin through bun when bun is installed, and is skipped
  otherwise.

Step 4 (`add-dsh-pilot`) is in flight in another worktree. It runs live evals and may fix bugs in
`runner/`, `review.py`, `refine.py`, `gate.py` and the `eval`/`refine`/`proposal` commands in
`cli.py`.

## Goals / Non-Goals

**Goals**
- One command checks everything a commit should pass, and a fresh `uv sync` can run it.
- Each rule in one place where several modules use it: name matching, error handling, runner
  workdir preparation, and the meta-role client.
- Cheaper `wikiskill hook`, which runs on every Claude Code hook event.
- `cli.py` split so a command's parser and handler sit together.
- Slices small enough to merge one at a time. The early slices touch nothing step 4 touches.

**Non-Goals**
- Any behaviour change: commands, flags, output text, exit codes, log, run, wiki and proposal
  formats all stay as they are.
- Chasing TRY003 (117 hits) or PERF401: style rules with no payoff here.
- Rewriting the runners' normalisers. They are long because the harness streams are irregular, and
  their tests are fixture-driven.
- Sharing code between Python and TypeScript. The two loggers run in different processes and
  runtimes. Parity stays enforced by shared test cases, not shared code.
- Fixing the two silent no-ops this survey found (see Open Questions). Each is a behaviour change,
  for its own change.

## Decisions

Ranked by value over effort. Sizes: S is under half a day, M up to two days, L more. "Step 4" says
whether the item touches files step 4 may be editing.

### D1. Tooling baseline (S, no conflict with step 4)

**Evidence**
- `pyproject.toml:17-21` puts pytest and ruff in an optional extra.
- There is no `.github/` and no `.pre-commit-config.yaml`.
- `ruff format --check` flags three test files.

**Change**
1. Move the dev tools to a `[dependency-groups] dev` table, which `uv sync` installs by default.
   Add `pyright` there too: `uv run pyright` makes it a project dev tool rather than a harness tool.
2. Add `bin/check`, a POSIX shell script that runs:
   - `ruff check`;
   - `ruff format --check`;
   - `pyright` (from D8 on);
   - `pytest -q`;
   - bun test and tsc in each of `harness/opencode/plugin` and `harness/opencode/guard`, skipped
     with a printed notice when bun is absent.
3. Reformat the three drifted test files.

A pre-commit hook and a CI workflow are listed as separate, optional tasks. CI is outward-facing,
because it runs on every push, so it waits for the user.

**Risk:** none at runtime. **Guarded by:** `bin/check` itself.

### D2. Preflight test speed (S, no conflict)

**Evidence:** `tests/test_preflight.py:67` calls `serve_forever` with its default 0.5 s poll, which
adds about 0.5 s to the teardown of each of 11 tests.

**Change:** `serve_forever(poll_interval=0.05)`. That saves about 5 s of a 21.5 s suite. The tests
that time out on purpose stay as they are.

**Risk:** none. **Guarded by:** the same 14 tests.

### D3. One error base (S, `cli.main` only)

**Evidence**
- 20 exception classes are spread over 17 modules.
- `cli.main` lists twelve of them by hand (`cli.py:1452-1467`). `VerifierError`, `JudgeError`,
  `RubricError` and `AdapterError` are each caught where they are raised today, so nothing escapes
  now. But a new module's error is a traceback until someone adds it to that list.
- Two names break N818: `NothingToReview` and `UnsupportedSchemaVersion`.

**Change**
- `src/wikiskill/errors.py` defines `WikiskillError(Exception)`.
- Every module's base error derives from it, and `main` catches `WikiskillError` and
  `FileNotFoundError`.
- Names stay as they are: renaming would ripple into tests for no gain, and the N818 hits are
  recorded as accepted.

**Risk:** a module catching `Exception` around another module's call is unaffected, since the class
hierarchy only widens. **Guarded by:** `tests/test_cli.py`, plus one new test that every
`*Error` class in the package derives from `WikiskillError`.

### D4. Fast path for `hook` and `guard` (S, `cli.main` only)

**Evidence:** `wikiskill hook` imports all of `cli` (113 ms) to reach `hooks.run`, which alone needs
65 ms. Claude Code runs it on every hook event, and a hook measured 0.17 s in step 6.

**Change**
- In `main`, when `argv[0]` is `hook` or `guard`, import that module and dispatch at once, before
  `build_parser`.
- `--help` and argparse errors for both still go through the full parser: the fast path takes only
  the exact shapes `hook <event>` and `guard`.

**Risk:** the fast path could drift from the parser's definition. **Guarded by:**
`test_build_claude_code.py::test_a_hook_command_runs_in_a_minimal_non_interactive_shell`,
`test_hooks.py` and `test_guard.py`, plus a new test that both paths accept the same arguments. The
import time is measured before and after, and recorded.

### D5. Shared name matching: `wikiskill.names` (M, step 4 conflict: wait for it to merge)

**Evidence:** the "bare or qualified component name" rule is written out at least twelve times:
- `review.py:111`, `refine.py:269-273`, `corrections.py:179`, `compare.py:256`;
- `score/route.py:25-31`, which lowercases;
- `hooks.py:66-87`;
- `runner/opencode.py:1167` and `:1357`;
- `score/judge.py:103-105` and `:242`;
- `collection.py:366`;
- `review.py:828`, which strips a model provider.

Steps 7–9 each fixed a bug of this kind: `Collection.component`, the graph's `resolve`, and OpenCode's
`watchedSourcePath`.

**Change:** `names.py` defines:
- `bare(name)`;
- `qualify(plugin, name)`;
- `matches(name, wanted, *, fold_case=False)`, where an unqualified `wanted` matches any plugin's
  component of that bare name and a qualified one matches only itself (the rule `corrections.py:179`
  already uses);
- `model_id(model)`, which strips a provider.

Each site moves to it. A site whose rule differs keeps its own rule, made explicit with the
`fold_case` argument or with a comment that says why.

**Risk:** behaviour drift at a site whose rule differed on purpose. **Guarded by:** a table test of
`names` covering exact, bare, cross-plugin and case-folded matches; the existing suites for
`review`, `refine`, `compare`, `corrections`, `route`, `hooks` and `judge`; and the plugin contract
test.

### D6. Shared runner helpers (M, step 4 conflict: wait)

**Evidence**
- `runner/claude.py:36-44` imports `_bare`, `_bound`, `_git_init`, `_run_setup`, `_split_model` and
  `_string_field` from `runner/opencode.py`.
- `review.py:36` imports `runner.opencode._default_guard_plugin`.
- The two `prepare` methods repeat the same fixture-copy, setup and `git init` block
  (`opencode.py:335-360`, `claude.py:190-211`).
- `opencode._bound` (`:112`) is `redact.bound` (`redact.py:160`) without the length.
- `run.py:362-367` finds `run_options` and `isolation_proof` with `getattr`, because `Backend` does
  not declare them.

**Change**
- `Backend.prepare_workdir(unit, root)` in `runner/base.py` holds the shared block.
- The shared helpers move to `runner/common.py`, and `_bound` gives way to `redact.bound`.
- `run_options` and `isolation_proof` become `Backend` methods with defaults.
- The guard-plugin lookup moves to `paths`.

**Risk:** the order of seed, setup, `git init` and install matters (comments at `opencode.py:342` and
`:357`). The shared block keeps that order, and OpenCode's seed step stays before it. **Guarded
by:** `test_runner_opencode.py`, `test_runner_claude.py` (including the stand-in `claude` that
replays a capture), and `test_run.py`.

### D7. One meta-role client: `wikiskill.roles` (M, step 4 conflict: wait)

**Evidence**
- `review.py:637-850` holds `role_asker`, `endpoint_asker`, `harness_asker` and `harness_flatten`:
  about 210 lines of a 932-line module whose subject is digests and patterns.
- `refine` reaches them through `review` (`cli.py:810`, `:867`).
- `score/judge.py:231-260` makes the same chat-completions request with its own error handling.

**Change:** `roles.py` holds the role client and one `chat(endpoint, model, messages, *, timeout)`
call, which both `endpoint_asker` and `judge.ask_once` use. `review` and `refine` import from
`roles`.

**Risk:** error messages could change; the existing messages are kept word for word. **Guarded
by:** `test_review.py`, `test_refine.py`, `test_judge.py` and `test_preflight.py`.

### D8. Pyright in the check (S, partly conflicts with step 4)

**Change**
- Add `[tool.pyright]` with `typeCheckingMode = "basic"` and `include = ["src"]`, and fix the 14
  errors, all by narrowing or annotation.
- The `cli.py`, `run.py` and `derive.py` fixes can go first. The nine in `runner/claude.py` wait
  for step 4.
- Stricter modes are not worth it yet.

**Guarded by:** the full suite, since no fix changes behaviour.

### D9. Split `cli.py` into a package (L, conflicts with step 4's `eval`/`refine`/`proposal`: do last)

**Evidence**
- 1474 lines, 56 functions, fan-out 27.
- `build_parser` (`cli.py:1352-1444`) defines the collection, log, suite, build and install parsers
  inline. Ten other groups use `_add_*_parser` helpers placed far from their handlers.
- `_add_eval_parser` is 122 lines.
- Seven `return MISUSE` sites each print their own message.

**Change**
- `cli/__init__.py` holds `main`, the exit codes, error handling and D4's fast path.
- `cli/<group>.py` holds each group's `register(subparsers)` and its handlers, with heavy modules
  imported inside the handlers.
- `cli/_common.py` holds a `misuse(message)` helper and the shared `--collection` argument.
- The module `wikiskill.cli` and its `main` stay importable, because `[project.scripts]` and the
  tests use them.

**Risk:** argument definitions could drift during the move. **Guarded by:**
- `test_cli.py`;
- every test that drives `main`;
- a new test comparing `--help` output for every subcommand before and after, recorded once as a
  fixture and deleted after the move.

### D10. Small cleanups (S each)

- **Public helpers.**
  - `compare.runs(collection)` replaces `review.component_runs`'s loop (`review.py:114-126`) and
    `graph._all_runs` (`graph.py:191-195`).
  - `compare.rate` makes public the `_rate` that `gate.py:447` reaches into.
- **Unused code**, each checked by grep across `src` and `tests`:
  - `run.load_results` (`run.py:425`) and `gate.PROPOSED` (`gate.py:39`);
  - the unused `root` parameters at `wiki.py:374` and `runner/claude.py:240`;
  - the commented-out code at `runner/claude.py:155`.

  `rawlog.is_event_id` and `validate_file` are used only by tests, and stay as public API.
- **Parity cases.**
  - Move the redaction cases, now copied by hand between `tests/test_redact.py` and
    `harness/opencode/plugin/test/redact.test.ts`, into `tests/fixtures/parity/redact.json`, read by
    both.
  - Do the same for the guard's deny cases (`tests/test_guard.py` and
    `harness/opencode/guard/test`).
  - Add a test that the two pattern tables (`redact.py:46-70`, `redact.ts:41-60`) have the same
    regex sources, compared as text.

## Risks / Trade-offs

- **Moving code under a live pilot.** Step 4 may land runner, review or gate fixes at any time. The
  slices that touch those files (D5–D7, part of D8, D9 and part of D10) wait for it to merge, then
  rebase, rather than run in parallel.
- **A refactor that changes behaviour by accident.** Every slice runs `bin/check`. D4 and D9 add
  tests that compare the old and new argument surfaces. D5 adds a table test before any site moves.
- **Churn against value.** D9 is the largest item and makes no immediate user-visible gain beyond
  D4's latency. It stays last and can be dropped.

## Open Questions

**Two features accept input and then ignore it.** Both are out of scope here, and each needs a
decision:
- `[logging] retention_days` is validated (`collection.py:124`, `:310-313`), but nothing prunes logs.
- A suite task's `followups` is in the schema (`schemas/task-suite.schema.json:170`, "Scripted user
  turns sent after the first response") and parsed (`suite.py:157`, `:326`). Neither runner sends
  them.

Either the feature gets built, or `collection check` and `suite check` warn that the setting has no
effect yet.

**CI:**
- whether to add a GitHub Actions workflow;
- if so, which Python versions it covers;
- and whether bun runs in CI or only locally.
