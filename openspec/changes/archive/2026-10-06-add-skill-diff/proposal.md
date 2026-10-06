## Why

Refining a skill produces a run of versions, each known only by its `source_hash`, and nothing shows
what changed between two of them. `wikiskill compare` compares two runs, but the user has to find the
runs, and it never shows the text. To decide whether an iteration helped, the user needs both, for a
named pair of versions, in one report.

## What Changes

- New `wikiskill diff <component> <version-a> <version-b>` command. A version is `current`, a
  `source_hash` prefix, a proposal (`p-003` is its candidate, `p-003^` the version it was made from),
  or `run:<run-id>` (the component's hash in that run).
- **Text diff**: a unified diff of the component's source between the two versions, with a note when
  the frontmatter `description` changed (that changes routing, not just behaviour).
- **Results diff**: the existing `compare` analysis (pass rates with Wilson intervals, direction,
  tool choice, timeouts as failures), run on the newest pair of finished runs that evaluated each
  version on the same suite content. `--run-a`/`--run-b` choose runs explicitly.
- Either half that cannot be produced is reported as unavailable with the reason; the other half is
  still shown. The command never runs an evaluation.
- `wikiskill diff <component> --list` lists the known versions of a component: hash, where its text
  is available, proposals that produced it, and the runs that evaluated it.
- The report goes to stdout and to `evals/diff/<component>/<a>_vs_<b>/` as `diff.md`, `diff.json` and
  `text.diff`.
- **Source snapshots**: eval runs, and refine when it writes a proposal, store each component's text
  by content in `<data>/<collection>/sources/<sha256>`, so later diffs do not depend on the
  collection's git history. Older versions fall back to the proposal's rendered copy and then to the
  collection repository's git history.

## Capabilities

### New Capabilities
- `version-diff`: the `wikiskill diff` command: resolving version references, recovering a version's
  text, choosing comparable runs, the combined text and results report, and `--list`.

### Modified Capabilities
- `eval-runner`: a run stores the source text of every component it records a `source_hash` for.
- `refinement-proposal`: writing a proposal stores the base and candidate text as source snapshots.

## Impact

- New `src/wikiskill/diff.py`, and a `diff` command group in the CLI package.
- `runner/run.py` (manifest step) and `refine.py` (proposal write) call one new snapshot helper.
- Reuses `compare.runs`, `compare.compare`, `compare.render`, and refine's `make_diff` and
  `description_changed`.
- New data: `<data>/<collection>/sources/` (content-addressed, deduplicated) and
  `evals/diff/`. Nothing is written into the collection's source repository; reading its git history
  is read-only.
- Depends on `refactor-code-tooling` slice 8 (the CLI package split). Implementation starts after it
  merges, so the new command is written as a `cli/<group>.py` module from the start.
- Live logging (the OpenCode plugin and Claude Code hooks) is unchanged: it keeps recording only the
  hash.
