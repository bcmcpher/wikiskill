## MODIFIED Requirements

### Requirement: Users can flag a correction explicitly

The `/wikiskill-note` command MUST record a `note` event with the note text, the session, and either the
named component or the last activated one, at confidence `explicit`. The note text MUST be redacted
before it is stored, as other logged text is, using the environment of the process recording the
note, unless the collection sets `[logging] redact = false`.

#### Scenario: Note without a component

- **WHEN** the user runs `/wikiskill-note the plot used the wrong axis scale` after a watched skill ran
- **THEN** a `note` event with confidence `explicit` is attributed to that skill

#### Scenario: Note containing a secret

- **WHEN** the user runs `wikiskill note "it printed sk-ant-api03-AAAABBBBCCCCDDDDEEEE"`
- **THEN** the stored note text holds `[REDACTED:api_key]` in place of the key, and the event's
  `redactions` lists `api_key`
