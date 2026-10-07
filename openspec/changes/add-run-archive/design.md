## Context

A run directory (`docs/data.md`, "Evaluation runs") holds `run.json`, `results.jsonl`, an optional
`results.superseded.jsonl`, the reports, `preflight/`, an optional `candidate-source/`, and one
directory per unit. An OpenCode unit holds its own `config/`, `data/`, `state/`, `cache/`,
`exports/`, `run.ndjson`, `sessions.json`, `setup.log`, `built/` and `work/`; a Claude Code unit
holds `claude/settings.json`, `stream.jsonl` and `work/`. A retried unit leaves
`<slug>.attempt-<N>/` beside it.

Measured on the 128 runs on the development GB10 (133 GB):

| part | per unit | all runs | needed to read a run again |
|---|---|---|---|
| `config/` (harness install, `node_modules`) | 63 MB | ~120 GB | no: rebuilt by any run |
| `cache/` | 9.5 MB | ~8 GB | no |
| `data/` (OpenCode session database) | 3.4 MB | ~5 GB | no: `exports/` has the sessions |
| `state/`, `built/` | < 0.2 MB | small | `built/` yes: the text that ran |
| `work/` (end state, a git repository) | 0.3 MB | ~0.3 GB | yes, for re-verifying |
| `exports/`, `run.ndjson`, `sessions.json`, `setup.log` | < 0.1 MB | ~0.3 GB | yes |

## Goals / Non-Goals

**Goals:**
- Everything needed to re-read, re-verify and re-report a run survives the machine that made it.
- An archive proves its own integrity, and says what it left out.
- An archive unpacks on a system with a different user, home directory and harness version.
- The bulk can be reclaimed, but only once its evidence is safely packed.

**Non-Goals:**
- Re-executing a run from an archive. A rerun is a new run; an archive is a record.
- A hosted store. Archives are files; where they go (an institutional store, Zenodo, OSF, a disk) is
  the user's choice.
- Replacing `findings bundle`. A study keeps only results in git; an archive is the evidence behind
  them, kept outside git.

## Decisions

### Pack what is needed to read a run, and say what was left out

The unit of an archive is a run. `pack` takes `--collection NAME` and run ids (or `--study DIR`, the
runs listed in a study's `findings.toml`, or `--all`). For each run it includes:
- always: `run.json`, `results.jsonl`, `results.superseded.jsonl`, `report.md`, `report.json`,
  `preflight/`, and per unit `exports/`, `run.ndjson`, `stream.jsonl`, `sessions.json`,
  `setup.log`, `built/`, `claude/settings.json`; `.attempt-<N>/` directories the same way;
- by default, each unit's `work/`, with its `.git`; `--no-workdirs` leaves them out;
- with `--with-sources`, the `sources/sha256-*` snapshots whose hashes the runs' `components` name,
  and `candidate-source/`;
- with `--with-wiki`, the wiki's pattern, proposal and `skill-impact.md` entries that cite the runs,
  and its `log.md` entries for reviews that read them;
- with `--with-raw`, the raw-log events with `origin: eval` and these run ids.

Never included: `config/`, `cache/`, `state/`, `data/`. The manifest lists each excluded class with
its byte count, so an archive says what it does not hold.

Rejected: packing the whole unit directory. It is 40 times larger, and the extra 97% is a harness
install any machine can rebuild.

### One tar file with a manifest first

An archive is `<name>.wsar.tar.zst`: a tar stream compressed with zstd (gzip with `--gzip`, where
zstd is not installed). Its first member is `archive.json`:
- `format` (1), `created`, `wikiskill_version`, `host` (hostname only, never a user name);
- `collection`, `runs` (each with its `suite`, `suite_hash`, `harness`, `harness_version`, models
  and unit count), and the optional parts included;
- `files`: every member's path, size and SHA-256;
- `excluded`: each left-out class and its total size;
- `secrets`: what the scan found and what was done (below).

Paths inside are relative: `evals/<run_id>/...`, `sources/...`, `wiki/...`, `raw/...`. Absolute
paths inside files (`run.json`'s `suite_path`, a unit's `workdir`) are left as written: rewriting
them would change the files their hashes cover. Readers already resolve a run by its directory.

Rejected: a directory tree or zip. tar keeps the end states' git repositories (modes, symlinks)
exact, and one file is what an archive store accepts.

### Verify before anything is trusted

`archive verify FILE` streams the tar, checks every member against `files`, and fails on a missing,
extra or changed member. `unpack` verifies before it writes, and `prune` verifies the archive it is
given before it deletes anything.

### Unpack is additive and marks what it brought in

`unpack FILE --collection NAME` writes into that collection's data directory on this system. It:
- refuses to overwrite a run directory that exists, unless the existing files match the archive's
  hashes, in which case it reports the run already present;
- writes `imported.json` in each run directory (archive name, its SHA-256, when, from which host),
  and never edits `run.json`;
- writes source snapshots only where none exists (they are content-addressed);
- puts wiki records under `wiki/imported/<archive>/`, never into the live wiki, so an imported
  review cannot change the collection's own patterns.

Every read-only command works on an imported run. `eval --fill` refuses it: the run was made on
another system, so its harness and preflight cannot be continued. `findings bundle` copies it like
any other run, so a study can be rebuilt on a new machine from archives alone.

### Secrets are found at pack time, not assumed absent

Unit directories are not redacted, because they are the harness's own record. Eval runs set
credentials empty, but a task's `env`, a `setup` command or a model's reply can still hold a
secret-shaped string. `pack` runs the raw log's redaction patterns over every text member. On a
match it stops and lists the files, unless given:
- `--redact`: the archive gets redacted copies; their hashes are of the copies, and the manifest
  names every redacted file. The run on disk is unchanged.
- `--keep-secrets`: the archive is written as is, and the manifest says so.

### Prune reclaims space, only against a verified archive

`archive prune FILE` deletes, for each run in the archive, the excluded classes (`config/`,
`cache/`, `state/`, `data/`) from its unit directories on this system. It refuses a run whose
archive does not verify, or whose on-disk files no longer match the archive's hashes. It prints
what it will free and asks for confirmation, or takes `--yes`. It never deletes a run, `work/`,
transcripts or results. A pruned run still reads, reports and bundles; it can no longer be filled,
because its harness install is gone, and `run.json` gains `pruned` so `--fill` says why.

## Risks / Trade-offs

- **An archive holds unredacted transcripts.** → The secret scan stops on a match by default, and
  the manifest records the decision. The README warns that an archive is as private as the sessions.
- **Absolute paths name the original user's home.** → Only in `run.json` and unit files, and only
  as written by the harness. `host` holds no user name. `--redact` can be extended to home paths if
  that proves to matter.
- **zstd may be missing.** → `--gzip` writes a `.tar.gz`; both read back the same way.
- **Prune is destructive.** → It only touches the classes an archive leaves out, only after
  verifying that archive, and only on confirmation. The evidence is never pruned.
- **Large studies make large archives.** → Pack per study or per run; the manifest lets several
  archives be checked independently.
