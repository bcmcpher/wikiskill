## ADDED Requirements

### Requirement: Runs keep the source text of the versions they evaluate

An evaluation run, on either backend (OpenCode or Claude Code), MUST store the text of every component
file it records a `source_hash` for in the collection's source snapshot store, keyed by that hash, so
the version can be shown later even after its source changes. A snapshot that already exists MUST NOT
be rewritten. A failure to store a snapshot MUST be reported as a warning and MUST NOT fail the run.

#### Scenario: First run of a version

- **WHEN** a run records `datalad-doer` at hash `h1` and no snapshot of `h1` exists
- **THEN** after the run the snapshot store holds the file's text under `h1`, and it hashes to `h1`

#### Scenario: Repeated version

- **WHEN** a second run records the same hash `h1`
- **THEN** the existing snapshot is left as it is

#### Scenario: Snapshot store not writable

- **WHEN** the snapshot store cannot be written
- **THEN** the run completes, its results are unaffected, and the warning names the store
