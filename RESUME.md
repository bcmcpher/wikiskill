# Resume note — 2026-10-22: skills-comm pilot features

Generic features to run the `../skills-comm` benchmark through wikiskill. No skills-comm
importer or integration code until their output plans settle.

## State

Proposals are on `proposals/skills-comm-pilot`. Each change is implemented on its own branch
and worktree under `.claude/worktrees/`. Nothing is archived or merged.

| Change | Branch head | State |
|---|---|---|
| `support-flat-plugin-layout` | `f4baf1f` | Two review rounds, all fixed. Ready to archive. |
| `add-verifier-secrets` | `f6a997c` | Two review rounds fixed. The last fix (+808/−120) is not reviewed. |
| `add-scored-verifier` | `f9e8904` | Follow-up fixes written but not committed (see below). |

`refs/review/change/<name>` marks the last reviewed commit of each branch.

## Next

1. **Commit the scored-verifier fixes.** Worktree `agent-a8b56ecce85ab28b8` has the fixes in
   `interval.py`, `score/verify.py` and three test files. A shared-stash collision also left four
   files conflicted there (`build.py`, `cli/collection.py`, `test_build.py`, `test_cli.py`).
   The scored branch does not change those files, so restore them:

   ```bash
   git -C .claude/worktrees/agent-a8b56ecce85ab28b8 checkout HEAD -- \
     src/wikiskill/build.py src/wikiskill/cli/collection.py tests/test_build.py tests/test_cli.py
   ```

   Then run `bin/check` and commit
   `verify: fix the follow-up review findings on structured results`. A backup of the fixes is in
   `.claude/scored-fix-wip.patch` (untracked). Then drop `stash@{0}`; it holds only a copy of
   the same fixes.
2. **Review the secrets fix.** Run `/code-review` on
   `refs/review/change/add-verifier-secrets..change/add-verifier-secrets`. It adds a pass that
   overwrites secret values in every file of a unit directory except `work/`.
3. **Close out** each change on its branch: `openspec archive <name> --yes`, commit, then merge
   with `--no-ff` into `proposals/skills-comm-pilot`, in this order: flat layout, secrets,
   scored. Secrets and scored conflict in `verify.py`, `suite.py`, the suite schema, both docs
   and tests; resolve on the scored branch. Ask before merging into `main`.
4. Remove the worktrees and branches after the merge.
5. After merging into `main`: rerun `findings tables` for the three `docs/pilots/*` studies
   (new score columns), and check secrets live on the batch machine on both harnesses.

## Open decisions

- **`evals/` in a plugin-root skill.** It is copied into the skill, not excluded. Claude Code uses
  `evals/` at plugin level, but skill-creator puts it inside a skill. Recommended: keep it.
- **Scrub cost.** For suites with secrets, the scrub reads every file of each unit, including the
  OpenCode seed `node_modules`. Skipping `node_modules` is a cheap follow-up.
- **Out of scope, found in review.** An ordinary skill still copies a nested `x/SKILL.md` into
  its build. `collection check` does not catch a bare-name clash across plugins, which the build
  rejects. Both predate these changes.

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
