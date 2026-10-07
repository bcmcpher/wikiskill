## Why

A study keeps only `run.json` and `results.jsonl` for each run (`findings bundle`). That is enough
to regenerate every rate, and it is deliberately small enough for git. Everything else a run
produced stays in `${XDG_DATA_HOME}/wikiskill/<collection>/evals/<run_id>/` on the machine that
ran it:
- the transcripts (`exports/`, `run.ndjson`, `stream.jsonl`);
- each unit's end state (`work/`, a git repository);
- the component text the run built (`built/`), and the earlier attempts a retry kept.

Those files are the evidence behind every claim a report makes beyond a rate. They are what showed
that a failed "no DOI" check was a labelled example rather than a fabrication, and that a model
asked not to think moved its reasoning into its reply. A finding read from transcripts cannot be
checked, or read again with a better question, once the machine is gone.

The same directories are also where nearly all of the disk goes. The development GB10 holds 133 GB
under `evals/`, in 128 runs. About 128 GB of it is each unit's private harness install: `config/`
holds 63 MB of OpenCode `node_modules` per unit, and `cache/` and `data/` hold more. Without
`config/` and `cache/` the same runs take 5.6 GB, and the transcripts, results and logs alone take
345 MB. Today there is no safe way to drop the bulk and keep the evidence, and no way to move a run
to another system.

## What Changes

- **`wikiskill archive pack`** writes one archive for one or more runs of a collection. It holds
  every file needed to read a run again, with a manifest of each file's SHA-256, and leaves out the
  per-unit harness install (`config/`, `cache/`, `state/`) and OpenCode's session database
  (`data/`), which `exports/` already holds in readable form. Optional parts: unit end states
  (`work/`, on by default), the collection's source snapshots and wiki records the runs cite, and
  the raw-log events the runs wrote.
- **`wikiskill archive verify`** checks an archive against its manifest without unpacking it.
- **`wikiskill archive unpack`** restores runs into a collection's `evals/` on any system. An
  unpacked run works with every read-only command: `report`, `leaderboard`, `compare`, `diff`,
  `findings bundle`, `review`. It is marked imported, and `eval --fill` refuses it.
- **`wikiskill archive prune`** frees disk on the machine that ran a run. It deletes only the parts
  `pack` leaves out, and only for runs whose verified archive it is given.
- **Secrets are checked at pack time.** Unit directories are not redacted today (`docs/data.md`).
  `pack` scans every text file with the raw log's redaction patterns and refuses to write an archive
  with a match unless told to redact the copy or to keep it.

## Impact

- New `run-archive` capability and spec.
- New `src/wikiskill/archive.py` and `cli/archive.py`; `RunLayout` gains the list of preservable
  parts; `run.json` readers accept a run marked `imported`.
- `eval --fill` refuses an imported run; `findings bundle` reads an unpacked run like any other.
- `docs/data.md` gains an archive section; `README.md` a short "Keeping runs" section.
- No change to any run already on disk. Archives are additive, and `prune` is never automatic.
