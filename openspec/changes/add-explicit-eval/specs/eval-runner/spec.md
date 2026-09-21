## Purpose

Defines how explicit evaluations execute: fresh isolated headless sessions behind a harness backend
interface, three comparison conditions, repeats across a model matrix, endpoint preflight, and outcome
classes that separate model behaviour from infrastructure failure.

## ADDED Requirements

### Requirement: Evaluations run in fresh isolated sessions

Every evaluation run MUST execute in a new headless harness session with its own configuration, data
directories, and working directory. It MUST NOT run in the session that requested it, and MUST NOT
load the user's global or project skills, agents, MCP servers, or plugins beyond those under test.

#### Scenario: Launch from inside OpenCode

- **WHEN** the user runs `/wikiskill-eval dsh-routing` in an OpenCode session
- **THEN** evaluation starts as a background process with a run id, and the calling session's
  context is not used for any task

#### Scenario: User has a global MCP server configured

- **WHEN** the user's global OpenCode config enables an MCP server
- **THEN** the run's captured configuration shows no MCP servers

### Requirement: Runs compare OFF, ROUTED, and INJECTED conditions

The runner MUST support three conditions per task:
- OFF: without the collection
- ROUTED: with the collection discovered normally
- INJECTED: with the component's text forced into context while self-loading is denied, or, for an
  agent, invoked directly

#### Scenario: Skill under INJECTED on OpenCode

- **WHEN** a skill task runs under INJECTED on OpenCode
- **THEN** the skill's text is supplied through `instructions` and the `skill` permission for that
  skill is `deny`

### Requirement: Endpoints are preflighted before tasks run

Before running tasks on a model, the runner MUST verify that:
- the endpoint is reachable
- the model is offered under the name the suite asks for
- the model returns a structured tool call
- the model's context window is at least the configured minimum (default 16k tokens)

The runner MUST probe the model over the same path its units will take: directly when wikiskill
addresses the endpoint itself, and through the harness when the harness holds the credential. On
failure it MUST skip that model with an actionable message.

#### Scenario: Default Ollama context

- **WHEN** a model is served by Ollama with a 4096-token context
- **THEN** preflight fails for that model with a message recommending a larger context setting, and
  no tasks run on it

#### Scenario: Model the harness authorizes on the runner's behalf

- **WHEN** a model is served by the harness's own provider, which refuses a direct HTTP request
- **THEN** preflight probes the model by running the harness, and accepts it when that probe makes
  a real tool call

### Requirement: Units run within stated budgets

Each unit MUST be held to its task's `timeout_s` and `max_steps`. Exceeding the step budget MUST be
classified `step_exhausted`, which is model behaviour, rather than an infrastructure failure. The
runner MUST NOT run more than a configured number of units at once against one endpoint, defaulting
to one, and MUST record that number in the run manifest.

#### Scenario: Model loops past its step budget

- **WHEN** a task declares `max_steps: 1` and the model attempts a second tool call
- **THEN** the call is refused, the unit is classified `step_exhausted`, and its verifiers still run
  against whatever the first step produced

#### Scenario: Endpoint serving one request at a time

- **WHEN** a suite runs across several models with no worker count given
- **THEN** one unit at a time runs against each endpoint, and models are not interleaved

### Requirement: Outcomes are classified before scoring

Every run MUST be classified as one of `completed`, `tool_call_as_text`, `step_exhausted`,
`permission_blocked`, `api_error`, `infra_error`, or `skipped`. `infra_error` and `skipped` runs MUST be
excluded from scores and reported separately with reasons.

#### Scenario: Model prints a tool call instead of making one

- **WHEN** the assistant's final text contains a JSON tool-call object and the session has no tool parts
- **THEN** the run is classified `tool_call_as_text`, not `completed`

#### Scenario: Harness process crashes

- **WHEN** the headless harness exits abnormally before producing a session
- **THEN** the run is classified `infra_error` and does not count as a task failure
