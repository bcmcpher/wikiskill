## Why

Steps 1–9 added about 15.6k lines of Python under `src/wikiskill/` and 3.7k of TypeScript under
`harness/opencode/`, each step written against the last. The code is in reasonable shape:
- 702 tests pass in 21.5 s, with 89% line coverage.
- No import cycles.
- 15 functions are over ruff's complexity limit of 10, and none is above 13.
- Pyright finds 14 errors, none of them a confirmed runtime bug.

What has grown is friction:
- **No single check command, CI or type checker.** A fresh `uv sync` does not install pytest or ruff,
  so `uv run pytest` fails there.
- **One rule copied many times.** "Does this component name match that one" is written out in about
  twelve places, with slightly different rules. Three bugs in steps 7–9 were this kind of name
  mismatch.
- **Runners reach into each other.** The Claude Code runner imports five private helpers from the
  OpenCode runner. `review` imports the OpenCode runner's guard-plugin lookup.
- **`cli.py` is 1474 lines and imports every module.** Claude Code runs `wikiskill hook` on every
  hook event, so each event pays for importing the whole CLI.
- **`main` lists twelve exception types by hand.** Four more exist that it does not list.

This pass fixes that friction without changing behaviour. It is ordered so the slices that touch
nothing step 4 is changing land first.

## What Changes

- **Tooling.**
  - A `dev` dependency group, so `uv sync` installs pytest and ruff.
  - A `bin/check` script running ruff, pytest, pyright, and bun test and tsc for both OpenCode
    packages.
  - The three test files whose formatting drifted, reformatted.
  - The preflight tests' half-second server shutdown removed.
  - Optionally, a CI workflow that runs `bin/check`.
- **One error base.** `WikiskillError`, from which every module's error derives. `main` catches that
  one type, with the same message and exit code as now.
- **A fast path for `wikiskill hook` and `wikiskill guard`.** They are dispatched before the full
  parser and its imports are loaded.
- **Shared name matching.** `wikiskill.names`, holding the bare, qualified and matches rules, used in
  every place that now writes them out by hand.
- **Shared runner helpers.** Working-directory preparation and the small helpers move to
  `runner/base.py` or a new `runner/common.py`. `run_options` is declared on `Backend`.
- **One meta-role client.** `wikiskill.roles` takes over the maintainer and proposer client from
  `review.py`, and the judge's chat request.
- **A `cli/` package.** One module per command group, each registering its own parser and handlers.
  Heavy modules are imported lazily.
- **Small cleanups.**
  - A public `compare.runs()` and `compare.rate()`.
  - Unused code removed.
  - Pyright set to basic mode, with its 14 errors fixed.
  - Shared redaction and guard test cases for Python and TypeScript.

No requirement changes. Every observable behaviour stays as it is: commands, output, exit codes,
log and run formats. The existing tests guard each slice, and the slices add tests only where a
rule moves.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

None. This change has no spec deltas; `.openspec.yaml` sets `skip_specs: true`.

## Impact

- **Code:** `pyproject.toml`, a new `bin/check`, `tests/` (formatting, the preflight server), and new
  `src/wikiskill/errors.py`, `names.py` and `roles.py`. It splits `cli.py` into `cli/`, and makes
  small edits across `runner/`, `review.py`, `refine.py`, `gate.py`, `compare.py`, `graph.py` and
  `corrections.py`.
- **Conflict with step 4:** `add-dsh-pilot` runs live evals and may fix bugs in the runners,
  `review`, `refine`, `gate` and the `eval`/`refine`/`proposal` commands. Slices 1–3 touch none of
  those; the later slices wait until step 4 merges (see tasks.md).
- **Outward-facing:** a CI workflow would run on every push to GitHub. It is a separate task, done
  only if the user wants it.
