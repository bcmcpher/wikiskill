## Context

See proposal.md for why. What exists today:

- A version of a component is only its `source_hash`: `sha256:` plus the hex digest of the main
  file's bytes (`rawlog.file_hash`). It is recorded in raw-log activations, in `run.json`
  `components[]` (`runner/run.py` `_component_versions`), in proposal `meta.json` (`source_hash`,
  `candidate_hash`), and in wiki pattern `source_hashes`. There are no version numbers.
- No text is kept by hash. A version's text exists only in the live file, a proposal's
  `wiki/proposals/p-NNN/rendered/<file>`, a candidate run's `evals/<run>/candidate-source/` (built by
  `gate.candidate_collection`, so that run's manifest records the candidate hash), or the
  collection repository's git history, when there is one.
- `compare.compare(a, b, component=)` already does the whole results analysis for two runs and
  raises `CompareError` on a suite, task or `suite_hash` mismatch. `compare.runs(collection)` lists
  finished runs, oldest first. `compare.render` gives the markdown.
- `refine.make_diff` builds a unified diff, and `refine.description_changed` compares frontmatter
  descriptions.
- After `refactor-code-tooling` slice 8, each command group is a `cli/<group>.py` module with
  `register()`, and handlers import heavy modules lazily.

## Goals / Non-Goals

**Goals:**
- Read-only over everything except its own report and the new snapshot store.
- Reuse `compare` for the results half. No second statistics path.
- Work for versions from before this change, as far as their text can still be found.

**Non-Goals:**
- Diffing a component's supporting files (`references/`, scripts). `source_hash` covers only the
  main file, so that is the only file a version names.
- Snapshots from live logging. The OpenCode plugin and Claude Code hooks stay hash-only. Writing on
  every activation would add a write to a fail-open path in two languages, for text that git
  history usually has.
- Back-filling snapshots when `diff` recovers an old text from git. `diff` writes only its report.
- Version numbering or aliases. `--list` gives the order.

## Decisions

**D1. A version is its `source_hash`; references resolve to one.** Every store already keys on the
hash, so `current`, prefixes, `p-NNN`, `p-NNN^` and `run:<id>` are resolved to a full hash up front.
After that, the rest of the command never sees the reference forms. Alternative: sequential
`v1, v2, …` per component. Rejected, because the numbering would need its own store and would
differ between machines, while hashes are the same everywhere a run is pooled.

**D2. Snapshot store: `<data>/<collection>/sources/sha256-<hex>`.** One plain file per hash, written
through a temporary file plus `os.replace`, and skipped when present. It is content-addressed, so
it is write-once and deduplicated. A `diff.snapshot(collection, text_bytes) -> hash` helper, or one
in a small `sources.py`, is called from `run._component_versions`, which already reads each file,
and from refine's proposal write, for the base text and the rendered candidate. Failures are caught
and become a warning. Alternatives considered:
- per-run copies in `evals/<run>/`: they duplicate the text on every run, and can't be found by
  hash without scanning;
- commits in the wiki's git repository: they add a commit per run, and couple a data store to the
  wiki's history.

**D3. Text recovery order.** The order is snapshot, current file, proposal `rendered/`,
`evals/*/candidate-source/`, then git history. That is cheapest first, and the most authoritative
before the slowest. Every candidate is re-hashed against the wanted hash before use.
- Git history: `git -C <repo> log --follow --name-only --format=%H -- <relpath>` gives
  (revision, path at that revision) pairs; `git show <rev>:<path>` gives the bytes.
- The scan stops at the first match or after 500 revisions, and the "unavailable" message says when
  it stopped at the limit.
- It never checks out, stashes or branches. Git runs with `GIT_OPTIONAL_LOCKS=0`, so it does not even
  refresh the index.
- The repository comes from `refine.repository_of`.

**D4. Choosing runs.** Take `compare.runs`, and keep runs whose `hashes()[component]` equals each
version. Group them by `(suite, suite_hash, sorted tasks)`. Among groups holding runs of both
versions, choose the one whose newest run is latest, and pair the newest run of each version in it.
Run ids are ULIDs, so their order is time order. Candidate runs (`manifest.proposal`) are eligible,
because they are the only runs of a candidate version. `--run-a`/`--run-b` bypass the choice but
still check the recorded hash. `compare.compare` is then called with `component=`. Its
`CompareError` can't occur for a chosen pair, but is still caught and reported for explicit runs.

**D5. One report model, three renderings.** A `Diff` dataclass holds both references and hashes, a
text result (`diff` or `unavailable` plus places searched, `description_changed`), and a results
result (a `compare.Comparison` and both run ids, or an `unavailable` reason plus runs found). The
renderings:
- `diff.md`: a header, the text section, then `compare.render` output;
- `diff.json`: the model, with `Comparison.as_dict()` nested;
- `text.diff`: the unified diff alone.

The output directory is `evals/diff/<component>/<a7>_vs_<b7>/`, next to `evals/compare/`. In the
component name, `/` and `:` become `-`, as wiki component pages already do.

**D6. `--list` sources.** `--list` reads, in this order:
1. snapshot file names;
2. proposal `meta.json` files;
3. run manifests;
4. raw-log `component_activated` events for that component (`rawlog.log_files`).

A version is shown under its first-seen time: its earliest run, proposal or event. The raw-log scan
is the slow part, so it reads only `component_activated` lines whose name matches before decoding
the rest.

**D7. CLI.** A `cli/diff.py` module with `register()`, following slice 8's layout. Reference errors
and missing components use the package's `misuse` exit path, and an unavailable half is not an
error (exit `OK`). `wikiskill diff` imports `diff` only inside its handler, so the hook fast path
and `--version` are untouched.

## Risks / Trade-offs

- [The snapshot store holds unredacted skill text] → It is the user's own source, which already sits
  unredacted in their repository and in candidate copies. It stays in the per-user data directory, and
  docs/data.md says so.
- [The git history scan is slow on long histories] → It is bounded at 500 revisions, stops at the
  first match, and says when it was cut short. Snapshots make the scan rare for versions created after
  this change.
- [A renamed or moved component file breaks history lookup] → `--follow` handles renames inside one
  repository. Beyond that, the version is reported unavailable, with the places searched.
- [CRLF, or editor normalisation, changes bytes but not meaning] → Hashes are over exact bytes, as
  `source_hash` already is. A recovered text that differs only in line endings is not that version,
  and is skipped.
- [Runs of a version on different suites can't be compared] → The report lists the runs per version
  and says no comparable pair exists, rather than comparing across suites.
- [Snapshot writes in the run's manifest step] → Each write is one small file per watched component
  per new hash, and a failure is only a warning, so a run never fails because of it.

## Migration Plan

Additive. No existing file changes shape. Versions from before the change rely on proposals, candidate
copies and git history; they are listed as text unavailable when none of those has them. Rollback
removes the command and the snapshot calls. The `sources/` directory can be deleted at any time, at
the cost of falling back to the slower sources.

## Open Questions

- Should `--list` also show each version's pooled pass rate? It is cheap once runs are loaded, and
  can be added without changing the report or the snapshot store.
- Should `docs/data.md`'s storage table gain the `sources/` row now, or when this change is archived?
