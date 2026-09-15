## Purpose

Defines the persistent experience wiki: how raw sessions are sampled into digests, how a maintainer
agent's output is validated and applied, and how patterns record evidence and model/harness scope.

## ADDED Requirements

### Requirement: The wiki layout is fixed and persistent

The wiki MUST consist of an index, pattern pages, component pages, an evolution log, and a skill-impact
record in a git repository per collection, and MUST NOT be rolled back when a refinement is rejected.

#### Scenario: Refinement rejected

- **WHEN** a proposal built on a wiki pattern is rejected at the gate
- **THEN** the wiki's patterns and history are unchanged apart from the appended skill-impact entry

### Requirement: Sampling prioritises correction and failure signals within a budget

Sampling MUST select unprocessed sessions carrying correction or failure signals ahead of clean
sessions, up to the configured counts. It MUST cap each digest to a budget derived from the maintainer
model's context.

#### Scenario: Mixed backlog

- **WHEN** twenty sessions are unprocessed, three of them with explicit notes
- **THEN** all three noted sessions are in the sample before any clean session

#### Scenario: Small-context maintainer

- **WHEN** the maintainer model is configured with a 32k-token context
- **THEN** each digest is capped below the default 15,000-character budget

### Requirement: Maintainer output is validated before it is applied

The maintainer MUST return the create/update/index/log JSON contract. wikiskill MUST validate it before
writing anything, re-prompt with the validation errors at most a configured number of times, and apply
nothing if it still fails.

#### Scenario: Ambiguous patch anchor

- **WHEN** a `replace` operation's anchor occurs twice in the target pattern page
- **THEN** the output is rejected and the maintainer is re-prompted with that error

#### Scenario: Retries exhausted

- **WHEN** the output is still invalid after the last retry
- **THEN** the wiki is unchanged, the watermark does not advance, and the failure is appended to the log

### Requirement: Patterns cite evidence and declare scope

Every pattern MUST cite at least one sampled event, carry a cause from the fixed taxonomy, and declare
its model and harness scope. A pattern MUST NOT be marked universal unless its evidence spans at least
two models or two harnesses.

#### Scenario: Lesson seen on one small model

- **WHEN** all evidence for a pattern comes from `qwen3:1.7b` under OpenCode
- **THEN** the pattern's scope lists that model and harness, and a `universal: true` claim is rejected

### Requirement: Review is incremental and invocable in and out of the harness

A watermark MUST record processed raw events so that review does not re-sample them unless asked.
The same maintenance MUST be runnable from `/wikiskill-review` inside the harness and headless against
the configured maintainer endpoint.

#### Scenario: Second review with no new sessions

- **WHEN** `/wikiskill-review` runs twice with no new raw events in between
- **THEN** the second run reports nothing to review and makes no wiki commit

#### Scenario: Headless review

- **WHEN** `wikiskill review --headless --collection dsh` runs
- **THEN** the maintainer runs on the maintainer role's configured model and the result is validated
  and applied exactly as in-harness
