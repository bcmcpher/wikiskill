## 0. Minimal working core

**Starts after `refactor-code-tooling` slice 8 (the CLI package split) merges.** Rebase onto it
first. The command is a new `cli/diff.py` module, so it never touches the pre-split `cli.py`.

The smallest shippable slice is groups 1–4:
- `wikiskill diff <component> <a> <b>` with every reference form;
- text recovery from the current file, proposals, candidate copies and git history;
- the results half through `compare`;
- the saved report.

That alone diffs every version that exists today. Snapshots (group 5) make future versions
independent of git history, and `--list` (group 6) is a convenience. Both can follow in a second
pass. Deferred entirely: supporting-file diffs, snapshots from live logging, and pass rates in
`--list` (design Open Questions).

## 1. Version references

- [x] 1.1 Add `src/wikiskill/diff.py` with `resolve(collection, component, ref) -> str` for
  `current`, a hash prefix of 7 or more hex digits (with or without `sha256:`), `p-NNN`, `p-NNN^` and
  `run:<id>`.
  - A prefix is matched against hashes from proposals, run manifests and the current file. Raw-log
    hashes join once 6.1 lands.
  - It raises a `DiffError(WikiskillError)` naming the reference for no match, and listing every full
    hash for an ambiguous prefix.
  - Verify: a table test in `tests/test_diff.py` covering each form, unknown, ambiguous, and a
    proposal belonging to another component.
- [x] 1.2 Confirm that a candidate run's `run.json` records the proposal's `candidate_hash` for the
  component, as design D4 assumes (`gate.candidate_collection` points the component at
  `candidate-source/`). Verify: a test that builds a candidate collection and checks
  `run._component_versions` against `meta.json`.

## 2. Text recovery

- [x] 2.1 Add `recover(collection, component, hash) -> Recovered`, a text or an unavailable result
  with the places searched. It checks, in the order of design D3: snapshot (a no-op until group 5),
  current file, `wiki/proposals/*/rendered/`, `evals/*/candidate-source/`. It re-hashes each
  candidate before using it. Verify: tests for a hit in each place, and for a mismatched candidate
  being skipped.
- [x] 2.2 Add the git-history source: `git log --follow --name-only --format=%H` then
  `git show rev:path`, with `GIT_OPTIONAL_LOCKS=0`, stopping at the first match or after 500
  revisions. The repository comes from `refine.repository_of`. Verify:
  - a test repository with three revisions recovers the middle one;
  - `git status --porcelain` and `HEAD` are unchanged afterwards;
  - a rename is followed;
  - the limit message appears when it is hit.
- [x] 2.3 Build the text section: `refine.make_diff` on both texts, `refine.description_changed`,
  "identical" for equal hashes, and an unavailable message naming the version and the places
  searched. Verify: tests for body-only, description-changed, identical and one-side-unavailable.

## 3. Results selection

- [x] 3.1 Add `pick_runs(collection, component, hash_a, hash_b) -> (a, b) | Unavailable` per design
  D4, over `compare.runs`: group by `(suite, suite_hash, sorted tasks)`, take the latest group, then
  the newest run of each version. Verify: tests with two suites (the newest shared suite wins), no run
  for one version (the reason lists the other's runs), and a candidate run counting for its version.
- [x] 3.2 Support `--run-a`/`--run-b`: load the run, refuse it when its recorded hash differs (naming
  that hash), and report `compare.CompareError` for an incompatible explicit pair. Verify: a test for
  each refusal.
- [x] 3.3 Call `compare.compare(a, b, component=component)` for the chosen pair. Verify: the
  `Comparison` in the report equals a direct `compare.compare` on the same two runs.

## 4. Report and command

- [x] 4.1 Add the `Diff` model and its renderings: `diff.md` (header, text section, then
  `compare.render`), `diff.json` (nesting `Comparison.as_dict()`) and `text.diff` (left out when a text
  is unavailable). Verify: snapshot-style tests of the markdown headings and the JSON keys.
- [x] 4.2 Write the report to `evals/diff/<component with / and : as ->/<a7>_vs_<b7>/`. Verify: a
  test asserts the three files and their paths, and that nothing was written outside the collection's
  data directory.
- [x] 4.3 Add `cli/diff.py` with `register()`: `wikiskill diff <component> <a> <b> [--run-a ID]
  [--run-b ID]`, with heavy imports inside the handler. Reference errors use the misuse exit path,
  and an unavailable half exits `OK`. Verify:
  - CLI tests through `wikiskill.cli.main` for success, an unknown component and a bad reference;
  - `tests/test_entry.py` still shows the hook fast path never imports `wikiskill.diff`.

## 5. Source snapshots

- [x] 5.1 Add the snapshot helper: write `<data>/<collection>/sources/sha256-<hex>` through a
  temporary file and `os.replace`, skip it when present, and return the hash. Add the read side used
  by 2.1. Verify: tests for write-once, the content hashing to its key, and an unwritable directory
  raising a caught, reportable error.
- [x] 5.2 Call it from `run._component_versions`, reading each file once for both the hash and the
  snapshot. A failure becomes a run warning. Verify: an eval test with a fake backend leaves a
  snapshot per watched component; a read-only `sources/` still completes the run with a warning.
- [x] 5.3 Call it from refine's proposal write, for the base text and the rendered candidate, and
  skip it on `no_action`. Verify: a refine test asserts both snapshots exist, keyed by `source_hash`
  and `candidate_hash`.

## 6. Listing versions

- [x] 6.1 Add `versions(collection, component)`, built from snapshots, proposal metas, run manifests
  and raw-log `component_activated` events (filtered by name before decoding the rest). Each entry
  has a first-seen time, whether its text can be recovered, the proposals that produced or started
  from it, a run count, and whether it is current. Verify: a test with a base, two proposals and runs
  gives the expected order and fields.
- [x] 6.2 Add `wikiskill diff <component> --list`, which refuses version arguments alongside it.
  Verify: a CLI test of the table, and of the refusal.

## 7. Docs

- [x] 7.1 Document `wikiskill diff` in the README's command overview, and add the `sources/` and
  `evals/diff/` rows to `docs/data.md`. Verify: the README and docs mention both, and their examples
  run against the test fixture collection.

## 8. Verify

- [x] 8.1 `bin/check` passes, and the pytest count only grows.
- [x] 8.2 End-to-end on a scratch collection with a git-tracked skill: eval, edit, eval, then
  `wikiskill diff <skill> run:<first> current`. Both halves are shown, the source repository's
  `git status` is clean, and `wikiskill diff <skill> --list` shows two versions.
- [x] 8.3 `openspec validate add-skill-diff --strict --no-interactive`.
