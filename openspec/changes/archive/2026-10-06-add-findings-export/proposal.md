## Why

A study's results live only in the XDG data directory, so a report cannot be regenerated or checked
from git. The findings are markdown tables spread across several outputs, which are copied into a
document by hand. Nothing produces a document that can be uploaded to Google Docs or Slides. Before
the DSH sweep adds about twenty models' runs, each study needs:
- runs tracked in the repo
- tables, data and figures made from those runs
- versioned markdown that builds to `.docx` and `.pptx`

## What Changes

- **Study manifest.** A `findings.toml` per study names its runs, groups them by role (sweep,
  versions, routing, …), and declares the tables to make: leaderboard, version board, per-judge
  report.
- **`wikiskill findings bundle <study>`** copies each named run's `run.json` and `results.jsonl` into
  the study directory. It never copies transcripts or units. Every number can then be regenerated
  from git alone.
- **`wikiskill findings tables <study>`** renders the declared tables from the bundle:
  - markdown fragments, each in a full and a slide-sized form
  - one long-format CSV
  - `--check`, which fails when a committed fragment is stale
- **`bin/figures`**, a PEP 723 script run with `uv run --script`, draws PNG figures from the CSV:
  pass rates with intervals per model, and lift per version. Its plotting library never becomes a
  project dependency.
- **`bin/build-docs`** expands fragment includes in a study's `report.md` and `slides.md`, then runs
  pandoc into `.docx` and native, editable `.pptx`. Reference templates are optional. The office
  files are build outputs and are gitignored. Pandoc is the user's to install; a missing pandoc is
  stated, never worked around.
- **A shared "how wikiskill works" section** that any study's report and slides include. It covers
  the conditions, the verifiers, the Wilson intervals, the gate, the version board and the judges.
- **DSH pilot first.** `docs/pilots/dsh/` holds the study, with drafts of `report.md` and `slides.md`
  from the v1 and p-002 runs. They fill in as the sweep lands.
- **Refactors, behavior-preserving except where stated:**
  - `present.py`: one implementation of rate, percent and markdown-table formatting, replacing five
    copies in `compare`, `leaderboard`, `version_board`, `gate` and `report` that disagree on the
    `CI` prefix and the missing-value dash
  - `report.py` takes its pass rates, outcome counts and medians from `leaderboard.pool([run])`
    instead of a second aggregation path
  - one module that decides what a tool call activated or delegated to, shared by the OpenCode and
    Claude Code runners, the judge's `delegations()` and the hook logger

## Capabilities

### New Capabilities
- `findings-export`: study manifests, bundling runs into the repo, tables and CSV from the bundle,
  figures, document builds to office formats, and one rate format across every output

### Modified Capabilities
- None. The refactors keep every requirement as written. The one visible change, a single rate
  format, is stated in `findings-export`.

## Impact

- New: `src/wikiskill/findings.py`, `src/wikiskill/cli/findings.py`, `src/wikiskill/present.py`,
  `src/wikiskill/calls.py`, `bin/figures`, `bin/build-docs`, `docs/findings/`,
  `docs/pilots/dsh/`.
- Changed: `compare.py`, `leaderboard.py`, `version_board.py`, `gate.py`, `report.py`,
  `runner/opencode.py`, `runner/claude.py`, `score/judge.py`, `hooks.py`, `.gitignore`, README.
- External tools: pandoc on `PATH` for `bin/build-docs`, installed by the user. `uv` fetches the
  figures script's plotting library on demand. Neither becomes a project dependency.
- Depends on `add-pilot-reporting` (archived): the catalogue, the panels and the per-judge report.
- Feeds `add-dsh-pilot`: its section 6 report tasks write into `docs/pilots/dsh/report.md` and
  `slides.md`, and its sweep log becomes the study's run list.
- `docs/pilots/dsh.md` moves to `docs/pilots/dsh/report.md`.
