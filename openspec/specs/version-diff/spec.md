# version-diff Specification

## Purpose

Lets a user see what changed between two iterations of one component, both in its source text and in
its evaluated results, from data wikiskill already stores, without re-running anything.

## Requirements

### Requirement: Versions are named by hash, proposal, run, or current

`wikiskill diff <component> <version-a> <version-b>` MUST accept each version as one of: `current`
(the component's file as it is now), a `source_hash` prefix of at least 7 hex digits, with or without
the `sha256:` prefix, a proposal id `p-NNN` (its candidate), `p-NNN^` (the version the proposal was
made from), or `run:<run-id>` (the component's `source_hash` recorded in that run). It MUST resolve
both to full hashes before doing anything else, and MUST exit non-zero, naming the reference, when a
reference matches no version or a hash prefix matches more than one.

#### Scenario: A proposal against what it was made from

- **WHEN** the user runs `wikiskill diff datalad-doer p-003^ p-003`
- **THEN** version A is `p-003`'s recorded `source_hash` and version B its `candidate_hash`

#### Scenario: Ambiguous prefix

- **WHEN** the prefix `9b1e2c4` matches two known hashes of the component
- **THEN** the command exits non-zero and lists both full hashes

#### Scenario: Unknown component

- **WHEN** the component is not in the collection
- **THEN** the command exits non-zero and names the component

### Requirement: The report shows the source text diff

The report MUST include a unified diff of the component's main file between the two versions, and
MUST state when the frontmatter `description` differs, because that changes how a harness routes to
the component. When a version's text cannot be recovered, the report MUST say so for that version,
with where it looked, and MUST still produce the results section. When both versions have the same
hash, the report MUST say the text is identical instead of printing an empty diff.

#### Scenario: Two recoverable versions

- **WHEN** both versions' text can be recovered and only the body changed
- **THEN** the report shows the unified diff and states that the description is unchanged

#### Scenario: Description changed

- **WHEN** version B edits the frontmatter `description`
- **THEN** the report flags the description change above the diff

#### Scenario: Text lost

- **WHEN** version A's text is in no snapshot, proposal, candidate copy, or the repository's history
- **THEN** the text section says version A's text is unavailable and lists the places searched, and
  the results section is still shown

### Requirement: Version text is recovered without writing to the source repository

To recover a version's text, the command MUST check, in order: wikiskill's own source snapshots, the
current file, a proposal's rendered candidate, a candidate run's copied source, and the git history
of the repository holding the component. A recovered text MUST hash to the requested `source_hash`
before it is used. Reading the repository's history MUST NOT change the repository: no checkout,
branch, stash, or write of any kind.

#### Scenario: Found in git history

- **WHEN** a version is only in the collection repository's history
- **THEN** the command finds the revision whose file content hashes to that version, uses it, and the
  repository's status is unchanged

#### Scenario: Hash mismatch

- **WHEN** a candidate copy's file does not hash to the version requested
- **THEN** that source is skipped and the search continues

### Requirement: The report shows the results diff from stored runs

The report MUST include the version comparison that `wikiskill compare` produces (per condition, per
model and pooled: pass rates with Wilson 95% intervals, direction, tool choice, and the pooled row
with timeouts counted as failures), computed on one finished run of each version. By default it MUST
use the newest pair of runs, one whose recorded `source_hash` for the component is version A and one
whose is version B, that share suite, tasks, and `suite_hash`. `--run-a` and `--run-b` MUST override
the choice, and MUST be refused when the given run did not record that version. When no comparable
pair exists, the report MUST say why and list the runs found for each version. The command MUST NOT
run an evaluation.

#### Scenario: Newest comparable pair

- **WHEN** version A has runs on suites `s1` and `s2`, and version B only on `s1`
- **THEN** the results section compares the newest `s1` run of each version and names both run ids

#### Scenario: No runs for a version

- **WHEN** version B has never been evaluated
- **THEN** the results section says version B has no finished runs, lists version A's runs, and
  suggests `wikiskill eval --proposal` when B is a proposal's candidate

#### Scenario: Explicit run of the wrong version

- **WHEN** `--run-a` names a run that recorded a different hash for the component
- **THEN** the command exits non-zero and names the hash that run recorded

### Requirement: The report is printed and saved

The command MUST print the report as markdown and MUST write it under the collection's evals directory
in a directory named for the component and both short hashes, as `diff.md`, `diff.json` (both
versions' hashes and references, where each text came from, the runs used, and the comparison
result) and `text.diff` (the unified diff alone, omitted when either text is unavailable). It MUST
NOT write to the component's source repository.

#### Scenario: Saved report

- **WHEN** the diff of `datalad-doer` between `9b1e2c4…` and `41f0aa7…` completes
- **THEN** `evals/diff/datalad-doer/9b1e2c4_vs_41f0aa7/` holds `diff.md`, `diff.json`, and
  `text.diff`

### Requirement: Known versions can be listed

`wikiskill diff <component> --list` MUST list every version of the component that wikiskill knows of,
from source snapshots, proposals, run manifests, and raw-log activations, oldest first. For each it
MUST show the short hash, whether its text is recoverable, the proposals that produced or started from
it, the number of finished runs that evaluated it, and whether it is the current file.

#### Scenario: A refined component

- **WHEN** the component started at `h1`, proposal `p-001` produced `h2`, and both were evaluated
- **THEN** the list shows `h1` (base of `p-001`) and `h2` (candidate of `p-001`), each with its run
  count, and marks the current one
