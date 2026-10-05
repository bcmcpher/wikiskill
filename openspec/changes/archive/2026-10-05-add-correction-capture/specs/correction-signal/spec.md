## Purpose

Defines how wikiskill captures what users had to correct after a watched skill or agent ran — follow-up
turns, edits to agent-produced files, repeated activations, and explicit notes — as attributed raw
events, without classifying them.

## ADDED Requirements

### Requirement: Follow-up turns after component activity are recorded

The logger MUST record user turns that follow a watched component's activation within the configured
window as `user_turn` events attributed to that component with a confidence level.

#### Scenario: Immediate follow-up

- **WHEN** a watched skill finishes and the user's next message asks for a different statistical test
- **THEN** a `user_turn` event with confidence `high` is attributed to that skill

#### Scenario: Window closes on another component

- **WHEN** a different watched component activates before the user's next message
- **THEN** that message is attributed to the newer component, not the earlier one

### Requirement: Edits to agent-produced files are detected

wikiskill MUST record later changes to files written by a watched component, when those changes are
not explained by a later logged tool call, as `output_edit` events with a bounded diff.

#### Scenario: User hand-edits a produced script

- **WHEN** a watched agent writes `analysis.py` and the user later edits it in their editor
- **THEN** the next scan records an `output_edit` for `analysis.py` attributed to that agent

#### Scenario: Agent edits its own output

- **WHEN** the file was changed by a later logged tool call
- **THEN** no `output_edit` event is recorded for that change

### Requirement: Users can flag a correction explicitly

The `/wikiskill-note` command MUST record a `note` event with the note text, the session, and either the
named component or the last activated one, at confidence `explicit`.

#### Scenario: Note without a component

- **WHEN** the user runs `/wikiskill-note the plot used the wrong axis scale` after a watched skill ran
- **THEN** a `note` event with confidence `explicit` is attributed to that skill

### Requirement: Repeated activation is recorded as a rework signal

The logger MUST record a `repeat_activation` event when the same component is re-activated within the
follow-up window.

#### Scenario: Skill re-run

- **WHEN** the user triggers the same watched skill twice within the window
- **THEN** the second activation is accompanied by a `repeat_activation` event

### Requirement: Capture does not classify

Correction capture MUST NOT label events as corrections, approvals, or unrelated; classification MUST
be left to the wiki maintainer.

#### Scenario: Approving follow-up

- **WHEN** the user's follow-up is "thanks, that's exactly right"
- **THEN** it is stored as a `user_turn` with no correction or approval label
