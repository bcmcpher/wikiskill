## ADDED Requirements

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
