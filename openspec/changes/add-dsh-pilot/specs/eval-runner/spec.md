## ADDED Requirements

### Requirement: A run can set its repeats without changing the suite

`eval --repeats N` MUST run every task N times in place of the suite's repeats, and MUST refuse N
below 1. `run.json` MUST record each task's repeats as run. The suite hash MUST stay the hash of the
suite file, so a run at other repeats pools with runs of the same suite.

#### Scenario: More repeats on an unchanged suite

- **WHEN** a suite declaring `repeats: 3` is run with `--repeats 10`
- **THEN** each task runs 10 times per model and condition, `run.json` records `repeats` of 10 for
  every task, and its `suite_hash` equals that of a run without the flag, so the two pool
