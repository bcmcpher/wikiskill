## ADDED Requirements

### Requirement: Critical checks are reported under OFF

With `--critical`, the board MUST also check OFF units, and MUST give per model the OFF units that
failed a critical check, listing them. A failure under OFF MUST NOT disqualify any version.

#### Scenario: A bare model invents a DOI

- **WHEN** an OFF unit on `mistral` replies with a DOI, and the DOI check is critical
- **THEN** the board lists that unit under `mistral`'s OFF, and no version is disqualified for it

### Requirement: The board lists models that did not run

The board MUST list every model that failed preflight in any pooled run, with the run and its
problems.

#### Scenario: A model skipped by preflight

- **WHEN** one candidate run's preflight failed `llama3.3`
- **THEN** the board names `llama3.3` with that run and reason, beside its per-model table
