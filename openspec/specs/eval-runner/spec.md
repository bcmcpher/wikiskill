# eval-runner Specification

## Purpose

Defines how explicit evaluations execute: fresh isolated headless sessions behind a harness backend
interface, three comparison conditions, repeats across a model matrix, endpoint preflight, and outcome
classes that separate model behaviour from infrastructure failure.

## Requirements

### Requirement: Evaluations run in fresh isolated sessions

Every evaluation run MUST execute in a new headless harness session with its own configuration, data
directories, and working directory. It MUST NOT run in the session that requested it, and MUST NOT
load the user's global or project skills, agents, MCP servers, or plugins beyond those under test.

Skills the harness ships itself MUST NOT be offered either: every skill is denied, and a unit allows
back only the skills its collection installed. The run's isolation proof MUST record the skills the
agent is offered under those rules, not every skill the harness knows of.

#### Scenario: Launch from inside OpenCode

- **WHEN** the user runs `/wikiskill-eval my-routing` in an OpenCode session
- **THEN** evaluation starts as a background process with a run id, and the calling session's
  context is not used for any task

#### Scenario: User has a global MCP server configured

- **WHEN** the user's global OpenCode config enables an MCP server
- **THEN** the run's captured configuration shows no MCP servers

#### Scenario: Harness with a built-in skill

- **WHEN** OpenCode ships `customize-opencode` regardless of the config directory
- **THEN** under OFF the run's isolation proof shows no skill offered and no skill tool, and under
  ROUTED it shows only the collection's skills

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
excluded from scores and reported separately with reasons. An `infra_error` MUST say whether it is
transient, and the run report MUST count the units that needed more than one attempt.

#### Scenario: Model prints a tool call instead of making one

- **WHEN** the assistant's final text contains a JSON tool-call object and the session has no tool parts
- **THEN** the run is classified `tool_call_as_text`, not `completed`

#### Scenario: Harness process crashes

- **WHEN** the headless harness exits abnormally before producing a session
- **THEN** the run is classified `infra_error`, marked transient, and does not count as a task
  failure

### Requirement: Components under evaluation run on the model under test

When a collection is installed into an evaluation run, the runner MUST remove every model pin from the
built components, so each subagent runs on the model the unit is evaluating. Build and install outside
evaluation MUST keep resolved pins.

#### Scenario: Pinned doer in an OpenCode run

- **WHEN** an agent declaring `model: haiku` is installed for a unit targeting `opencode/big-pickle`
- **THEN** the installed agent has no `model` key and runs on `opencode/big-pickle`

### Requirement: Suites declare their run environment

A suite MUST be able to declare, at suite and task level, environment variables and setup commands.
- The runner MUST set the variables in each unit's harness process, with a task's value overriding
  the suite's, and MUST NOT let them replace the variables it uses to isolate the run.
- It MUST run the setup commands in the unit's workdir, in order, with those variables, after
  fixtures are copied and before the session starts.
- A setup command that fails MUST make the unit an `infra_error`, never a model failure.
- A leading `~` and `$VAR` references in a value MUST be expanded against the invoking environment,
  and the expanded values MUST be the ones the harness process, the setup commands, the `requires`
  check and command verifiers all see.
- Both MUST be recorded in the run's captured configuration as the suite wrote them, unexpanded.

This is runner mechanics. The starting state a task needs belongs with whoever writes the task, and
a fixture read in place is never edited to carry it.

#### Scenario: DataLad autosave off

- **WHEN** a suite declares `env: { DATALAD_AUTOSAVE: "0" }`
- **THEN** every unit's harness process sees `DATALAD_AUTOSAVE=0`, and `run.json` records it

#### Scenario: A tool installed in a venv

- **WHEN** a suite declares `env: { PATH: "~/tools/venv/bin:$PATH" }` and `requires: [nipoppy]`, and
  `nipoppy` is only in that venv
- **THEN** the unit is not skipped, the harness, setup and verifiers all find `nipoppy`, and
  `run.json` records `~/tools/venv/bin:$PATH`

#### Scenario: A dataset to start from

- **WHEN** a task declares `setup: ["datalad create --force ."]`
- **THEN** the session starts in a workdir that is already a DataLad dataset

#### Scenario: Setup fails

- **WHEN** a setup command exits non-zero
- **THEN** the unit is recorded as `infra_error` with the command and its last output lines, and no
  session is started

### Requirement: Claude Code evaluation backend

The runner MUST provide a Claude Code backend that executes tasks with `claude -p` stream-json output in
an isolated configuration directory. It MUST support:
- OFF: without the plugin
- ROUTED: with the built collection via `--plugin-dir`
- INJECTED: component text appended to the system prompt with the `Skill` tool disallowed

#### Scenario: Isolation from user configuration

- **WHEN** the user has personal plugins, skills, and MCP servers configured in Claude Code
- **THEN** a Claude Code evaluation run loads none of them, and its run manifest shows only the
  collection under test

#### Scenario: Shared outcome classes

- **WHEN** a Claude Code run ends with the model printing a tool call as text
- **THEN** it is classified `tool_call_as_text`, exactly as on OpenCode

### Requirement: Runs keep the source text of the versions they evaluate

An evaluation run, on either backend (OpenCode or Claude Code), MUST store the text of every component
file it records a `source_hash` for in the collection's source snapshot store, keyed by that hash, so
the version can be shown later even after its source changes. A snapshot that already exists MUST NOT
be rewritten. A failure to store a snapshot MUST be reported as a warning and MUST NOT fail the run.

#### Scenario: First run of a version

- **WHEN** a run records `datalad-doer` at hash `h1` and no snapshot of `h1` exists
- **THEN** after the run the snapshot store holds the file's text under `h1`, and it hashes to `h1`

#### Scenario: Repeated version

- **WHEN** a second run records the same hash `h1`
- **THEN** the existing snapshot is left as it is

#### Scenario: Snapshot store not writable

- **WHEN** the snapshot store cannot be written
- **THEN** the run completes, its results are unaffected, and the warning names the store

### Requirement: A model's output cap and thinking are run options

For a provider wikiskill declares, the runner MUST cap each model turn's output (default 8192
tokens) and MUST tell the harness the context the server reported in preflight. `--thinking` MUST
accept `default`, `off` and `on`; anything but `default` MUST be sent with every request, the
preflight probe included. Both MUST be recorded in `run.json`, as `null` for a model the harness
serves itself, where wikiskill applies neither.

#### Scenario: Thinking off

- **WHEN** a run uses `--thinking off`
- **THEN** every request to the model, the preflight probe included, carries `reasoning_effort:
  none`, and `run.json` records `thinking: off`

#### Scenario: Thinking asked of a model that cannot

- **WHEN** a run uses `--thinking on` with a model the server says cannot think
- **THEN** preflight fails that model, naming `--thinking default or off`, and no unit runs on it

### Requirement: A unit lost to the harness is repaired without rerunning its run

A unit that ends `infra_error` because the harness crashed, could not export its session or could
not be launched MUST be marked transient by its backend. The runner MUST rerun a transient unit in
a fresh workdir up to `--retries` times (default 1) and MUST keep the earlier attempt's unit
directory. No other outcome MUST be retried, including timeouts and every scored outcome, pass or
fail. The unit's result MUST record its number of attempts and the error of each earlier attempt.

`wikiskill eval --fill RUN_ID` MUST rerun only that run's units that have no scored result, under
the settings recorded in its `run.json`, and MUST replace their lines in `results.jsonl` atomically,
keeping one line per unit. Each replaced line MUST be kept in `results.superseded.jsonl`, and every
fill MUST be listed in `run.json`. `--fill` MUST refuse a run whose suite hash, harness version or
component versions differ from the current ones, and MUST refuse any run setting given beside it.

#### Scenario: Harness crash on one unit

- **WHEN** OpenCode exits without a session on one unit of a 36-unit run, and the retry completes
- **THEN** the run has 36 scored units, that unit's result shows 2 attempts and the first error, and
  the crashed attempt's directory is kept

#### Scenario: Unit times out

- **WHEN** a unit exceeds its task's `timeout_s`
- **THEN** it is `infra_error` and is not retried

#### Scenario: Failed unit

- **WHEN** a unit completes and fails its verifiers
- **THEN** it is not retried, by `--retries` or by `--fill`

#### Scenario: Filling an incomplete run

- **WHEN** a run has one `infra_error` unit and `wikiskill eval --fill <run>` reruns it to completion
- **THEN** `results.jsonl` holds one line per unit, the old line is in `results.superseded.jsonl`,
  and `run.json` lists the fill with its time and versions

#### Scenario: Suite edited after the run

- **WHEN** the suite file has changed since the run, and the user asks to fill it
- **THEN** the fill is refused and names the hash that differs
