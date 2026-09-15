## Purpose

Defines the acceptance gate for refinement proposals: replay evidence across every configured model,
regressions reported individually, a human decision for every outcome, and a complete impact record.

## ADDED Requirements

### Requirement: Acceptance requires a human decision

A proposal MUST NOT reach the `accepted` state without an explicit user decision recorded with the
proposal, whatever the replay results.

#### Scenario: Replay recommends acceptance

- **WHEN** replay shows improvement and no regressions
- **THEN** the proposal stays `replayed` with an "accept" recommendation until the user decides

### Requirement: Replay covers motivating cases and a regression bank on every target model

When the eval runner is installed, the gate MUST replay the proposal's motivating cases and the
component's regression bank under baseline and candidate on every configured target model before a
decision is requested. Cases that cannot be reproduced MUST be marked non-replayable with a reason.

#### Scenario: Proposal motivated by one model's failures

- **WHEN** a proposal's evidence comes only from `qwen3:1.7b` and the manifest lists three target models
- **THEN** replay runs on all three models and reports each separately

#### Scenario: Eval runner absent

- **WHEN** `add-explicit-eval` is not installed
- **THEN** the gate records replay as unrun with that reason and still allows a decision

### Requirement: Regressions are reported individually

The gate report MUST list every regressed case per model individually, and MUST NOT present only an
aggregate score change.

#### Scenario: Net improvement hiding a regression

- **WHEN** candidate improves five cases and breaks one on the same model
- **THEN** the report shows the net change and names the broken case

### Requirement: Every outcome is recorded in skill-impact

Accepted, rejected, and withdrawn proposals MUST each append an entry to `skill-impact.md` with the
decision, reviewer note, diff, evidence ids, and replay summary. Rejected proposals MUST keep their full
content.

#### Scenario: Rejected proposal

- **WHEN** the user rejects a proposal
- **THEN** its full proposal content and replay summary are appended to `skill-impact.md`, and later
  proposer runs can read them
