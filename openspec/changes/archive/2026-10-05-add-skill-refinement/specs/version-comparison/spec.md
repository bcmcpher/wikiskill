## MODIFIED Requirements

### Requirement: Runs of one suite compare across component versions

`wikiskill compare <run-a> <run-b>` MUST compare two completed runs from their stored results without
re-running anything. It MUST refuse runs whose suite or task ids differ, or whose recorded
`suite_hash` differs, and MUST warn when either run recorded no `suite_hash` or when the component
under test has the same `source_hash` in both. `--record accept|reject --proposal <id>` MUST record
the comparison as that proposal's replay and the decision through the refinement gate. The entry in
`wiki/skill-impact.md` MUST carry the decision, both run ids, both hashes, and the pooled result.
`--record` MUST NOT apply or revert any change.

#### Scenario: Before and after a patch

- **WHEN** run A used datalad-doer at hash `h1` and run B at hash `h2`, on the same suite
- **THEN** the comparison is produced and labels its columns with both hashes

#### Scenario: Different suites

- **WHEN** the two runs used different suites
- **THEN** the command exits non-zero and names both suites

#### Scenario: Same suite name, different content

- **WHEN** both runs used suite `datalad-doer` but their `suite_hash` values differ, because a
  verifier was edited between them
- **THEN** the command exits non-zero and names both hashes

#### Scenario: A run from before suite hashes

- **WHEN** one run's `run.json` has no `suite_hash`
- **THEN** the comparison is produced with a warning that the suite content is unverified

#### Scenario: Recording a decision

- **WHEN** the user runs the comparison with `--record reject --proposal p-001`
- **THEN** `skill-impact.md` gains one entry for `p-001`, the proposal's state is `rejected`, and no
  source file changes
