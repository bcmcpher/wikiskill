## 1. Shared budget

- [ ] 1.1 OpenCode guard: keep the step count in `WIKISKILL_STEP_FILE` in the unit root, matching
  the Python guard; verify with `bun test` that two guard instances sharing a file enforce one
  budget
- [ ] 1.2 Runner: one deadline per unit, each turn's subprocess given the remaining time; verify
  with a unit test using a fake executable that a slow second turn times the unit out

## 2. Turn loop

- [ ] 2.1 OpenCode backend: after a `completed` first turn, send each follow-up with `opencode run
  -s <session_id>` in the same directories; verify with a contract test on a recorded multi-turn
  stream that the session id is unchanged across turns
- [ ] 2.2 Claude Code backend: the same with `claude -p --resume <session_id>`; verify with a test
  against a recorded stream
- [ ] 2.3 Stop on a non-`completed` turn and record `turns_sent` in the result; verify with tests for
  a step-exhausted second turn and a blocked first follow-up
- [ ] 2.4 Read back once after the last turn: `final_text` from the last answer, `transcript` and
  activations from all turns; verify with a test that a regex on `final_text` sees only the last
  answer and one on `transcript` sees the first

## 3. Run record and pooling

- [ ] 3.1 `run.json` `options.followups = "sent"`; verify with a test
- [ ] 3.2 Leaderboard, compare and version board refuse to mix `sent` and unrecorded runs of a suite
  that declares `followups`, and pool them for a suite that does not; verify with tests for both

## 4. Remove the interim warning

- [ ] 4.1 Remove the follow-up warning from the suite loader and reword the schema description;
  verify the warning tests from `warn-unsent-followups` are replaced by tests that it is absent

## 5. Live check and documentation

- [ ] 5.1 Run a two-follow-up task live on one local model under OpenCode and under Claude Code;
  confirm in `exports/` that all turns are in one session and the verdict follows the last turn
- [ ] 5.2 `docs/data.md` (`turns_sent`, `options.followups`), `docs/writing-suites.md` (when to use
  follow-ups, raising `timeout_s`), and the guide's task-field table; verify `bin/check` passes
