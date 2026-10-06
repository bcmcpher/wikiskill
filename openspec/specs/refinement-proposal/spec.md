# refinement-proposal Specification

## Purpose
Defines the refinement proposal: one user-triggered patch to one component per invocation, grounded
in the wiki's patterns and the evidence shown behind them, held to machine checks for atomicity,
evaluation leakage and model-specific guidance, tied to the component version it was made from,
and never applied by wikiskill. The gate it passes is `refinement-gate`.

## Requirements

### Requirement: Refinement produces one user-applied patch

`/wikiskill-refine <component>` and `wikiskill refine <component>` MUST run only when the user invokes
them, and MUST produce exactly one `patch` or `no_action` result for that one component. A patch MUST
be written under `wiki/proposals/<id>/`:
- `proposal.json`, the validated reply
- `patch.diff`
- `rendered/`, holding the whole new file
- `preview.md`
- `meta.json`, recording:
  - the target component
  - its current `source_hash`, and the hash of the rendered file
  - the patterns and evidence cited
  - the proposer model
  - the proposal's state

wikiskill MUST NOT apply the patch or write to the source repository. A proposal citing no wiki
pattern MUST be rejected before it is written.

#### Scenario: Patch for the doer

- **WHEN** the user runs `/wikiskill-refine datalad/datalad-doer` with two patterns in the wiki
- **THEN** one proposal directory is written, `meta.json` cites at least one pattern, and the
  data-science-harness repository's `git status` is unchanged

#### Scenario: Nothing to fix

- **WHEN** the wiki holds no pattern for the component
- **THEN** the result is `no_action` with a reason, and no proposal directory is written

### Requirement: Proposals target a single component

A proposal MUST name its target component, and MUST be rejected if it names any other. Its edits
MUST each match exactly one passage of that component's own text.

#### Scenario: Proposal names a second skill

- **WHEN** the proposer is asked about `analyze/checkpoint` and replies naming
  `disseminate/publish`
- **THEN** the reply is rejected as non-atomic and nothing is written

### Requirement: Proposals are grounded in evidence shown to the proposer

The proposer MUST be shown the following, in its prompt:
- digests of the evidence cited by the target's active patterns, each under a label
- the component's earlier `skill-impact.md` entries

A patch MUST cite at least four evidence labels, or every label when fewer were shown. A cited
label that was not shown MUST be rejected by name. A reply written elsewhere MUST be checked against
the prompt persisted for it.

#### Scenario: Claimed but unshown evidence

- **WHEN** a patch cites `E1`, `E2`, `E7` and `S3`, and the prompt showed `E1` to `E5` and no
  session
- **THEN** the proposal is rejected naming `E7` and `S3`

#### Scenario: Too little evidence cited

- **WHEN** six labels were shown and a patch cites two
- **THEN** the proposal is rejected with the count and the minimum of four

### Requirement: Proposals do not leak evaluation content

A proposal MUST be rejected if the text it adds contains any of these, drawn from the suites that
evaluated the component and from its logged notes:
- a task id
- a literal run from a verifier's expected pattern
- text shared with a rubric anchor
- text shared with a user note longer than 200 characters

The rejection MUST name the matched text. The user MAY override it with `--allow-overlap`, which
MUST be recorded with the proposal.

#### Scenario: Expected value copied into a skill

- **WHEN** a patch adds a sentence containing a verifier's expected output from the routing suite
- **THEN** the proposal is rejected and the matched span is reported

### Requirement: General edits are preferred over model-specific variants

A proposal MUST NOT add model-specific guidance unless it marks the models. Every pattern it
addresses MUST be scoped to those models and, together, they MUST carry at least three evidence
items from them. Added text naming a model the patterns were seen on, without that mark, MUST be
rejected.

#### Scenario: Small-model section with thin evidence

- **WHEN** a proposal adds a section for small models backed by one evidence item
- **THEN** the proposal is rejected with the evidence count and the required minimum

#### Scenario: Unmarked model name

- **WHEN** a patch adds "If you are qwen3, ask first" and its reply marks no models
- **THEN** the proposal is rejected naming `qwen3`

### Requirement: Proposals can be listed, shown, and put on a branch

`wikiskill proposal list` MUST show each proposal's id, component, state, and recommendation when
replayed. `wikiskill proposal show <id>` MUST print its preview. `wikiskill proposal apply <id>`
MUST write nothing and print how to apply the diff. With `--branch`, it MUST:
- refuse a dirty source worktree, or a file that no longer has the proposal's `source_hash`
- commit the patch on a new branch `wikiskill/<component>/<id>`
- leave the user on the branch they were on

#### Scenario: Apply without a branch

- **WHEN** the user runs `wikiskill proposal apply p-002`
- **THEN** `git -C <source> status` is unchanged

#### Scenario: Apply on a branch with local edits

- **WHEN** the source worktree has uncommitted changes and the user passes `--branch`
- **THEN** the command exits non-zero and creates no branch

### Requirement: Proposals keep the text of both versions

Writing a proposal MUST store the component's text before the edit and the rendered candidate in the
collection's source snapshot store, under the proposal's `source_hash` and `candidate_hash`, so the
two versions can be compared after the source moves on. A snapshot that already exists MUST NOT be
rewritten, and a failure to store one MUST be a warning that does not stop the proposal.

#### Scenario: New proposal

- **WHEN** refine writes proposal `p-004` for a component at hash `h3`, producing candidate `h4`
- **THEN** the snapshot store holds texts for both `h3` and `h4`, each hashing to its key

#### Scenario: No-action reply

- **WHEN** the proposer replies `no_action`
- **THEN** no snapshot is written
