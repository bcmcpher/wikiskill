## 1. Transient errors

- [x] 1.1 `Trajectory.transient` (default False), included in `as_result()` only when true
- [x] 1.2 OpenCode: set it on no session, export failure and launch `OSError`; not on timeout,
  `prepare` failure or agent mismatch
- [x] 1.3 Claude Code: no session and launch `OSError`; not on an isolation leak or failed injection
- [x] 1.4 Tests: launch failure and setup failure (OpenCode); no session and isolation leak (Claude
  Code)

## 2. Retry inside a run

- [x] 2.1 `--retries N` (default 1, `0` disables), recorded in `run.json`
- [x] 2.2 `_execute`: on a transient `infra_error`, move the unit directory to
  `<slug>.attempt-<n>`, run again, and record `attempts` and `retried`
- [x] 2.3 Only the final attempt's events are written
- [x] 2.4 Tests: crash then success; crash twice; timeout and failure not retried; `--retries 0`

## 3. `--fill`

- [x] 3.1 `RunLayout.attempt_dir`, `replace_results` (atomic, superseded lines kept)
- [x] 3.2 `fill_refusal`: no `run.json`, preflight-only, suite hash, harness and version, component
  versions, run options
- [x] 3.3 CLI: settings from `run.json`, refused beside `--fill`; `--collection` required; base URL
  defaults to the recorded one; `--suite` optional otherwise required
- [x] 3.4 `run.json` `fills`, `outcomes` and `events_written` updated; report regenerated
- [x] 3.5 Report: units retried, units filled
- [x] 3.6 Tests: fill one unit; nothing to fill; still lost after a fill; refusal on a changed suite
  and harness version; no manifest; CLI refusals

## 4. Sweep

- [x] 4.1 `sweep-fill.patch`: fill up to `MAX_FILLS` (default 2) while `state finished` fails,
  stopping on a refused fill; then the existing completeness check and `findings add`
- [x] 4.2 Header comment: what a fill does, and that it never reruns a scored unit
- [ ] 4.3 Apply the patch on `results/dsh-pilot` once the running sweeps end

## 5. Docs and verification

- [x] 5.1 `docs/data.md`: `attempts`, `retried`, `transient`, `retries`, `fills`,
  `results.superseded.jsonl`, `.attempt-<N>` directories
- [x] 5.2 `docs/writing-suites.md` "After the first run": retried and filled units
- [ ] 5.3 Fill the DSH ministral-3:3b archive run `01M4BGXVYQ93JES7NC9F1YQXTK` on the GPU once the
  sweeps end, and compare it with the full rerun
