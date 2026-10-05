## 1. Preflight: prove a local model runs end to end

- [x] 1.1 Catch timeouts and dropped connections in the tool-call probe and in `ollama_context`
- [x] 1.2 Give the probe its own `--probe-timeout` (120s HTTP, 300s harness)
- [x] 1.3 Read the served context from `/api/ps` before falling back to the environment
- [x] 1.4 Tests against a real local HTTP server (`tests/test_preflight.py`)
- [x] 1.5 At least one Ollama model completes `toy-routing` OFF on a 16k server
- [x] 1.6 Record which models pass, and at what context, for the quickstart

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

Done on 2026-10-01 on an NVIDIA GB10 (Ollama 0.34.2, OpenCode 1.18.34), two runs of toy-routing
under OFF, ROUTED and INJECTED (`01M3WK8CCMNH60QTB1KHWKPGYB`, `01M3WNDM7QH52GTMST14ERCR80`): 56
units completed, 7 skipped by design, no timeouts and no exhausted step budgets. Served contexts
were each model's own maximum or the server's default for this memory: qwen3:1.7b 40k, gemma4
128k, ministral-3:3b and qwen3:30b-a3b 256k. Pooled under ROUTED: gemma4 5/6, qwen3:1.7b 4/6,
qwen3:30b-a3b 2/3 (one run), ministral-3:3b 3/6, every interval overlapping. qwen2.5-coder:1.5b
fails the tool-call probe. Run 1's units took 1–4 minutes and run 2's 10–35 s; run 1 overlapped a
large model download, which is the likely cause but was not isolated. The quickstart's table
carries these.

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
- [x] 1b.4 A runaway generation (qwen3:1.7b, 9m48s on one request) is scored infra_error. Both
      answers: `--max-output-tokens` (default 8192) caps a turn through OpenCode's `limit.output`,
      which needs `limit.context` beside it, so preflight's served context is passed on; and
      `--thinking default|off|on` sends `reasoning_effort`, which OpenCode passes on only for a model
      marked `reasoning`. Both are recorded in `run.json`; the leaderboard keeps thinking settings
      apart and warns on differing caps. qwen3:1.7b with thinking off: one ROUTED unit in 5.6 s

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
- [x] 3.2 `docs/quickstart.md`, a bring-your-own-collection guide, and templates. Walked from a
      fresh clone with `uv tool install .` and empty XDG directories, through preflight and one
      real unit; both templates validate as written and with every option enabled

## 4. Before the event (about 20 GB10s for participants)

- [x] 4.1 Seed each unit's OpenCode cache from one shared per-machine copy. Every unit now installs
      OpenCode's npm packages (63 MB, into `config/opencode/node_modules`) and downloads ripgrep and
      `models.json` into its own fresh cache: about 2.3 GB for one toy-routing run, or ~45 GB across
      20 machines on event Wi-Fi, and a registry hiccup fails units. First confirm OpenCode skips
      its install when the packages are already present
      **Implemented 2026-10-05, not yet run against a live OpenCode.** The first unit (or
      preflight probe) that exits cleanly copies `cache/opencode/` and OpenCode's `node_modules`,
      `package.json` and lockfile into `~/.cache/wikiskill/opencode-seed/<version>/`; later units
      start from a copy. `--no-seed-cache` turns it off, and `run.json` records which.
      **Run on the GB10 2026-10-05** (OpenCode 1.18.34, gemma4, toy-routing OFF and ROUTED). The
      first seeding run (`01M46AN0XEH2YEH99HMKZJXYT0`) failed one unit, the first ROUTED one, with
      `[Errno 17] File exists` on `node_modules/.bin` symlinks: the isolation proof prepares that
      unit and its `opencode debug` calls install packages, then the unit prepares again and the
      seed was copied over them. `_apply_seed` now leaves any path the root already has; regression
      test in `test_runner_opencode.py`. After the fix, seeded (`01M46AZ1DKYBZ64FHQ13F8ZSZ7`) and
      unseeded (`01M46B3PZ5XQWJJX068SFX3GWS`) pool in one leaderboard: ROUTED routes 2/2 each,
      control 1/2 and 0/2 against 1/2 on 2026-10-01. A seeded unit leaves 3647 of 3648 seeded files
      untouched (72 MB seed); the one it rewrites is `cache/opencode/models.json`, 5.3 MB and
      byte-identical, which OpenCode re-downloads every run. `OPENCODE_DISABLE_MODELS_FETCH` would
      stop that, at the cost of running on the seed's catalog; not set yet
- [ ] 4.2 Pre-stage models on every machine: pull once and copy Ollama's model store, or pull well
      ahead (qwen3:30b-a3b took two hours here)
- [ ] 4.3 Pin one OpenCode and one Ollama version on every machine. OpenCode updates itself in
      interactive use; the leaderboard only warns about mixed versions after the fact
- [ ] 4.4 Choose and freeze the suite participants run. toy-routing proves the pipeline but its three
      tasks will not separate models; candidates are the data-science-harness suites, or
      `my-skills` once its 84 unresolved plugin paths are fixed. Its hash must not change after
- [ ] 4.5 Decide how runs are collected (`run.json` and `results.jsonl` per run) and who runs
      `wikiskill leaderboard` over them
- [ ] 4.6 Rehearse the quickstart on one event GB10 as a participant, from its stock accounts and
      software; the walk-through here had OpenCode, Ollama and uv already installed
- [ ] 4.7 Tag the commit participants check out, and announce it
- [x] 4.8 Update the README's Status paragraph, which still says step 3 is next
- [ ] 4.9 After the event: pool the runs, record what they showed, and archive this change
