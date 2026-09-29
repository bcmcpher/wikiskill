## Why

Montreal Brainhack (about 2026-10-05) is the first time people other than the author will run
wikiskill. Participants bring laptops with Ollama, run skill suites through OpenCode and compare pass
rates across models. Until now no local Ollama model had ever finished a run. Only `big-pickle` had,
through the harness. Nothing could pool runs from several machines, and a new user had no written
path from a clean install to a finished run.

## What Changes

- **Preflight survives slow and dying local servers.**
  - The tool-call probe gets its own timeout (`--probe-timeout`, default 120s over HTTP, 300s through
    the harness), because it is the request that loads the model.
  - A probe that times out or loses its connection is a failed preflight, not a crash.
  - The context check asks the running Ollama server what it serves (`/api/ps`), rather than
    trusting `OLLAMA_CONTEXT_LENGTH` in wikiskill's own environment.
- **`wikiskill leaderboard <run>...`** pools runs across machines, per model and condition, with
  Wilson intervals, and refuses runs whose suite or components differ.
- **Build carries plugin `references/`**, so skills that cite `${CLAUDE_PLUGIN_ROOT}/references`
  still resolve.
- **Docs:** a quickstart, a bring-your-own-collection guide and templates.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `eval-runner`: preflight timeouts and the server-reported context.

## Impact

- `src/wikiskill/runner/preflight.py`, `runner/opencode.py`, `cli.py`
- Later tasks: a new `leaderboard.py`, `report.py`, `build.py`, and `docs/`
- Out of scope: several endpoints in one run, passing API keys through, rubric judges
