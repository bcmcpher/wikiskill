# wikiskill OpenCode logger

A thin, passive plugin that appends wikiskill raw events for OpenCode sessions touching a watched
skill, subagent or command.

## Layout

| File | Role |
|---|---|
| `wikiskill-logger.ts` | hooks (`event`, `chat.message`, `command.execute.before`, `tool.execute.after`), all fail-open |
| `wikiskill/mapper.ts` | **pure** OpenCode event → raw record, and activation/delegation detection |
| `wikiskill/match.ts` | watch-list globbing, matching Python's `fnmatch` semantics |
| `wikiskill/redact.ts` | secret redaction and output bounds, pure |
| `wikiskill/sessions.ts` | session identity, the pre-activation ring buffer, the delegation tree |
| `wikiskill/writer.ts` | append-only writes and the logger error log |
| `wikiskill/config.ts` | reads `runtime.json`, published by the Python CLI |
| `wikiskill/hash.ts` | the component `source_hash`, cached by path *and* mtime/size |
| `wikiskill/types.ts` | the raw event shape, mirroring `schemas/raw-event.schema.json` |

`mapper.ts`, `match.ts` and `redact.ts` touch no clock, filesystem or environment — timestamps,
hashes and the environment snapshot are arguments. That is what makes the recorded-event contract
tests in `test/` meaningful.

## Versions

This plugin targets the OpenCode plugin API at **1.18.31 or newer**, declared here as a floor
(`^1.18.31`) rather than an exact pin. It is declared here rather than inherited from the user's
OpenCode config, which pins `@opencode-ai/plugin` 1.14.22 against a much newer binary.

The harness is updated regularly, so drift is *detected*, not pinned away:

- Event fixtures under `test/fixtures/` record the payload shapes this plugin was written against.
  Re-capturing them from a newer release is expected; the tests compare against the version recorded
  in the fixture (`RECORDED_VERSION`) and assert only that it is at or above
  `MIN_OPENCODE_VERSION`, so they do not break on an upgrade.
- `harness_version` is stamped on **every** event, so a drift is visible in the log itself rather
  than only at install time.

When an upgrade does change a payload shape, the mapper contract tests are what will fail — that is
their job. Re-capture the fixtures (see `test/fixtures/README.md`) and raise
`MIN_OPENCODE_VERSION`.

## Install

Do not copy these files by hand:

```bash
wikiskill install --harness opencode --scope global   # or --scope project
```

## Test

```bash
bun test test
```

To check an **installed** copy without needing a model — local models are slow and often cannot
call tools at all:

```bash
bun run test/drive-installed.ts ~/.config/opencode smoke-check ~/.config/opencode/skills/smoke-check
wikiskill log validate <collection>
```
