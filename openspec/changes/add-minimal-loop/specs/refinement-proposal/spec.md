## Purpose

Defines the minimal refinement proposal: one user-triggered, user-applied patch per invocation,
grounded in the wiki and tied to the component version it was made from. Replay and gate states are
added later by `add-skill-refinement`.

## ADDED Requirements

### Requirement: Refinement produces one user-applied patch

`/wikiskill-refine <component>` and `wikiskill refine <component>` MUST run only when the user invokes
them, and MUST produce exactly one `patch` or `no_action` result for that one component. A patch MUST
be written under `wiki/proposals/<id>/`:
- `patch.diff`
- `preview.md`
- `meta.json`, recording the target component, its current `source_hash`, the patterns cited, and the
  proposer model

wikiskill MUST NOT apply the patch or write to the source repository. A proposal citing no wiki
pattern MUST be rejected before it is written.

#### Scenario: Patch for the doer

- **WHEN** the user runs `/wikiskill-refine datalad/datalad-doer` with two patterns in the wiki
- **THEN** one proposal directory is written, `meta.json` cites at least one pattern, and the
  data-science-harness repository's `git status` is unchanged

#### Scenario: Nothing to fix

- **WHEN** the wiki holds no pattern for the component
- **THEN** the result is `no_action` with a reason, and no proposal directory is written
