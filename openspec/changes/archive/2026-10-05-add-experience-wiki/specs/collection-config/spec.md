## MODIFIED Requirements

### Requirement: Meta-roles are configured per role

The manifest MUST let each meta-role — judge, maintainer, proposer — name its own OpenAI-compatible
endpoint and model, independently of the models under test, and MUST reject a judge model that is
also a model under test. A role MAY state its model's context in tokens, which work sent to that role
is sized by.

#### Scenario: Roles on different endpoints

- **WHEN** the judge points at a remote vLLM server and the maintainer at a local Ollama model
- **THEN** each role's calls go to its own endpoint

#### Scenario: Judge equals a target

- **WHEN** an evaluation's target model list includes the configured judge model
- **THEN** the configuration is rejected with a message naming the model

#### Scenario: Role context

- **WHEN** `[roles.maintainer]` sets `context_tokens = 32768`
- **THEN** the collection loads with that context on the maintainer role, and a context that is not
  a positive integer is rejected
