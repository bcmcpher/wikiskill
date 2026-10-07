# add-run-archive

Preserve evaluation runs beyond the machine that made them: pack a run's evidence (results,
transcripts, end states, component text, review and decision records) into one checksummed archive,
verify it, unpack it on another system where every read-only command works on it, and reclaim the
disk the harness's per-unit installs take once a run is safely packed.
