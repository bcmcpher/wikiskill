# Resume note — 2026-11-10 (end of session): honour-empty-task-overrides merged

## Done

- The three skills-comm pilot changes are archived and merged into `main` through
  `proposals/skills-comm-pilot`: `support-flat-plugin-layout`, `add-verifier-secrets` and
  `add-scored-verifier`. That work is pushed (`94fd5df..2307620`).
- `honour-empty-task-overrides` is archived and merged (`a857a3e`). A task's `setup: []`,
  `requires: []` or `guard: {}` now clears the suite default. `env` and `secrets` still combine.
  Pooling across the change was accepted and is noted in the guide §3.3. Not pushed.

## The GB10 is gone

The GB10 is no longer accessible. Its `evals/` runs beyond the bundles in `docs/pilots/` are out
of reach, and no live eval can run. Build against synthetic fixtures and the bundled pilot
results, and list live verification as outstanding. Live secret checks on both harnesses cannot
run. Check whether `findings tables` for the three `docs/pilots/*` studies can be regenerated from
the committed bundles.

## Next

The order of the pending changes is in `ROADMAP.md` § Pending changes. Three changes were proposed
on 2026-11-12: `warn-empty-guard`, `unify-secret-scrub` and `collection-name-clash-check`. Their
open decisions are in each `design.md`. `add-run-archive` reuses the scrubber from
`unify-secret-scrub`. Live multi-turn runs stay unverified.

The pilot tables on `results/dsh-pilot` check as current with that branch's code. With `main`'s
code, `findings.csv` gains the seven `score_*` columns from `add-scored-verifier`. Merge `main` into
that branch and regenerate the tables.

## Open decisions and follow-ups

- **Scrub cost.** For suites with secrets, the unit scrub reads every file of each unit, including
  the seeded OpenCode `node_modules`. Skipping `node_modules` is a cheap follow-up.
- **Three scrubbers.** `redact.hide_value` (all JSON forms, dict keys), `redact.redact_value`
  (raw form, patterns; used for the rubric judge) and the pattern pass on verifier output differ
  in coverage. Unify on `hide_value` plus one pattern pass.
- **Known limits, not fixed.** Two declared secrets used as keys of one dict collapse into one
  redacted key. A secret that is a substring of `[REDACTED:env_value]` breaks the leak check.
  `Task.suite_secrets` duplicates `Suite.secrets`.
- **`evals/` in a plugin-root skill.** It is copied into the skill, not excluded. Recommended:
  keep it.
- **Found in the honour-empty-task-overrides review, not fixed.** `guard: {}` on a task drops the
  suite's deny patterns silently; a `suite check` warning would need a new change. The run manifest
  records `setup` only when non-empty and never records `requires` or `guard`.
- **Out of scope, found in review.** An ordinary skill still copies a nested `x/SKILL.md` into
  its build. `collection check` does not catch a bare-name clash across plugins, which the build
  rejects.

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
