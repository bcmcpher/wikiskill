## 1. Preflight: prove a local model runs end to end

- [x] 1.1 Catch timeouts and dropped connections in the tool-call probe and in `ollama_context`
- [x] 1.2 Give the probe its own `--probe-timeout` (120s HTTP, 300s harness)
- [x] 1.3 Read the served context from `/api/ps` before falling back to the environment
- [x] 1.4 Tests against a real local HTTP server (`tests/test_preflight.py`)
- [ ] 1.5 At least one Ollama model completes `toy-routing` OFF on a 16k server
- [ ] 1.6 Record which models pass, and at what context, for the quickstart

Rehearsal on 2026-09-29 (qwen3:1.7b, 16k context, i7-1185G7 laptop, CPU only) did not reach 1.5;
the machine was too slow, so 1.5 and 1.6 move to a machine that can serve a local model. Carry
forward:

- OpenCode's first turn is ~6.3k prompt tokens (system prompt plus 9 tool schemas). Cold prefill
  there ran at 8–22 tok/s, so the first request alone took ~13 min, past the 600s unit budget.
  The CPU was pinned near 1.2 GHz by the `power-saver` profile; check the power profile first.
- OpenCode's provider `timeout`, `headerTimeout` and `chunkTimeout` each default to 5 min, and
  Ollama sends no headers until prefill is done. All three are now disabled for `--base-url` runs.
- Ollama keeps computing a request after its client disconnects, so every later request queues
  behind it. A timed-out unit therefore delays the next unit and the next preflight probe.
- qwen3 thinks for ~350–650 tokens per turn. With `reasoning_effort: "none"` the first turn is a
  19-token `skill` call that routes correctly. Whether and how to expose this (a per-run option
  recorded in `run.json`, so thinking and non-thinking results are never pooled) is undecided.
- `Endpoint.is_ollama` only recognises port 11434 or "ollama" in the URL; a server on another
  port needs `--min-context 0`, and its context must be checked by hand via `/api/ps`.

## 2. Leaderboard

- [ ] 2.1 `wikiskill leaderboard <run>...`: load runs with `compare.load_run`, require one
      `suite_hash` and matching component `source_hash`es
- [ ] 2.2 Pool per model and condition with `compare.wilson`, rank, and mark overlapping intervals
- [ ] 2.3 A per-task by model matrix; write `leaderboard.md` and `leaderboard.json`
- [ ] 2.4 The same pooled table in a single run's `report.md`
- [ ] 2.5 Tests in `tests/test_leaderboard.py`

## 3. Packaging and docs

- [ ] 3.1 Build carries plugin `references/`, with a fixture plugin that reads one
- [ ] 3.2 `docs/quickstart.md`, a bring-your-own-collection guide, and templates
