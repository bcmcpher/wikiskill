## Purpose

Defines how wikiskill proposes a refinement to a skill or agent: one atomic, typed, evidence-grounded
proposal per component, checked by the harness for real evidence use and evaluation leakage, and
delivered as a reviewable patch.

## ADDED Requirements

### Requirement: Proposals are atomic and typed

Every proposal MUST be exactly one of `create`, `patch`, or `no_action` and MUST target a single
component; edits MUST touch only files belonging to that component.

#### Scenario: Proposal spans two skills

- **WHEN** a proposer returns edits to both `analyze/checkpoint` and `disseminate/publish`
- **THEN** the proposal is rejected as non-atomic

### Requirement: Proposals are grounded in evidence actually read

A proposal MUST cite the patterns it addresses and at least the configured minimum of distinct trace
digests. wikiskill MUST verify those reads from the proposer's own logged session and reject a proposal
whose claimed reads are not in the log.

#### Scenario: Claimed but unread digests

- **WHEN** a proposal lists four digest ids but the proposer session log shows two digest reads
- **THEN** the proposal is rejected with the missing ids named

### Requirement: Proposals do not leak evaluation content

A proposal MUST be rejected if its text contains task ids, expected output values from task suites,
or rubric anchor text.

#### Scenario: Expected value copied into a skill

- **WHEN** a patch adds a sentence containing an expected output value from the routing suite
- **THEN** the proposal is rejected and the matched span is reported

### Requirement: Proposals are delivered as reviewable patches

A proposal MUST be delivered as a patch and rendered preview in the wiki's proposals directory. It
MUST NOT modify the component's source repository unless the user explicitly applies it.

#### Scenario: New proposal

- **WHEN** `/wikiskill-refine analyze/checkpoint` produces a patch proposal
- **THEN** the patch and preview are written under `wiki/proposals/<id>/`, and the source repository's
  `git status` is unchanged

### Requirement: General edits are preferred over model-specific variants

A proposal MUST NOT add model-specific guidance unless the patterns it addresses are scoped to those
models and carry at least the configured minimum of evidence items.

#### Scenario: Small-model section with thin evidence

- **WHEN** a proposal adds a section for small models backed by one evidence item
- **THEN** the proposal is rejected with the evidence count and the required minimum
