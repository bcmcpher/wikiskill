## ADDED Requirements

### Requirement: A run's evidence is packed into a self-verifying archive

`wikiskill archive pack` MUST write one archive for the runs it is given, holding every file needed
to read, re-verify and re-report each run: `run.json`, `results.jsonl`, any
`results.superseded.jsonl`, the reports, `preflight/`, and for every unit and kept attempt its
transcripts, session index, setup log, built component text and, unless `--no-workdirs` is given,
its working directory. It MUST NOT include a unit's harness install or session database (`config/`,
`cache/`, `state/`, `data/`). The archive's first member MUST be a manifest giving the archive
format, the wikiskill version, the runs, every member's size and SHA-256, and each excluded class
with its total size.

#### Scenario: Packing one run

- **WHEN** the user packs a finished OpenCode run of 36 units
- **THEN** the archive holds the run's results, reports and every unit's `exports/`, `run.ndjson`
  and `work/`, holds no unit's `config/`, `cache/`, `state/` or `data/`, and its manifest lists the
  bytes left out

#### Scenario: Packing a study

- **WHEN** the user packs with `--study docs/pilots/<study>`
- **THEN** the archive holds exactly the runs listed in that study's `findings.toml`

### Requirement: An archive is checked for secrets before it is written

`pack` MUST scan every text member with the raw log's redaction patterns. On a match it MUST stop
and name the files, unless `--redact` (the archive receives redacted copies and the run on disk is
unchanged) or `--keep-secrets` is given. The manifest MUST record the scan's result and the choice.

#### Scenario: A token in a transcript

- **WHEN** a unit's export contains a secret-shaped string and neither flag is given
- **THEN** no archive is written, and the file is named

### Requirement: An archive verifies, and unpacks on another system

`wikiskill archive verify` MUST fail on any member missing, added or changed against the manifest.
`wikiskill archive unpack --collection NAME` MUST verify before writing, MUST NOT overwrite an
existing run whose files differ, and MUST mark each unpacked run as imported without editing its
`run.json`. Wiki records MUST be unpacked apart from the collection's live wiki. Every read-only
command MUST work on an unpacked run, and `eval --fill` MUST refuse it.

#### Scenario: Rebuilding a study elsewhere

- **WHEN** a study's archive is unpacked on a second machine and `findings bundle` and
  `findings tables --check` run there
- **THEN** every generated table matches the committed one

#### Scenario: A tampered archive

- **WHEN** one member of an archive has changed since it was packed
- **THEN** `verify` and `unpack` both fail and name that member, and `unpack` writes nothing

### Requirement: Disk is reclaimed only against a verified archive

`wikiskill archive prune` MUST delete only the classes an archive leaves out, only for runs in an
archive that verifies and whose on-disk files still match it, and only after confirmation. It MUST
NOT delete results, transcripts, working directories or any run. A pruned run MUST be marked, MUST
still report and bundle, and `eval --fill` MUST refuse it.

#### Scenario: Reclaiming a finished study

- **WHEN** the user prunes against a verified archive of a study's runs
- **THEN** each unit's `config/`, `cache/`, `state/` and `data/` are gone, its transcripts and
  `work/` remain, and `report` on each run gives the same output as before
