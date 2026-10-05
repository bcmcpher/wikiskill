## Purpose

Defines the minimal experience wiki: a user-triggered review of one component that turns its eval
results and logged sessions into validated pattern pages, kept in a persistent per-collection wiki.
Sampling at scale and digests are added later by `add-experience-wiki`.

## ADDED Requirements

### Requirement: Review of one component writes validated patterns

`/wikiskill-review <component>` and `wikiskill review <component>` MUST run only when the user invokes
them. They MUST give the maintainer that component's eval results and raw sessions, bounded by a
character budget, and MUST validate the maintainer's create, update, index and log output against its
schema before writing anything. Invalid output MUST be re-prompted with the errors at most a
configured number of times, and nothing MUST be written if it still fails.

#### Scenario: Review after an eval run

- **WHEN** the user runs `/wikiskill-review datalad/datalad-doer` after an eval of that component
- **THEN** new or updated pages appear under `wiki/patterns/`, each citing the run and session ids it
  draws on, and `wiki/log.md` gains one entry

#### Scenario: Maintainer returns invalid JSON twice

- **WHEN** the maintainer's output fails validation on every allowed attempt
- **THEN** the wiki is unchanged and the command reports the last validation errors

### Requirement: The wiki is persistent and scoped

The wiki MUST live in `<collection>/wiki/` as a git repository holding `index.md`, `patterns/*.md`,
`log.md`, and `skill-impact.md`. Each pattern MUST record its component, the models and harnesses its
evidence came from, and the component `source_hash` it was observed on. The wiki MUST NOT be rolled
back when a proposal is rejected.

#### Scenario: Pattern observed on one model

- **WHEN** a pattern's evidence comes only from `opencode/big-pickle` runs
- **THEN** its page lists that model as its whole scope

#### Scenario: Rejected proposal

- **WHEN** a proposal built on a pattern is rejected
- **THEN** the pattern pages and log are unchanged apart from the appended `skill-impact.md` entry
