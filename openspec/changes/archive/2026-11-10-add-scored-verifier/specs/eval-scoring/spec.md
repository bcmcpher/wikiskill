## ADDED Requirements

### Requirement: A structured result decides pass by its declared fields

For a command verifier with `result: json`, the runner MUST parse stdout as one JSON object, or, if
that fails, its last non-empty line. Output that yields no JSON object MUST make the unit an
`infra_error` naming the verifier. The parsed object MUST be stored with the verifier's record in
`results.jsonl`, and a result over 64 KiB once serialised MUST be an `infra_error`. The verifier MUST
pass only when the exit code equals `expect_exit` and every `pass_when` field is present and equal to
one of its accepted values. A failing verifier's detail MUST name each field that did not match and
the value it held.

#### Scenario: Acceptable verdict

- **WHEN** the scorer exits 0 and prints `{"verdict": "acceptable", "score": 71.5}`, and
  `pass_when` is `{verdict: [acceptable, indistinguishable]}`
- **THEN** the verifier passes, and `results.jsonl` holds the object under that verifier

#### Scenario: Valid but marginal

- **WHEN** the scorer exits 0 and prints `{"verdict": "marginal", "score": 41}`
- **THEN** the verifier fails, and its detail names `verdict` and `marginal`

#### Scenario: Invalid output exits non-zero

- **WHEN** the scorer exits 1 and prints `{"verdict": "invalid", "score": 0}`, and `expect_exit` is 0
- **THEN** the verifier fails, and the result is stored

#### Scenario: Log lines before the result

- **WHEN** stdout is two log lines followed by a JSON object on its last line
- **THEN** the last line is parsed as the result

#### Scenario: Scorer crash

- **WHEN** stdout holds a Python traceback and no JSON object
- **THEN** the unit is an `infra_error` naming the verifier, and is left out of the pass-rate
  denominator

#### Scenario: negate

- **WHEN** a verifier with `result: json` also sets `negate: true`
- **THEN** it passes exactly when the same verifier without `negate` would fail

### Requirement: Scores are reported beside the pass rate

For each verifier with `score`, a run report MUST give, per task, model and condition, the mean of
that field over scored units, the count of units it covers, and a 95% t-interval of the mean,
mean ± t(0.975, n−1)·s/√n, not clipped to the scorer's scale. With one unit there MUST be no
interval, and identical scores MUST be marked as such rather than printed as a range. A unit whose
field is missing or not a number MUST be left out and counted beside the mean. `infra_error` and
`skipped` units MUST be left out. The score MUST NOT change the pass rate.

#### Scenario: Three repeats

- **WHEN** three units of a task score 60, 70 and 80
- **THEN** the report gives mean 70, n 3, and an interval of 45.2 to 94.8, to one decimal

#### Scenario: Rebuilt report

- **WHEN** `wikiskill report` rebuilds a finished run's report twice
- **THEN** both give the same means and intervals

#### Scenario: Non-numeric score

- **WHEN** one of four units prints `{"verdict": "invalid", "score": null}`
- **THEN** the mean covers three units, and the report counts one without a score

#### Scenario: Run made before this change

- **WHEN** a report is rebuilt for a run whose verifiers declared no `score`
- **THEN** it has no score section, and its rates are unchanged
