## 0. Minimal working core

The loop runs once on `datalad/datalad-doer`, end to end:
- the build fixes and unit scoping (1.x)
- the doer suite and a v1 run (2.x)
- a headless review (3.1–3.3)
- a headless refine (4.1–4.2)
- the user applying the patch, then a v2 run and `wikiskill compare` (5.x, 6.1)

Deferred:
- the in-harness `/wikiskill-review` and `/wikiskill-refine` commands (3.4, 4.3), until the headless
  path produces sensible output
- rebasing the later changes (7.x), which is bookkeeping and can land any time before they are applied

## 1. Build and scope

- [x] 1.1 `collection.py`: `plugins = [...]` on claude-plugin sources, honoured by `discover()`.
  Report unknown plugins as unresolved.
- [x] 1.2 `collection.py`: alias-to-alias resolution, one hop at most. `collection check` rejects cycles
  and chains that do not end in `provider/model`.
- [x] 1.3 `build.py`: map `tools:` to capabilities (an explicit `capabilities:` wins, unknown tools
  warn, the source `tools` key is dropped), and resolve `model:` as an alias when `role_model` is
  absent.
- [x] 1.4 `build.py`: `build_collection(harness, collection, out_dir, *, strip_models=False)`, with
  `_component_roots` moved in from `runner/opencode.py`. It checks for flat-name collisions before
  merging and returns the name mapping.
- [x] 1.5 `runner/opencode.py:_install_collection` uses `build_collection(..., strip_models=True)`.
  `cli.cmd_build` builds the collection's sources when `--collection` is given and prints the mapping.
- [x] 1.6 Tests: tools→permissions, tier resolution and cycle rejection, collision, `strip_models`,
  plugin filter, and a source tree left byte-identical.
- [x] 1.7 `examples/collections/data-science-harness.toml`: tier aliases (`small`, `large`, and
  `haiku`/`sonnet`/`opus` pointing at them) and a commented `plugins` example. Update
  `tests/test_example_manifest.py`.

## 2. First unit: datalad-doer

- [x] 2.1 `suite.py` and `schemas/task-suite.schema.json`: `env` at suite and task level. The runner
  sets it in `_env` and records it in `run.json`.
- [x] 2.1a `setup:` commands at suite and task level, run in the workdir after fixtures and before
  the session, with the task's env. A failure is `infra_error`. They are recorded in `run.json`.
  Setup is runner mechanics, not a DSH fixture field (see `bench/README.md`).
- [x] 2.2 `pilots/datalad-doer/dsh-datalad.toml` (named for the collection, which is loaded by name): the DSH
  source with `plugins = ["datalad"]`.
- [x] 2.3 `pilots/datalad-doer/suite.yaml`: about five capability tasks with command verifiers
  (`datalad status`, `git log`, file checks).
  - Fixture setup runs `datalad create` in the workdir.
  - `env: { DATALAD_AUTOSAVE: "0" }`.
  - The guard denies `datalad push|siblings`, `git push` and network CLIs.
  - No prompt names the doer or DataLad's own commands.
- [x] 2.4 `wikiskill suite check pilots/datalad-doer/suite.yaml` passes.
- [ ] 2.5 v1 run on `opencode/big-pickle`, OFF and INJECTED (the doer invoked directly), repeats as
  chosen at run time. Run it detached, and record the run id.
- [ ] 2.6 Live check: one INJECTED transcript shows the doer running bash, and one guard denial is
  visible.

## 3. Minimal review

- [x] 3.1 `schemas/maintainer-output.schema.json` (create, update, index, log) and a validator in
  `src/wikiskill/wiki.py`, with at most two re-prompts.
- [x] 3.2 `src/wikiskill/wiki.py`: initialise `<collection>/wiki/` as a git repository. Apply
  validated output and commit.
- [x] 3.3 `wikiskill review <component>`: collect that component's eval results and raw sessions within
  a character budget, call `roles.maintainer` headless, and apply. Add the
  `harness/source/agents/wikiskill-maintainer.md` prompt.
- [ ] 3.4 (deferred) `harness/source/commands/wikiskill-review.md` for in-harness use.

## 4. Minimal refine

- [ ] 4.1 `src/wikiskill/refine.py` and `wikiskill refine <component>`: exactly one `patch` or
  `no_action` result. Write `wiki/proposals/<id>/{patch.diff,preview.md,meta.json}`. Reject a
  proposal that cites no pattern. Add the `harness/source/agents/wikiskill-proposer.md` prompt.
- [ ] 4.2 The patch applies cleanly with `git apply --check` in the source repository. wikiskill itself
  never writes there.
- [ ] 4.3 (deferred) `harness/source/commands/wikiskill-refine.md`.

## 5. Version comparison

- [x] 5.1 `src/wikiskill/compare.py`: load two runs, and refuse ones whose suite or task ids differ.
  Warn when the component hash is the same in both. List unmatched models.
- [x] 5.2 Wilson 95% intervals for each model, pooled, and each condition. Report the direction, or
  "no detectable difference" when the intervals overlap. Add a pooled row that counts timeouts
  as failures (they are `infra_error`, and so excluded from every other row).
- [x] 5.3 Tool-choice distribution per condition and version, from the runs' raw-log trajectories.
- [x] 5.4 `wikiskill compare <a> <b> [--record accept|reject --proposal <id>]`. Write `compare.md` and
  `compare.json`, and append to `skill-impact.md` when recording.
- [x] 5.5 Tests: overlapping and separated intervals, a suite mismatch, the timeout row, and
  tool-choice counts from fixture trajectories.

## 6. Close the loop

- [ ] 6.1 The user applies the 4.1 patch. Run v2 with the same suite and models, then
  `wikiskill compare` v1 v2 and record the decision.
- [ ] 6.2 Write `docs/pilots/datalad-doer.md`: the unit, the models, what was unrun and why, the
  comparison table, and the decision.

## 7. Roadmap bookkeeping

- [ ] 7.1 Add a task to `add-experience-wiki` and `add-skill-refinement` to rebase their deltas onto
  the `experience-wiki` and `refinement-proposal` specs this change introduces.
- [ ] 7.2 Reshape `add-dsh-pilot` into per-unit pilots on this loop, with the full routing probe
  optional.

## 8. Verify

- [ ] 8.1 `uv run pytest` and `uv run ruff check`.
- [ ] 8.2 `wikiskill build --collection data-science-harness --harness opencode --out /tmp/dsh-build`:
  no collision, the mapping is printed, and `agents/datalad-doer.md` allows bash.
- [ ] 8.3 `git -C ~/Projects/claude/data-science-harness status --porcelain` is identical before and
  after 8.2, 2.5, 4.1 and 6.1.
- [ ] 8.4 `wikiskill compare` on the v1 and v2 runs produces `compare.md` with intervals and tool
  choice.
- [ ] 8.5 `openspec validate add-minimal-loop --strict --no-interactive`.
