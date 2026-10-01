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

## 1b. Findings from the first GB10 run (2026-10-01)

- [x] 1b.1 Read frontmatter Claude Code accepts (unquoted `argument-hint: [x] text`) as plain text,
      warn in build, and have `collection check` report lenient and unreadable frontmatter
- [x] 1b.2 Deny every skill but the collection's, so OpenCode's built-in `customize-opencode` never
      reaches OFF; the isolation proof records the agent's offered skills and its skill tool
- [x] 1b.3 Read `opencode debug` output from a file: through a pipe it stopped at 64 KB, so ROUTED
      proofs for a real collection recorded no skills
- [x] 1b.5 Let a unit read its installed `skills/` and `plugins/`: the eval's `external_directory`
      deny came after OpenCode's own allowance for skill directories, so no model could read a file
      beside a skill it had loaded, its own `references/` included
- [ ] 1b.4 A runaway generation (qwen3:1.7b, 9m48s on one request) is scored infra_error; decide on
      a per-turn output cap or a recorded thinking setting

## 2. Leaderboard

- [x] 2.1 `wikiskill leaderboard <run>...`: load runs with `compare.load_run`, require one
      `suite_hash` and matching component `source_hash`es
- [x] 2.2 Pool per model and condition with `compare.wilson`, rank, and mark overlapping intervals
- [x] 2.3 A per-task by model matrix; write `leaderboard.md` and `leaderboard.json`
- [x] 2.4 The same pooled table in a single run's `report.md`
- [x] 2.5 Tests in `tests/test_leaderboard.py`
- A route-scored unit counts only under ROUTED: OFF installs nothing and INJECTED denies the skill,
  so counting it there adds a failure by construction. Units that did not run sit beside the rate.

## 3. Packaging and docs

- [x] 3.1 Build carries plugin `references/`, with a fixture plugin that reads one. A plugin is
      mirrored to `plugins/<plugin>/`; `${CLAUDE_PLUGIN_ROOT}` and `${CLAUDE_SKILL_DIR}` are expanded
      to the installed paths, as Claude Code expands them; `collection check` warns of cited paths
      that resolve to nothing (84 in my-skills, written as if the variable were the skill's own
      directory, or climbing out with `../`)
- [ ] 3.2 `docs/quickstart.md`, a bring-your-own-collection guide, and templates
