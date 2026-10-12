## ADDED Requirements

### Requirement: Scripted follow-up turns are sent in the same session

When a task declares `followups`, each unit MUST send them as user turns, in order, in the same
session as the first prompt, each after the model's answer to the previous turn. This MUST hold
under every condition and for both the OpenCode and the Claude Code backends.

The unit's `timeout_s` and `max_steps` MUST cover all turns together. When a turn ends the unit by
exhausting either budget, or with an outcome other than `completed`, the remaining turns MUST NOT be
sent, and the unit MUST record how many turns were sent.

Verifiers MUST run once, after the last turn sent. `final_text` MUST be the model's answer to that
turn, and `transcript` MUST cover every turn. A unit's route MUST be its first activation across
all turns.

#### Scenario: Two follow-up turns under OpenCode

- **WHEN** a task declares two `followups` and its unit runs under OpenCode
- **THEN** the session receives the prompt and both follow-ups in order, `final_text` is the answer
  to the second follow-up, and the unit records three turns sent

#### Scenario: Claude Code backend

- **WHEN** the same task runs with `--harness claude-code`
- **THEN** the follow-ups are sent in the same session, and the unit records three turns sent

#### Scenario: Step budget shared across turns

- **WHEN** a task declares `max_steps: 4`, the model makes three tool calls in the first turn, and
  two in the first follow-up
- **THEN** the fifth call is refused, the unit is `step_exhausted`, the second follow-up is not sent,
  and the verifiers run against the state the first follow-up left

#### Scenario: No follow-ups

- **WHEN** a task declares no `followups`
- **THEN** the unit runs one turn, exactly as before this change

### Requirement: Runs record whether follow-ups were sent

`run.json` MUST record in its options whether the runner sent scripted follow-up turns.

#### Scenario: A run on this version

- **WHEN** `wikiskill eval` runs any suite
- **THEN** `run.json` options record that follow-ups are sent
