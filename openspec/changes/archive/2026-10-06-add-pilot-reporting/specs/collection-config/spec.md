## ADDED Requirements

### Requirement: The judge role can name several models

`[roles.judge]` MAY name `models`, a list of two or more distinct models on its one endpoint, instead
of `model`. Naming both, or an empty or repeated list, MUST be rejected. Every model in the list MUST
be checked against the models under test, as a single judge is.

#### Scenario: A three-model panel

- **WHEN** `[roles.judge]` sets `models = ["gpt-oss:120b", "llama3.3", "nemotron-3.5-lightning"]`
- **THEN** the collection loads with a three-model judge panel on the role's endpoint

#### Scenario: A panel member under test

- **WHEN** a run's models include `llama3.3`, which is in the judge panel
- **THEN** the run is refused, naming `llama3.3`
