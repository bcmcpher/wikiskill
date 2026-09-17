## 0. Minimal working core

All three behaviours are already implemented and tested, in commit `8baedeb` — the change was
written after the fact to record a contract the code already meets, so its tasks describe existing
work rather than work to schedule. The smallest shippable slice is therefore the whole change: three
requirements, each with tests already in the suites named under Verify.

Nothing is deferred. One question about a sibling change is left open in design.md (whether Claude
Code reports a tool duration); it affects `add-claude-code-adapter`, not anything here.

A task below is checked only where the behaviour and its test both exist. Group 4 records the
commands that were run, and when.

## 1. Tool call outcomes

- [x] 1.1 Track terminal OpenCode tool parts by call id, keeping the outcome bounded, and verify
  `harness/opencode/plugin/wikiskill/toolstate.ts` derives ok, error and duration only from a
  `completed` or `error` state (`bun test test/logger.test.ts`, "a running call is not recorded
  until it finishes")
- [x] 1.2 Record a failed call from its tool part, since `tool.execute.after` does not fire for one,
  and verify the event is marked not ok and carries the harness's error text ("a failed tool call is
  recorded as failed, with its duration")
- [x] 1.3 Let the part and the hook each claim a call id so one call yields one event, and verify a
  call described by both is written once with a real duration ("a completed call carries a real
  duration and is written once")
- [x] 1.4 Confirm every emitted event still validates against the raw schema, including a failed
  call, via the cross-language contract test (`uv run --extra dev pytest
  tests/test_plugin_contract.py`)

## 2. Session state release

- [x] 2.1 Track each session's last activity and prune on it rather than on its start time, and
  verify a session that is still producing events survives ("staleness follows the last activity,
  not the session's start")
- [x] 2.2 Prune logged sessions on the same terms as any other, and verify a quiet logged session is
  released ("a logged session is released too, once it has gone quiet")
- [x] 2.3 Confirm releasing state does not touch what is already written, by verifying the log file
  is unchanged after a prune (covered by the writer and logger suites: `bun test`)

## 3. Build output ownership

- [x] 3.1 Write a marker into every build output directory and require it before clearing one, and
  verify a directory holding foreign files is refused with its path named
  (`tests/test_build.py::test_build_refuses_to_erase_a_directory_it_does_not_own`)
- [x] 3.2 Keep accepting an empty directory and a previous build's output, and verify a removed
  component disappears on rebuild (`test_build_uses_an_empty_directory_without_complaint`,
  `test_build_clears_stale_output`)
- [x] 3.3 Exclude the marker from what `install` stages, and verify no installed file is the marker
  (`test_the_build_marker_is_not_installed`)

## 4. Verify

Run from the repository root. All four were run on 2026-09-17 against commit `8baedeb` plus this
change's artifacts.

- [x] 4.1 `uv run --extra dev pytest` — 170 passed
- [x] 4.2 `bun test` in `harness/opencode/plugin` — 152 passed
- [x] 4.3 `bunx tsc --noEmit` in `harness/opencode/plugin`, and `uv run --extra dev ruff check` —
  both clean
- [x] 4.4 `openspec validate add-logging-safeguards --strict --no-interactive` — valid
