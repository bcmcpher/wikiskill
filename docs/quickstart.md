# Quickstart: from a clean machine to a finished run

This takes you from nothing to one evaluated suite on a local model, and then to a result you can
pool with other people's. Budget 20 minutes plus model downloads.

## 1. What you need

| Tool | Tested with | Why |
|---|---|---|
| `git`, [`uv`](https://docs.astral.sh/uv/) | uv 0.12 | to get and install wikiskill |
| [OpenCode](https://opencode.ai) | 1.18.34 (1.18.31 or newer) | the harness each task runs in |
| [Ollama](https://ollama.com) | 0.34.2 | serves the models under test |

A GPU or Apple Silicon helps a great deal. OpenCode's first turn is about 6,300 prompt tokens before
the model says anything; a CPU-only laptop prefilling at 8–22 tokens a second spends over ten
minutes on that turn alone, which is past a unit's budget. If you are on a laptop CPU, plug in and
switch off power-saving first — a throttled CPU made one rehearsal three times slower.

## 2. Install

```bash
git clone https://github.com/bcmcpher/wikiskill.git
cd wikiskill
uv tool install .
wikiskill --version
```

Stay in this directory: the example suite below lives in the clone.

Everyone whose results will be pooled must run the **same commit**. The leaderboard refuses runs
whose suite or skill files differ, so check out the commit you are told to before you start.

## 3. Serve a model with enough context

OpenCode needs at least 16k tokens of context. Ollama may serve less: on a machine with little
memory its default is 4096, and preflight will refuse the model with a message saying so. Set the
context **where the Ollama server runs**, not in the shell you run wikiskill from:

- **Linux (systemd):** `sudo systemctl edit ollama`, add the lines below, then
  `sudo systemctl restart ollama`.

  ```ini
  [Service]
  Environment="OLLAMA_CONTEXT_LENGTH=16384"
  ```

- **macOS (the app):** `launchctl setenv OLLAMA_CONTEXT_LENGTH 16384`, then quit and reopen Ollama.
- **Running `ollama serve` yourself:** `OLLAMA_CONTEXT_LENGTH=16384 ollama serve`.

Then pull a model that can call tools:

```bash
ollama pull qwen3:1.7b
```

Models tried so far, on one machine (NVIDIA GB10, toy-routing pooled over two runs, 2026-10-01):

| Model | Size | Preflight | Passed under ROUTED | Typical unit |
|---|---|---|---|---|
| `qwen3:1.7b` | 1.4 GB | ok | 4 of 6 | 15 s; once spent ten minutes thinking on one turn |
| `ministral-3:3b` | 3.0 GB | ok | 3 of 6 | 10 s |
| `gemma4` | 9.6 GB | ok | 5 of 6 | 15 s |
| `qwen3:30b-a3b` | 18 GB | ok | 2 of 3 (one run) | 35 s |
| `qwen2.5-coder:1.5b` | 1.0 GB | **refused** | — | answers in text instead of calling a tool, so it would score zero for reasons unrelated to any skill |

"Passed" counts the two routing tasks and the control together; a typical unit is the median of the
second run. Every one of those intervals overlaps the others: the table says which models work, not
which is better. That is what pooling many people's runs is for.

## 4. Point wikiskill at a collection

A *collection* is the set of skills, agents and commands under test. wikiskill's own components make
a small one:

```bash
wikiskill collection init wikiskill-self --source harness/source
wikiskill collection check wikiskill-self
```

`check` ends with `ok`. It writes nothing into the source directory, ever.

## 5. Check the model, then run the suite

`examples/suites/toy-routing.yaml` asks three questions: two that should reach the
`wikiskill-trace` skill, and one that should reach nothing.

```bash
wikiskill eval --suite examples/suites/toy-routing.yaml --collection wikiskill-self \
  --base-url http://localhost:11434/v1 --models ollama/qwen3:1.7b --preflight-only
```

Preflight checks that the server answers, that the model makes a real tool call, and that it is
served with enough context. The first probe loads the model, so it can take a minute. When it says
`ok`, run the suite:

```bash
wikiskill eval --suite examples/suites/toy-routing.yaml --collection wikiskill-self \
  --base-url http://localhost:11434/v1 --models ollama/qwen3:1.7b \
  --condition off,routed,injected
```

Each task runs in a fresh, isolated OpenCode session, under three conditions:

- **off** — no skills installed: the baseline
- **routed** — the collection installed, and the model has to find the right skill itself
- **injected** — the skill's text given to the model directly, and loading it forbidden

On a GPU one unit takes seconds to a few minutes. The command prints each unit as it finishes and
ends with the path to `report.md`.

Two options change how the model behaves, so both are recorded with the run:

- `--thinking off` (or `on`) tells a model whether to reason before answering. Left at `default`,
  models differ — qwen3 thinks unasked, gemma4 does not. Runs with different settings appear as
  separate rows in the leaderboard and are never pooled together, so trying both is a fair
  comparison.
- `--max-output-tokens` caps one model turn, thinking included (default 8192). A model that would
  otherwise think for minutes is cut off and scored on what it produced.

Every unit starts from empty OpenCode directories, which by default means OpenCode downloads its
packages, ripgrep and its model catalog again for every unit. Instead, the first unit that finishes
cleanly leaves a copy of those downloads in `~/.cache/wikiskill/opencode-seed/<opencode-version>/`,
and every later unit starts from that copy. Copy the folder to another machine with the same
OpenCode version and that machine skips the downloads too. To return to a fresh download per unit,
pass `--no-seed-cache` or delete the folder.

## 6. Read the report

Results land in `~/.local/share/wikiskill/wikiskill-self/evals/<run-id>/`. `report.md` has:

- **Pooled per model and condition** — passes out of units, with a 95% interval
- **Per task, model and condition** — `route@1` is whether the model's *first* choice was the
  expected skill
- **Not run** — anything skipped or failed for reasons that are not the model's, with the reason

A task with no expected route is judged by its verifiers instead; `pass basis` says which. A unit
that did not run is listed, never counted as a failure.

## 7. Pool your run with everyone else's

Send the two files that describe your run:

```bash
cd ~/.local/share/wikiskill/wikiskill-self/evals
tar czf my-run.tgz <run-id>/run.json <run-id>/results.jsonl
```

Whoever collects them unpacks every archive into one directory and runs:

```bash
wikiskill leaderboard runs/*/
```

It pools units per model and condition across machines, refuses any run whose suite or skill files
differ, and marks with `≈` every model whose interval overlaps the leader's — so a place in the
table is not mistaken for a finding.

## When something goes wrong

| You see | It means |
|---|---|
| `... answered the tool-call probe with text` | the model cannot call tools; choose another |
| `... cannot think, and this run asks it to` | drop `--thinking on` for that model |
| `... is served with a 4096-token context` | set `OLLAMA_CONTEXT_LENGTH` on the server (step 3) and restart it |
| `did not answer the tool-call probe within 120s` | the model is still loading; retry, or pass `--probe-timeout 300` |
| a unit ends `timed out after 600s` | the model is too slow here; a smaller model, or `--thinking off`, helps |
| `step_exhausted` | the model kept calling tools past the task's step budget instead of answering |
| every unit stalls after a timeout | Ollama keeps working on a request after its client has gone; wait, or restart Ollama |

To evaluate your own skills, see [bring your own collection](bring-your-own-collection.md).
