## ADDED Requirements

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

## MODIFIED Requirements

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
