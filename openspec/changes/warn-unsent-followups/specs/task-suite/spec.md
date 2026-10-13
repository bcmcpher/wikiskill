## ADDED Requirements

### Requirement: Unsent follow-up turns are reported

A suite check MUST report every task that declares `followups` as something to look at, naming the
task and stating that its scripted turns are not sent, for as long as no evaluation backend sends
them. It MUST NOT refuse the suite for it, and it MUST NOT change the suite's hash.

#### Scenario: A task declares follow-up turns

- **WHEN** a suite's task `ask-then-correct` declares `followups: ["Use the v2 tag instead."]`
- **THEN** `wikiskill suite check` prints a warning naming `ask-then-correct` and saying its follow-up
  turns are not sent, and exits zero

#### Scenario: No task declares follow-up turns

- **WHEN** no task in a suite declares `followups`
- **THEN** `wikiskill suite check` prints no follow-up warning
