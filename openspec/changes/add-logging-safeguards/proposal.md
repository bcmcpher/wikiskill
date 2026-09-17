## Why

Three behaviours shipped with `add-trace-logging` that its specs do not describe: failed tool calls
are now recorded rather than silently absent, session state is released on inactivity rather than
held forever, and `wikiskill build` refuses to erase a directory it does not own. Each came out of a
review of the implementation, not the design, so the specs claim less than the code does. A reader
of `openspec/specs/` cannot tell that a failed call is logged at all, and a later change could
remove any of the three without a scenario failing.

## What Changes

- Record a tool call's outcome: whether it succeeded, its error when it failed, and its duration.
  The OpenCode `tool.execute.after` hook carries none of these and does not fire when a tool throws,
  so failures were absent from the log while every recorded call claimed success.
- Release per-session logger state after a bounded period of inactivity, including for sessions that
  are being logged, measured from the session's last activity rather than from when it started.
- Refuse to clear a build output directory that is not build output, so pointing `--out` at a
  harness config directory cannot delete the user's configuration.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `trace-log`: two added requirements — a tool call records its outcome, and per-session logger
  state is released once a session goes quiet.
- `harness-packaging`: one added requirement — a build only clears output it owns.

## Impact

- `harness/opencode/plugin/wikiskill/toolstate.ts`, `wikiskill-logger.ts`, `wikiskill/sessions.ts`,
  and `src/wikiskill/build.py` already implement all three behaviours, with tests, as of commit
  `8baedeb`. This change records the contract they now meet; no further implementation is expected.
- No dependency on another change. `add-trace-logging` (roadmap step 1) is archived, and this
  amends two of the capabilities it introduced.
- `add-claude-code-adapter` inherits the tool-outcome fields: Claude Code's `PostToolUse` hook
  reports success and failure directly, so its adapter satisfies the same requirement without the
  tool-part machinery OpenCode needs.
