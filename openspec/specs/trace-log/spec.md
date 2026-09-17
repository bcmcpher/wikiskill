# trace-log Specification

## Purpose

Defines the harness-neutral raw log: an append-only record of what watched skills and subagents did
with a model, filled passively during real use and by explicit evaluations, and the OpenCode plugin
that writes it.

## Requirements

### Requirement: Raw events follow one versioned, harness-neutral schema

Every raw event MUST validate against the versioned raw-event schema and MUST record its harness,
harness version, provider, model, session, root and parent session, and origin.

#### Scenario: Events from different harnesses

- **WHEN** the same skill is logged once under OpenCode and once under Claude Code
- **THEN** both event streams validate against the same schema and differ only in harness, model, and
  session identity fields

#### Scenario: Unknown schema version

- **WHEN** a reader encounters an event whose major `schema_version` it does not support
- **THEN** it refuses the file with a message naming the version, rather than misreading it

### Requirement: Only sessions touching watched components are logged

The logger MUST persist a session only once it activates a watched skill, agent, or command, and MUST
then include the buffered events that preceded the activation, up to the configured buffer size.

#### Scenario: Session without watched components

- **WHEN** a session never activates a watched component
- **THEN** nothing from that session is written to the raw log

#### Scenario: Activation mid-session

- **WHEN** a watched skill first activates at the fifth turn of a session
- **THEN** the log contains that activation and the buffered events from the earlier turns

### Requirement: Activations are attributed to a component version

Each component activation event MUST name the component's kind and name and MUST record a content hash
of the component's source file at activation time.

#### Scenario: Skill edited between sessions

- **WHEN** a watched skill's `SKILL.md` changes between two sessions
- **THEN** the two sessions' activation events carry different `source_hash` values

### Requirement: Delegation chains are logged as one trajectory

When a logged session delegates to a subagent, the log MUST record the delegation with the child
session id, and the child session's events MUST be written into the root session's log.

#### Scenario: Planner skill delegates to a doer agent

- **WHEN** a watched skill's session calls the OpenCode `task` tool with `subagent_type: datalad-doer`
- **THEN** the root log contains a `delegation` event naming `datalad-doer` and the child session id,
  followed by the child's tool calls tagged with that `parent_session_id`

### Requirement: Logging is fail-open, model-free, and redacted

Logger failures MUST NOT interrupt or alter the user's session, logging MUST NOT make model calls,
and the logger MUST redact environment values and secret-shaped strings and bound tool-output size.

#### Scenario: Storage is unwritable

- **WHEN** the raw log directory cannot be written
- **THEN** the OpenCode session continues normally, and the failure is recorded in the logger error
  log when that is writable

#### Scenario: Tool output contains a token

- **WHEN** a bash tool output contains a string matching a secret pattern
- **THEN** the stored event replaces it with a redaction marker and lists the redaction kind

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
