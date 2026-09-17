## ADDED Requirements

### Requirement: A build only clears output it owns

`wikiskill build` MUST clear its output directory before writing, and MUST refuse, with an error
naming the directory, when the target holds files that no previous build produced. A refused build
MUST leave the target untouched.

#### Scenario: Output directory points at a harness config directory

- **WHEN** `wikiskill build --out` names a directory holding the user's own OpenCode configuration
- **THEN** the build fails with an error naming that directory, and nothing in it is deleted

#### Scenario: Rebuilding into a previous build's output

- **WHEN** `wikiskill build` runs twice into the same directory and a component was removed from the
  source tree between runs
- **THEN** the second build succeeds and the removed component is gone from the output

#### Scenario: Building into an empty directory

- **WHEN** the output directory exists and is empty
- **THEN** the build proceeds
