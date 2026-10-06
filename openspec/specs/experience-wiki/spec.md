# experience-wiki Specification

## Purpose
Defines the experience wiki: a user-triggered review of one component that turns a signal-led,
incremental sample of its eval results and logged sessions into validated pattern pages, kept in a
persistent per-collection wiki, from inside the harness or from the command line.

## Requirements

### Requirement: Review of one component writes validated patterns

`/wikiskill-review <component>` and `wikiskill review <component>` MUST run only when the user invokes
them. They MUST give the maintainer a sample of that component's eval results and raw sessions,
bounded by a character budget, and MUST validate the maintainer's create, update, index and log
output against its schema before writing anything.

Invalid output MUST be re-prompted with the errors at most a configured number of times. If it still
fails, no pattern, index or watermark change MUST be written, and the failure MUST be appended to the
wiki log.

#### Scenario: Review after an eval run

- **WHEN** the user runs `/wikiskill-review datalad/datalad-doer` after an eval of that component
- **THEN** new or updated pages appear under `wiki/patterns/`, each citing the run and session ids it
  draws on, and `wiki/log.md` gains one entry

#### Scenario: Maintainer returns invalid JSON twice

- **WHEN** the maintainer's output fails validation on every allowed attempt
- **THEN** the patterns, index and watermark are unchanged, `wiki/log.md` gains an entry naming the
  failure, and the command reports the last validation errors

### Requirement: The wiki is persistent and scoped

The wiki MUST live in `<collection>/wiki/` as a git repository holding `index.md`, `patterns/*.md`,
`components/*.md`, `log.md`, `skill-impact.md` and `.watermark.json`. Each pattern MUST record its
component, the models and harnesses its evidence came from, and the component `source_hash` it was
observed on, all computed from the evidence it cites. A component's page MUST be created with its
first pattern and list every pattern of that component. The wiki MUST NOT be rolled back when a
proposal is rejected.

#### Scenario: Pattern observed on one model

- **WHEN** a pattern's evidence comes only from `opencode/big-pickle` runs
- **THEN** its page lists that model as its whole scope

#### Scenario: First pattern for a component

- **WHEN** a review creates the first pattern for `datalad/datalad-doer`
- **THEN** `components/datalad-datalad-doer.md` is created and lists that pattern

#### Scenario: Rejected proposal

- **WHEN** a proposal built on a pattern is rejected
- **THEN** the pattern pages and log are unchanged apart from the appended `skill-impact.md` entry

### Requirement: Sampling prioritises correction and failure signals within a budget

Sampling MUST rank evidence by its strongest signal, in this order: explicit note, output edit,
repeat activation, failure, then follow-up turn. It MUST take signal evidence ahead of clean evidence,
each up to a configured count. The per-review budget MUST be derived from the maintainer role's
configured context when one is given.

#### Scenario: Mixed backlog

- **WHEN** twenty sessions are unprocessed, three of them with explicit notes
- **THEN** all three noted sessions are in the sample before any clean session

#### Scenario: Small-context maintainer

- **WHEN** the maintainer role is configured with a 32k-token context
- **THEN** the digest is capped below the default 15,000-character budget

### Requirement: Review is incremental

A watermark MUST record, per component, which evidence a successful review was shown, and review MUST
NOT sample that evidence again unless asked to. A live session MUST become unprocessed again when it
gains events after the last one shown. The watermark MUST advance only in the same commit as the
patterns it produced.

#### Scenario: Second review with no new sessions

- **WHEN** `wikiskill review` runs twice for a component with no new raw events in between
- **THEN** the second run reports nothing to review, asks no model, and makes no wiki commit

#### Scenario: A note arrives after review

- **WHEN** a session already reviewed later gains an explicit note on that component
- **THEN** the next review samples that session again, ahead of clean evidence

### Requirement: Patterns claim universality only on evidence

Every pattern MUST cite at least one sampled piece of evidence and carry a cause from the fixed
taxonomy. A pattern MUST NOT be marked universal unless its evidence, including evidence it already
had, spans at least two models or two harnesses.

#### Scenario: Lesson seen on one small model

- **WHEN** all evidence for a pattern comes from `qwen3:1.7b` under OpenCode
- **THEN** the pattern's scope lists that model and harness, and a `universal: true` claim is rejected
  with a message saying why

### Requirement: Review runs in and out of the harness on one validator

The same review MUST be runnable from `/wikiskill-review` inside the harness and from `wikiskill
review` against the maintainer role's configured model. Both MUST be validated and applied by
wikiskill, against the evidence the maintainer was shown. A sample taken for an in-harness review MUST
be persisted, so the reply is checked against exactly that sample.

#### Scenario: In-harness review

- **WHEN** `/wikiskill-review datalad/datalad-doer` runs in OpenCode
- **THEN** it takes a sample with `wikiskill sample`, and the `wikiskill-maintainer` subagent answers
  it. `wikiskill review --sample <id> --reply-file <file>` then validates and applies that answer.

#### Scenario: Stale sample

- **WHEN** a reply is applied against a sample taken before another review changed that component's
  patterns
- **THEN** it is refused and nothing is written

### Requirement: Review evidence can be restricted to one model

`wikiskill review --model <model>` and `wikiskill sample --model <model>` MUST sample only eval units
and live sessions run on that model, named with or without its provider, and the prompt MUST say so.
A live session whose model was not recorded MUST be left out. `--model` MUST be refused beside
`--sample`, whose evidence was fixed when it was taken. A proposal refined from that review MUST
record the model in its metadata. How the proposal is gated MUST NOT change.

#### Scenario: A proposal for a small model

- **WHEN** the user reviews `archive/archive-doer` with `--model ollama/qwen3:1.7b`, then refines it
- **THEN** every cited unit and session ran on `qwen3:1.7b`, and the proposal's metadata names
  that model
