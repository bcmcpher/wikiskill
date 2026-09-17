## ADDED Requirements

### Requirement: Tool calls record their outcome

Every `tool_call` event MUST record whether the call succeeded, MUST carry the harness's error text
when it failed, and MUST record the call's duration when the harness reports enough to derive one. A
call that fails MUST be recorded, not omitted.

#### Scenario: A tool fails

- **WHEN** a watched session runs a tool that exits with an error
- **THEN** the log contains a `tool_call` event for it marked as not ok, carrying the harness's error
  text

#### Scenario: A tool succeeds

- **WHEN** a watched session runs a tool that completes normally
- **THEN** the `tool_call` event is marked ok, with no error text

#### Scenario: OpenCode reports a completed call twice

- **WHEN** OpenCode describes one completed call both as a tool part and through its
  `tool.execute.after` hook
- **THEN** exactly one `tool_call` event is written for that call id

#### Scenario: Duration is unavailable

- **WHEN** the harness reports no timing for a completed call
- **THEN** the event records a null duration rather than a guess, and is still written

### Requirement: Per-session logger state is released when a session goes quiet

The logger MUST release the state it holds for a session, including a session it is logging, once
that session has been inactive for a bounded period measured from its last activity. Releasing state
MUST NOT alter or remove anything already written to the raw log.

#### Scenario: A long-lived server accumulates sessions

- **WHEN** many sessions have activated watched components and then gone quiet in one long-running
  OpenCode server
- **THEN** their per-session state is released, and the logger's memory does not grow with the number
  of sessions it has ever logged

#### Scenario: A long session is still active

- **WHEN** a session started longer ago than the inactivity period but is still producing events
- **THEN** its state is retained, including its pre-activation buffer, and its events continue to be
  logged
