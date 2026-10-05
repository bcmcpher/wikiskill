## Context

WikiSkill's Proposer is a ReAct agent that starts from the wiki index and the skill-impact history. It
must read at least four raw traces and submits one atomic proposal: create a skill, patch one, or do
nothing. The harness scores the result on validation and keeps it only if the score strictly beats the
best so far; otherwise skills roll back and the wiki stays. One unofficial implementation only asks
for the four-trace minimum in prompt text; the other enforces it through its tool server. We enforce
it.

Two things differ for wikiskill. Collections are real repositories users own, so nothing is applied
silently. Components serve many models: a patch that helps the model that failed may hurt another. So
evidence and replay must be cross-model. The study of personalised skills (arXiv 2608.10319) found
generic pooled skills beat per-user ones under limited data, which argues for general edits by
default.

`add-minimal-loop` (step 3) has since built the first half of this: `wikiskill refine` asks the
proposer role for exact find-and-replace edits, writes `wiki/proposals/p-NNN/` with `patch.diff`,
`preview.md` and `meta.json` (`status: proposed`), and never applies anything. `wikiskill compare`
compares two runs with Wilson intervals, and `--record accept|reject --proposal <id>` appends the
decision to `skill-impact.md`. `add-experience-wiki` (step 7) added signal-led digests with
evidence labels (`E1`, `S1`) and persisted samples for a reply written in the harness. This change
extends those modules rather than adding `propose.py` and `gate.py` beside them.

## Goals / Non-Goals

**Goals:**
- One reviewable, evidence-grounded change per proposal.
- Machine-enforced proposer discipline, not prompt-only.
- A gate decision the user makes with replay evidence in front of them.

**Non-Goals:**
- **Automatic acceptance** — never in this change.
- **`create` proposals** — a new component has no evaluations and no patterns of its own, so nothing
  here could ground or replay it. Deferred.
- **Multi-component proposals** — graph-aware joint proposals are left open (`add-collection-graph` only widens
  replay).
- **Description-only trigger tuning** — needs routing metrics from `add-explicit-eval` and conflict edges from
  `add-collection-graph`.
- **Converting live sessions into replayable tasks** — a live session's workspace and conversation
  state are not recorded, so its evidence is listed as non-replayable instead.

## Decisions

**Rebase onto step 3 (task 0a.1).**
- The reply keeps step 3's exact `find`/`replace` edits rather than the original anchor operations
  (`append|replace|insert_after`). A small model copies a sentence far more reliably than it places
  an anchor, and a `find` that must occur exactly once already is an anchor-uniqueness check.
- Gate states extend `meta.json`'s `status`.
- Replay is `compare` plus a per-task breakdown, not a second statistics implementation.
- The commands that act on an existing proposal are a new `wikiskill proposal` group
  (`list|show|apply|replay|decide`). They are not `refine` subcommands, because `refine` already
  takes the component as its first positional argument.

**Contract.** `{action: patch|no_action, component, reason, patterns: [...], evidence: [...],
models?: [...], edits?: [{find, replace}]}`.
- `component` must name the target. A reply naming another component, or any second one, is
  rejected as non-atomic.
- Every `find` must occur exactly once in the component's text. Edits can only touch that one file,
  by construction.
- `evidence` lists the evidence labels the proposal rests on (see below).
- `models` marks model-specific guidance (see pooled first).

**Evidence is shown, not fetched.** The proposer prompt carries digests of the evidence its target's
active patterns cite: eval units and live sessions, labelled `E1…`, `S1…` as in review. The digests
are rendered by the same code as review's, within the role's budget. The prompt also carries the
component's earlier `skill-impact.md` entries, rejected proposals in full.
- A patch must cite at least `MIN_EVIDENCE = 4` labels, lowered to the number shown when fewer
  exist.
- A label that was not shown is rejected by name.

This replaces the original design's internal `_wikiskill` collection and `wikiskill propose
check`, which counted digest reads in the proposer's logged session. The paper's concern is a
proposer that never looks at traces. A model cannot skip text in its own prompt. A tool-read count
would verify a weaker property, through a second logging path, and only in the harness. The harness
path (`/wikiskill-refine`) persists the same prompt with `refine --prepare`, as `wikiskill sample`
does for review. The reply is then checked against exactly what was persisted.

**Leakage ban.** The text a patch adds is checked against every suite that evaluated the component,
read from its runs' `suite_path`. The check also covers the component's logged notes. A patch is
rejected if its added text contains:
- a task id, as a whole word. Ids without a `-`, `_` or digit are skipped, because they are
  ordinary words.
- a verifier pattern's literal run of at least eight characters
- an eight-word normalised run shared with a rubric anchor, or with a note longer than 200
  characters

The message names the match. `refine --allow-overlap` overrides the check and is recorded in
`meta.json`.

**Pooled first.** Model-specific guidance needs `models` in the reply, and the proposal is rejected
unless both of these hold:
- every cited pattern is scoped to models within that list
- the cited patterns carry at least `MIN_SCOPED_EVIDENCE = 3` evidence items from those models

Added text that names a model the patterns were seen on, without `models`, is rejected.

**Delivery.** `wiki/proposals/<id>/` holds:
- `proposal.json`: the validated reply
- `patch.diff`
- `rendered/<file>`: the whole new file
- `preview.md`: the summary
- `meta.json`: the original `source_hash`, and `candidate_hash`, the hash of the rendered file

`wikiskill proposal apply <id>` prints how to apply the diff and writes nothing. With `--branch`, it
does the following in the source repository:
- refuses if the worktree is dirty or the file has moved on from `source_hash`
- creates `wikiskill/<component>/<id>` from `HEAD`
- applies and commits the patch there
- switches back to the branch the user was on

**Gate.**
- **States:** `proposed → replayed → accepted | rejected | withdrawn`. A proposal can be decided
  from `proposed` without replay, and then its impact entry says replay was not run.
- **Candidate runs without touching the source:** `wikiskill eval --proposal <id>`:
  - copies each source holding the component into the run directory, without `.git`
  - swaps in the rendered file
  - evaluates against that copy
  - records `proposal` in `run.json`

  A baseline is an ordinary run at the proposal's `source_hash`.
- **Replay:** `wikiskill proposal replay <id> <baseline-run> <candidate-run>`. It checks that the
  baseline ran at `source_hash` and the candidate ran at `candidate_hash`, or recorded the proposal.
  Then it runs `compare` and adds a per-task, per-model breakdown:
  - *motivating cases*: the suite tasks the cited patterns' eval evidence came from
  - *regression bank*: every other task in the suite
  - *non-replayable cases*: live-session evidence, and eval evidence from tasks not in this suite,
    each with its reason

  This gives every model in the runs individually. It writes `replay.md` and `replay.json` and sets
  `replayed`.
- **Report:** per model, the motivating cases' pass rates before and after. Every task whose pass
  rate fell is listed individually, never only an average.
- **Recommendation:** "accept" only if motivating cases improve on at least one model and no task on
  any model fell by more than the tolerance. The default tolerance is 1/3, one repeat in three. It is
  a recommendation; the user decides.
- **Decision:** `wikiskill proposal decide <id> accept|reject|withdraw --note <text>` is the only
  way to reach a final state. `compare --record` now replays and decides in one step through the
  same functions.
- **Record:** every decision appends to `skill-impact.md`:
  - the decision and the reviewer note
  - the diff and the evidence references
  - the replay summary, or "replay not run"

  A rejected or withdrawn proposal also keeps its full `proposal.json` there, so later proposer
  runs read it.

## Risks / Trade-offs

- [Overfitting to one user or one model] → pooled-first rule; replay reports every model in the runs.
- [Live sessions rarely replayable] → explicit non-replayable marking; eval suites become the main
  regression bank.
- [Weak proposer produces noise] → `no_action` is a valid, common outcome; contract validation with
  bounded retries as in `add-experience-wiki`.
- [Human review becomes a bottleneck] → `wikiskill proposal list` shows pending proposals with their
  state and recommendation.
- [Leakage check false positives on short common phrases] → eight-word and eight-character
  thresholds; the message names the match so the user can override with `--allow-overlap`.
- [Shown-not-fetched evidence costs prompt space] → digests are clipped and fitted to the proposer
  role's budget, as review's are; what does not fit is counted and not citable.

## Open Questions

- Should neutral proposals that simplify a skill without changing scores be recommendable? The paper's
  strict gate rejects them, which it lists as a limitation.
- What regression tolerance is sensible for k=3 repeats on small suites? 1/3 is the starting point.
