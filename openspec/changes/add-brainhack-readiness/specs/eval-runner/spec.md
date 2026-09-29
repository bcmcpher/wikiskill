## MODIFIED Requirements

### Requirement: Endpoints are preflighted before tasks run

Before running tasks on a model, the runner MUST verify that:
- the endpoint is reachable
- the model is offered under the name the suite asks for
- the model returns a structured tool call
- the model's context window is at least the configured minimum (default 16k tokens)

The runner MUST probe the model over the same path its units will take: directly when wikiskill
addresses the endpoint itself, and through the harness when the harness holds the credential. On
failure it MUST skip that model with an actionable message.

The tool-call probe MUST have its own configurable timeout, separate from the other checks, because
it is the request that loads the model. A probe that times out or loses its connection MUST fail
preflight for that model with an actionable message, and MUST NOT abort the run.

For Ollama, the runner MUST prefer the context the running server reports for the loaded model over
any value read from its own environment.

#### Scenario: Default Ollama context

- **WHEN** a model is served by Ollama with a 4096-token context
- **THEN** preflight fails for that model with a message recommending a larger context setting, and
  no tasks run on it

#### Scenario: Context set only in the runner's shell

- **WHEN** `OLLAMA_CONTEXT_LENGTH=16384` is set where wikiskill runs, but the Ollama server was
  started without it and serves 4096 tokens
- **THEN** preflight reports the server's 4096 tokens and fails that model

#### Scenario: Model still loading when the probe times out

- **WHEN** the tool-call probe does not answer within the probe timeout
- **THEN** preflight fails for that model with a message naming `--probe-timeout`, and the run goes
  on to the next model

#### Scenario: Model the harness authorizes on the runner's behalf

- **WHEN** a model is served by the harness's own provider, which refuses a direct HTTP request
- **THEN** preflight probes the model by running the harness, and accepts it when that probe makes
  a real tool call
