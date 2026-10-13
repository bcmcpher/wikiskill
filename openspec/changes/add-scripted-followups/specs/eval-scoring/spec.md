## ADDED Requirements

### Requirement: Runs that differ in follow-up turns are never pooled

`wikiskill leaderboard`, `wikiskill compare` and the version board MUST refuse to pool or compare a
run that sent scripted follow-up turns with a run that did not, when the suite declares
`followups` on any task. A run whose `run.json` does not record the option MUST count as one that
did not send them. For a suite with no `followups`, the option MUST NOT affect pooling.

#### Scenario: Mixed runs of a multi-turn suite

- **WHEN** a leaderboard is asked to pool two runs of a suite that declares `followups`, one made
  before follow-ups were sent and one after
- **THEN** it refuses, naming both runs and saying that one sent follow-up turns and one did not

#### Scenario: Single-turn suite

- **WHEN** a leaderboard pools a run made before this change and one made after, of a suite with no
  `followups`
- **THEN** it pools them as before
