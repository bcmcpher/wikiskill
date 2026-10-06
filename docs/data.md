# What wikiskill saves, and where

This page covers everything wikiskill writes when one of your skills, agents or commands is used or
evaluated: what is recorded, how each file is structured, and where it lives on disk. For the
recording rules in brief, see the README's
[What it records, and what it will not](../README.md#what-it-records-and-what-it-will-not).

## Where things live

wikiskill follows the XDG base directories. `<collection>` is the `name` in your collection manifest.

| Root | Default | Holds |
|---|---|---|
| Config | `~/.config/wikiskill/` (`$XDG_CONFIG_HOME`) | `collections/<collection>.toml` manifests; `runtime.json`, the loggers' generated view of every manifest |
| Data | `~/.local/share/wikiskill/<collection>/` (`$XDG_DATA_HOME`) | the collection's recorded data, below |
| State | `~/.local/state/wikiskill/` (`$XDG_STATE_HOME`) | install records, and the Claude Code hooks' per-session state |
| Cache | `~/.cache/wikiskill/` (`$XDG_CACHE_HOME`) | OpenCode's packages and model catalogue, reused by eval runs. Safe to delete |

Inside a collection's data directory:

```
~/.local/share/wikiskill/<collection>/
├── raw/        session logs: what happened when a watched component ran (live and eval)
├── evals/      evaluation runs, comparisons and leaderboards
├── wiki/       distilled patterns, proposals and decisions (a git repository)
├── sources/    the text of each component version a run or a proposal used, by hash
└── samples/    review and refine prompts saved for answering inside a harness
```

Nothing is written into a collection's source repository, with one opt-in exception:
`wikiskill proposal apply --branch`, which commits a proposal onto a new branch
`wikiskill/<component>/<id>` and returns you to your branch.

## Session logs: `raw/`

### When anything is written

- Logging is opt-in, per component. A session writes nothing until it activates a **watched**
  component: the model calls it as a skill, delegates to it as an agent, runs it as a command, or
  reads its source file. The turns before that moment, up to `[logging] buffer_size` events (default
  200), are held in memory and written with their original timestamps when the activation happens.
  A session that never activates a watched component leaves no trace.
- With no `runtime.json` (see `wikiskill collection check --sync`), nothing is logged.
- OpenCode records through its in-process plugin. Claude Code records through hooks that call
  `wikiskill hook <Event>`. Both write the same format.
- Logging is fail-open. A logging error never interrupts a session; it is appended to
  `raw/_logger-errors.log` when that file is writable.

### Layout

```
raw/
├── 2026-10-06/
│   └── <root_session_id>.jsonl    one file per root session
├── _logger-errors.log             "<ISO time> <where>: <message>" lines
└── .sessions/                     the sessions active per project directory, for `wikiskill note`
```

- **One file per root session.** A subagent's or delegated session's events go into its root
  session's file, so a delegation chain reads as one trajectory.
- **Day directories** come from each event's own timestamp, so a session that runs past midnight
  continues in the next day's directory.
- Characters outside `A–Z a–z 0–9 . _ -` in a session id become `_` in the file name.
- Evaluation runs write their events here too, marked `"origin": "eval"` (see below), not under
  `evals/`.

### Event format

Each line is one JSON object, following
[`schemas/raw-event.schema.json`](../schemas/raw-event.schema.json) (schema 1.1). Files are only
ever appended to. Every event carries:

| Field | Meaning |
|---|---|
| `schema_version` | major version, currently `1`. Readers refuse an unknown major |
| `event_id`, `ts` | a ULID, and an RFC 3339 UTC time in milliseconds |
| `origin` | `live` (your own session) or `eval` (an evaluation run) |
| `eval` | only when `origin` is `eval`: `run_id`, `suite`, `task_id`, `condition` (`off`, `routed` or `injected`), `repeat` |
| `harness`, `harness_version` | `opencode` or `claude-code`, and its version |
| `provider`, `model` | as the harness reported them (`unknown` when it did not) |
| `collection`, `session_id`, `root_session_id`, `parent_session_id` | which collection, and where the session sits in a delegation chain |
| `component` | `{kind, name, source_hash}` of the component the event belongs to, or `null` |
| `type`, `payload` | what happened (below) |
| `redactions` | `[{kind, count, field}]` when anything in the event was masked |
| `confidence` | on correction signals only: how sure the logger is that this is a correction |

`source_hash` is `sha256:` followed by the hex digest of the component's main file (for a skill, its
`SKILL.md`) at that moment. It is how wikiskill tells versions apart; there are no version numbers.

Event types:

| `type` | Key payload fields |
|---|---|
| `session_start` | `cwd`, `title`, `agent` |
| `component_activated` | `trigger` (`skill_tool`, `task_tool`, `command`, `read`), `source_path`, `input_summary` (≤500 characters) |
| `delegation` | `subagent_type`, `child_session_id`, `description` |
| `tool_call` | `tool`, `call_id`, `ok`, `input`, `output`, `output_length` (before truncation), `output_truncated`, `error`, `duration_ms`, `produced_files` (`[{path, hash}]`, up to 50) |
| `assistant_turn` | `text`, `text_length`, `finish_reason` (`truncated_by_logger` when cut) |
| `step_usage` | `tokens` (`input`, `output`, `reasoning`, `cache_read`, `cache_write`), `cost` |
| `error` | `message`, `where`, `fatal` |
| `session_end` | `reason`, `duration_ms` |
| `user_turn` | correction signal: what you typed shortly after a component ran: `text`, `turns_since_activation`, `seconds_since_component` |
| `repeat_activation` | correction signal: the same component activated again soon after |
| `note` | correction signal: an explicit `wikiskill note`, `attributed_by` `named`, `last_activated` or `none` |
| `output_edit` | correction signal: a file the component produced was later edited: `path`, `before_hash`, `after_hash`, `diff` (≤8 KB) |

An example line, wrapped here for reading:

```json
{"schema_version": 1, "event_id": "01K6Y3Q4ZB8N0T5W2R7C9D1E3F", "ts": "2026-10-06T14:02:11.482Z",
 "origin": "live", "harness": "claude-code", "harness_version": "2.1.289",
 "provider": "anthropic", "model": "claude-sonnet-4-5", "collection": "my-skills",
 "session_id": "5f1c…", "root_session_id": "5f1c…", "parent_session_id": null,
 "component": {"kind": "skill", "name": "govern/preregister", "source_hash": "sha256:9b1e…"},
 "type": "component_activated",
 "payload": {"trigger": "skill_tool", "source_path": "/home/u/skills/govern/skills/preregister/SKILL.md",
             "input_summary": null}}
```

### Redaction, truncation, and what is never recorded

- **Redaction** (`[logging] redact`, on by default) covers every event in `raw/`: live sessions,
  evaluation runs and notes. It replaces environment values and secret-shaped strings with
  `[REDACTED:<kind>]` in every free-text field (assistant text, your turns, note text, tool input,
  output and error, delegation descriptions, activation input summaries, error messages), before
  anything is cut to size, so a truncated field never holds the first half of a secret. The kinds are `env_value`, `api_key`, `token`, `private_key`,
  `password` and `url_credentials`. Environment values shorter than 8 characters and allow-listed
  variables (`PATH`, `HOME`, `XDG_*` and the like) are kept. Tool inputs are redacted to a nesting
  depth of 8; anything deeper becomes `[TRUNCATED:depth]`. The environment checked is the
  process's own: the hook's or plugin's for a live session, `wikiskill note`'s for a note, and for
  an evaluation unit the environment its harness ran in, including the suite's `env`. With
  `redact = false` nothing is redacted, live or eval.
- **Truncation**: tool output and assistant text longer than `[logging] output_limit_bytes` (default
  16 KB) are cut, and the original length is kept.
- **Never recorded:**
  - sessions that never touch a watched component;
  - the model's reasoning or thinking text (only its token count);
  - your messages outside a component's follow-up window (`[logging] follow_up_turns`, default 3), and
    all subagent prompts and command expansions.
- Logging makes no model or network calls.
- There is no automatic clean-up yet. `[logging] retention_days` is accepted but nothing prunes logs.
  Delete old day directories by hand if you need to.

## Evaluation runs: `evals/`

`wikiskill eval` writes one directory per run, named by a ULID run id:

```
evals/<run_id>/
├── run.json           the run's manifest, written when the run ends
├── results.jsonl      one line per unit, appended as each finishes
├── report.md          the human-readable report
├── report.json        the same, as data
├── units/<task>__<model>__<condition>__r<N>/   each unit's own sandbox and transcripts
├── preflight/<model>/  the endpoint check before tasks run (OpenCode)
└── candidate-source/  only for `eval --proposal`: a copy of the source with the proposal applied
```

**`run.json`** records what was run, so a result can be repeated and pooled:
- `run_id`, `suite`, `suite_path`, `suite_hash`, `collection`, `harness`, `harness_version`,
  `wikiskill_version`, `models`, `conditions`, `tasks`, `env`, `setup`;
- `components`: `[{kind, name, source_hash}]`, the exact version of each component under test;
- `proposal`: `null`, or the proposal id for a candidate run;
- `preflight`, `isolation` (proof of what each condition ran under), `options` (output cap, thinking,
  seed cache), `workers`, `duration_s`, `outcomes` (a count per outcome), `events_written`.

It never contains an API key.

**`results.jsonl`** has one object per unit (task × model × condition × repeat):
- `run_id`, `suite`, `task_id`, `model`, `condition`, `repeat`;
- `outcome`, one of:
  - `completed`, `tool_call_as_text`, `step_exhausted`, `permission_blocked` or `api_error`;
  - `infra_error`, which a timeout is: `reason` says "timed out after Ns";
  - `skipped`;
- `reason`, `error`, `duration_ms`, `exit_code`, `tokens`, `session_id`, `activations`;
- `verifiers` and `passed` (`null` when a task has no verifiers), `rubric`, `expected`.

`infra_error` and `skipped` units are reported but left out of pass rates.

`run.json` and `results.jsonl` are the files to share when pooling results with others (see the
quickstart's [Pool your run](quickstart.md#7-pool-your-run-with-everyone-elses)).

**Unit directories** hold each unit's isolated harness setup and its full transcripts:
- OpenCode: its own `config/`, `data/`, `state/` and `cache/`, `exports/`, `run.ndjson`;
- Claude Code: `claude/settings.json`, `stream.jsonl`;
- both: the `work/` directory the task ran in, which is a git repository.

These are **kept indefinitely** and can grow large. They are **not redacted**: they are the
harness's own records of a sandboxed run.

Other outputs under `evals/`:

| Path | Written by |
|---|---|
| `evals/compare/<runA>_vs_<runB>/compare.{md,json}` | `wikiskill compare` |
| `evals/leaderboard/<suite>-<id>/leaderboard.{md,json}` | `wikiskill leaderboard` |
| `evals/diff/<component>/<a7>_vs_<b7>/diff.{md,json}`, `text.diff` | `wikiskill diff` ("/" and ":" in names become "-"; `text.diff` only when both texts were found) |
| `evals/versions/<component>/<suite>-<id>-<condition>-base-<b7>[-critical-<c7>]/board.{md,json}` | `wikiskill leaderboard --by-version` ("/" and ":" in names become "-"; the JSON keeps every unit behind each figure, with its run id) |

## Source snapshots: `sources/`

A version of a component is the `source_hash` of its main file. So that `wikiskill diff` can show a
version after the file has moved on, every eval run stores the text of each watched component it
records a hash for, and refine stores a proposal's base and candidate text. Each is one file,
`sources/sha256-<hex>`, written once and never changed; two runs of one version share it. A
snapshot that cannot be written is a warning in `run.json`'s `warnings` or in refine's output, and
never fails the run or the proposal.

Snapshots hold your skill text as it is in your repository: **not redacted**. The directory can be
deleted at any time; `wikiskill diff` then falls back to proposals' rendered copies, candidate runs'
copied sources, and the source repository's git history, which it reads without checking anything
out.

## The wiki: `wiki/`

The wiki is what wikiskill learns from the logs and runs. It is a git repository: every change is
committed, so its history is the audit trail.

```
wiki/
├── index.md              table of active patterns
├── log.md                one entry per review, failed ones included
├── skill-impact.md       one entry per proposal decision
├── patterns/<slug>.md    one page per failure or success pattern
├── components/<name>.md  per component: its patterns and history ("/" in names becomes "-")
├── proposals/<p-NNN>/    refinement proposals (below)
├── graph.json            the collection graph (`wikiskill graph build`)
└── .watermark.json       which evidence each component's reviews have already seen
```

A **pattern page** has YAML frontmatter followed by `## Observation`, an optional `## Suggestion`,
and `## Updates`. The frontmatter fields:
- `slug`, `title`, `component`, `cause`, `trigger`, `status` (`active` or `superseded`), `evidence`;
- `models`, `harnesses`, `source_hashes` and `universal`: the pattern's scope;
- `created`, `updated`, `maintainer`.

Scope is computed from the cited evidence, not from the maintainer model's claims. Each evidence
reference points back to a run unit (`run_id`, `task_id`, `condition`, `repeat`, `model`) or to a live
`session_id`.

A **proposal**, `proposals/p-NNN/`, holds:
- `patch.diff`: the edit, for you to apply;
- `rendered/<file>`: the edited file in full;
- `proposal.json`: the proposer's raw reply;
- `preview.md`;
- `meta.json`.

`meta.json` has `component`, `source_path`, `repository`, `source_hash` (the version it was made
from), `candidate_hash` (the version it would produce), `description_changed`, `patterns`,
`evidence`, `models`, `reason` and `status`. `status` moves from `proposed` to `replayed`, then to
`accepted`, `rejected` or `withdrawn`. A replay adds `replay.json` and `replay.md`, and a decision
adds `meta.decision` and an entry in `skill-impact.md`.

## Saved prompts: `samples/`

`wikiskill sample`, and `wikiskill refine` when it saves a prompt for you to answer in a harness,
write `samples/<ULID>/` with the following files:
- `prompt.md`;
- `instructions.md`;
- `evidence.json`;
- `sample.json`: the component, the runs and evidence shown, and the patterns seen.

A saved sample is refused as stale once the component's patterns have changed.

## State and cache

- **Install records:** `~/.local/state/wikiskill/installed/<harness>-<scope>-<target>.json`. Each
  lists the files `wikiskill install` wrote, with their hashes, so they can be checked or removed.
- **Claude Code hook state:**
  - `~/.local/state/wikiskill/claude-code/sessions/<session>.json` holds per-session buffers between
    hook calls, and is pruned after 7 days;
  - `claude-code/errors.log` gets hook errors when no collection log is writable.
- **Cache:** `~/.cache/wikiskill/opencode-seed/<opencode-version>/` lets each eval unit start without
  downloading OpenCode's packages again.

## Things to be aware of

- **Unit transcripts under `evals/` are not redacted.** Their events in `raw/` are, but the
  harness's own records (`exports/`, `stream.jsonl`, `run.ndjson`) are kept as written. An eval
  runs in a sandbox with its own config, but a secret that a task's fixtures or setup put into the
  workdir can appear there.
- **Logs written before eval and note redaction existed are not rewritten.** Eval events and notes
  from those versions may hold secrets in the clear; delete the old `raw/` day directories if that
  matters.
- Raw logs, unit directories, source snapshots and the wiki are never cleaned up automatically.
- `docs/design/architecture.md` §6 predates some of this; where the two disagree, this page and the
  schema are current.
