---
description: >
  Start an explicit evaluation of a collection in the background and report its run id.
  Takes a suite file, and optionally a collection, models, and conditions.
---

Start `wikiskill eval` for the suite named in `$ARGUMENTS` and return its run id. **Never run the
suite in this session.** An evaluation opens fresh isolated harness sessions of its own; running it
here would put this conversation's context, skills and MCP servers into the thing being measured,
which is the one thing the runner exists to prevent.

1. Resolve the arguments. The first is the suite file. `--collection`, `--models`, `--condition` and
   `--workers` pass straight through. With no collection given, pick the one whose manifest names
   the suite's components, or ask — ROUTED and INJECTED both need one.
2. Check the suite first: `wikiskill suite check <suite>`. A suite that does not load is a one-line
   answer, not a background job.
3. Cost the run before starting it: `wikiskill eval --suite <suite> --models ... --preflight-only`.
   On a harness-served model the probe itself spends tokens, so run it once and report what it says.
   A model that fails preflight is reported with its reason and not run.
4. Start the real run in the background, with its output going to a file:

   ```
   wikiskill eval --suite <suite> --collection <name> [--models ...] [--condition off,routed] \
     > <run-log> 2>&1 &
   ```

5. Report the run id, the directory under `<collection>/evals/<run-id>/`, and how to read it later:
   `report.md` for the summary, `results.jsonl` for one line per unit. Then stop. Do not poll it.

If the user asks how a run went, read its `report.md` rather than re-running anything. Say plainly
what the report says was skipped or ended in `infra_error`, and what each row's `pass basis` was —
a verifier pass rate and a routing one are not the same measurement.
