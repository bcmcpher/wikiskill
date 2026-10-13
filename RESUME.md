# Resume note — 2026-10-12

## Done

- `docs/evaluate-and-refine-a-skill.md`: the end-to-end guide, reviewed twice, merged and pushed.
- Four OpenSpec proposals on `main`, none applied:
  - `warn-unsent-followups`
  - `add-scripted-followups` (apply after `warn-unsent-followups` is archived)
  - `enforce-task-splits`
  - `honour-empty-task-overrides`

No proposal changes a suite hash. None of the DSH pilot suites uses `followups` or an empty
`setup`, `requires` or `guard`. Merging `main` into `results/dsh-pilot` therefore cannot change
how the sweep's runs pool, and no file is changed on both branches.

## Next: on the batch machine

Do not merge `main` into the sweep's checkout while the sweep runs. Each eval is a new
`uv run wikiskill` process, so later evals would run the new code.

1. Let `pilots/dsh-sweep/v2.sh 1a` and `1b` finish. Logs are in
   `${XDG_STATE_HOME:-~/.local/state}/wikiskill/dsh-sweep/`.
2. Check `$SWEEP_LOGS/unrecorded/`. If it holds a run, run `sweep.sh` once more: it adds the run
   at start and reruns nothing.
3. For each study (`docs/pilots/dsh`, `docs/pilots/dsh-bids`, `docs/pilots/dsh-curate`):

   ```bash
   uv run wikiskill findings bundle docs/pilots/<study>
   uv run wikiskill findings tables docs/pilots/<study>
   bin/figures docs/pilots/<study>
   uv run wikiskill findings tables docs/pilots/<study> --check
   ```

4. Commit on `results/dsh-pilot` and push it.

## Next: here

1. Fetch the results and merge `main` into them:

   ```bash
   git fetch origin
   git switch results/dsh-pilot    # first time: git switch -c results/dsh-pilot origin/results/dsh-pilot
   git pull --ff-only
   git merge --no-ff main
   uv run wikiskill findings tables docs/pilots/<study> --check   # for each study
   git push origin results/dsh-pilot
   git switch main
   ```

2. The bundles hold `run.json` and `results.jsonl` only. To read transcripts here, copy the run
   directories from `~/.local/share/wikiskill/<collection>/evals/<run-id>/` on the batch machine.

## Open decisions

- **`enforce-task-splits` conflicts with the maintainer arm.** Every DSH pilot task is
  `split: val`, so a review that reads only `train` sees no eval units, and `pilots/dsh-maint`
  gets empty digests. Either move some DSH tasks to `train` (a new suite file, so a new hash), or
  give review a way to read another split. Hold the change until this is decided.
- **`add-scripted-followups`** moves the OpenCode step counter into a file. Apply it after the
  study's runs are closed.
- **`honour-empty-task-overrides`**: may runs of a suite with an empty override, made before and
  after the change, pool? Recommended: yes, as no known suite has one.
- `warn-unsent-followups` and `honour-empty-task-overrides` are safe to apply at any time.
