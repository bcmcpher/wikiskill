## MODIFIED Requirements

### Requirement: Logging is fail-open, model-free, and redacted

Logger failures MUST NOT interrupt or alter the user's session, logging MUST NOT make model calls,
and every event written to the raw log MUST have environment values and secret-shaped strings
redacted and tool-output size bounded. This applies to live events from the OpenCode logger and the
Claude Code hooks, to `origin: eval` events written by an evaluation run on either backend, and to
notes. Redaction MUST cover every free-text field: assistant text, user turns, note text, tool input,
output and error, delegation descriptions, activation input summaries, and error messages. It MUST
happen before truncation, so a secret cut by the size bound cannot survive as a partial match, and
each event MUST list what was redacted in `redactions`. The environment values redacted from an eval
event MUST be those of the unit's own harness environment. A collection with `[logging] redact =
false` MUST get no redaction, live or eval. A harness's own transcripts in an eval unit's directory
are not raw-log events, and are stored unredacted.

#### Scenario: Storage is unwritable

- **WHEN** the raw log directory cannot be written
- **THEN** the OpenCode session continues normally, and the failure is recorded in the logger error
  log when that is writable

#### Scenario: Tool output contains a token

- **WHEN** a bash tool output contains a string matching a secret pattern
- **THEN** the stored event replaces it with a redaction marker and lists the redaction kind

#### Scenario: Eval tool output contains a token

- **WHEN** a unit of an eval run, on OpenCode or on Claude Code, runs a tool whose output contains
  `ghp_` followed by 36 letters
- **THEN** the `origin: eval` `tool_call` event in `raw/` holds `[REDACTED:api_key]` instead, its
  `redactions` lists `api_key`, and the unit's own transcript is unchanged

#### Scenario: Eval environment value

- **WHEN** a suite sets `env = { DATASET_TOKEN = "s3cr3t-value-123" }` and the model echoes it
- **THEN** the eval event replaces it with `[REDACTED:env_value]`

#### Scenario: A secret at the truncation bound

- **WHEN** a tool output longer than `output_limit_bytes` has a key straddling the cut
- **THEN** the stored output holds the redaction marker, not the first part of the key, and
  `output_length` is the original length

#### Scenario: Delegation description

- **WHEN** a live or eval session delegates with a `description` holding a password assignment
- **THEN** both the `delegation` event's `description` and the `component_activated` event's
  `input_summary` hold `[REDACTED:password]` in place of the value

#### Scenario: Redaction turned off

- **WHEN** the collection sets `[logging] redact = false` and an eval tool output holds a key
- **THEN** the eval event stores the key as it was, and lists no redactions
