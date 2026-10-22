## ADDED Requirements

### Requirement: A command verifier can declare a structured result

A `command` verifier MUST accept:
- `result: json`, meaning its stdout is a JSON object;
- `pass_when`, a mapping from a top-level result field to a non-empty list of accepted JSON scalar
  values;
- `score`, the name of a top-level numeric result field to aggregate.

Loading MUST fail when `pass_when` or `score` is set without `result: json`, when `pass_when` is
empty, or when any of the three is set on a verifier of another kind.

#### Scenario: A grader with a verdict

- **WHEN** a task declares a command verifier with `result: json`,
  `pass_when: {verdict: [acceptable, indistinguishable]}` and `score: score`
- **THEN** `wikiskill suite check` accepts the suite

#### Scenario: pass_when without a result

- **WHEN** a command verifier sets `pass_when` and no `result`
- **THEN** `wikiskill suite check` reports the problem and exits non-zero

#### Scenario: Result on a regex verifier

- **WHEN** a `regex` verifier sets `result: json`
- **THEN** `wikiskill suite check` reports the problem and exits non-zero
