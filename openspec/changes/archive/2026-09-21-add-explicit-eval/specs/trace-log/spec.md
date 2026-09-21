## MODIFIED Requirements

### Requirement: Raw events follow one versioned, harness-neutral schema

Every raw event MUST validate against the versioned raw-event schema and MUST record its harness,
harness version, provider, model, session, root and parent session, and origin. An event whose origin
is `eval` MUST additionally carry the evaluation run id, suite, task id, condition, and repeat index,
so an evaluation trajectory can be read back per task and condition from the log alone. An event whose
origin is `live` MUST NOT carry them.

#### Scenario: Events from different harnesses

- **WHEN** the same skill is logged once under OpenCode and once under Claude Code
- **THEN** both event streams validate against the same schema and differ only in harness, model, and
  session identity fields

#### Scenario: Unknown schema version

- **WHEN** a reader encounters an event whose major `schema_version` it does not support
- **THEN** it refuses the file with a message naming the version, rather than misreading it

#### Scenario: Event from an evaluation run

- **WHEN** the runner normalises the second repeat of task `disseminate-release` under ROUTED
- **THEN** every event it writes carries `origin: eval` together with that run's id, the suite name,
  the task id, condition `routed`, and repeat index `1`

#### Scenario: Event from ordinary use

- **WHEN** the OpenCode plugin logs a session during real use
- **THEN** the event carries `origin: live` and no evaluation block, and the schema rejects one that
  does carry it
