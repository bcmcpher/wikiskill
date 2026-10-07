## 1. Layout

- [ ] 1.1 `RunLayout`: the preservable parts of a run and of a unit, and the excluded classes, in
  one place, for OpenCode and Claude Code units and `.attempt-<N>` directories
- [ ] 1.2 Size accounting per part, for `pack`'s manifest and `prune`'s report

## 2. Pack

- [ ] 2.1 `wikiskill archive pack --collection NAME RUN_ID... | --study DIR | --all --out FILE`
- [ ] 2.2 `archive.json` first: format, versions, host, runs, parts, `files` with SHA-256,
  `excluded` with sizes
- [ ] 2.3 Optional parts: `--no-workdirs`, `--with-sources`, `--with-wiki`, `--with-raw`
- [ ] 2.4 zstd by default, `--gzip` otherwise
- [ ] 2.5 Secret scan with the raw log's redaction patterns; stop on a match; `--redact` and
  `--keep-secrets`, recorded in the manifest
- [ ] 2.6 Tests: one run packs with every always-included part and none of the excluded ones; a
  retried unit's attempt directory is packed; `--study` packs a study's runs; a secret stops the
  pack; `--redact` leaves the run on disk unchanged

## 3. Verify and unpack

- [ ] 3.1 `archive verify FILE`: missing, extra and changed members each fail, by name
- [ ] 3.2 `archive unpack FILE --collection NAME`: verify first; refuse an existing different run;
  report an identical one as present; write `imported.json`; sources only where absent; wiki
  records under `wiki/imported/<archive>/`
- [ ] 3.3 `eval --fill` refuses an imported run, naming the archive
- [ ] 3.4 Tests: round trip into an empty data directory under another `XDG_DATA_HOME`, then
  `report`, `leaderboard`, `findings bundle` and `findings tables --check` give the same output as
  on the original; a tampered member fails verify and unpack

## 4. Prune

- [ ] 4.1 `archive prune FILE`: verify the archive and the on-disk files against it, list what will
  be freed, confirm or `--yes`; delete only excluded classes; mark `run.json` `pruned`
- [ ] 4.2 `eval --fill` refuses a pruned run
- [ ] 4.3 Tests: prune leaves results, transcripts and `work/`; a run changed since packing is
  refused; a pruned run still reports and bundles

## 5. Docs and verification

- [ ] 5.1 `docs/data.md`: the archive format, what is left out and why, `imported.json`, `pruned`
- [ ] 5.2 `README.md`: "Keeping runs", with the privacy warning
- [ ] 5.3 Pack one pilot study's runs on the GB10, verify, unpack on a second machine, rebuild the
  study's tables there, and record archive size against the runs' size on disk
