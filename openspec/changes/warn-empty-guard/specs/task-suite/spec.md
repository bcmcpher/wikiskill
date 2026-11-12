## ADDED Requirements

### Requirement: A task guard that drops suite deny patterns is reported

A suite check MUST report, as something to look at, every task whose own `guard` leaves out a deny
pattern that the suite defaults declare. The report MUST name the task and each dropped pattern, and
MUST say that the runner's own base denies still apply. It MUST NOT refuse the suite for it, and it
MUST NOT change the suite's hash. A task that does not set `guard`, or whose `guard` keeps every
default pattern, MUST NOT be reported.

#### Scenario: An empty guard drops the suite's patterns

- **WHEN** the suite defaults set `guard: {deny: ["git push*", "datalad push*"]}` and the task
  `release` sets `guard: {}`
- **THEN** `wikiskill suite check` prints a warning naming `release` and both `git push*` and
  `datalad push*`, and exits zero

#### Scenario: A narrower guard drops one pattern

- **WHEN** the suite defaults set `guard: {deny: ["git push*", "datalad push*"]}` and the task
  `publish` sets `guard: {deny: ["git push*"]}`
- **THEN** `wikiskill suite check` prints a warning naming `publish` and `datalad push*` only

#### Scenario: A task that adds to the suite's patterns

- **WHEN** the suite defaults set `guard: {deny: ["git push*"]}` and a task sets
  `guard: {deny: ["git push*", "rm -rf *"]}`
- **THEN** `wikiskill suite check` prints no guard warning for that task

#### Scenario: A suite with no default guard

- **WHEN** the suite defaults set no `guard` and a task sets `guard: {}`
- **THEN** `wikiskill suite check` prints no guard warning
