# task-suite Specification

## Purpose

Defines the declarative task-suite format for explicit evaluation: each task's prompt, expected route,
verifiers, rubric, split, fixtures, and required capabilities, held as data rather than code.

## Requirements

### Requirement: Tasks are declarative fixtures

A task suite MUST be a data file validated against the task-suite schema. Each task MUST declare an id
unique within the suite, a prompt, a split, and at least one expected outcome: an expected route, a
verifier, or a rubric.

#### Scenario: Adding a task

- **WHEN** a contributor adds a new entry to a suite file
- **THEN** `wikiskill suite check` validates it with no change to shared code

#### Scenario: Task with no expected outcome

- **WHEN** a task declares a prompt but no route, verifier, or rubric
- **THEN** `wikiskill suite check` rejects the suite and names the task

### Requirement: Prompts do not name what they test

A task prompt MUST NOT name its expected route's qualified identifier, so that routing is tested
rather than instructed. Where a prompt contains only one half of that identifier — the plugin, or
the component name — `wikiskill suite check` MUST report it for a reader to judge, and MUST NOT
refuse the suite: a component is often named after the subject it acts on, and a plugin is often an
ordinary word.

#### Scenario: Prompt names the route

- **WHEN** a routing task's prompt contains the string `disseminate/dataset-release` and that skill
  is its expected route
- **THEN** `wikiskill suite check` reports the leak and exits non-zero

#### Scenario: Prompt uses a word the route is named after

- **WHEN** a task's prompt says "this project", and its expected route is `project/status-report`
- **THEN** `wikiskill suite check` reports it as something to look at and exits zero

### Requirement: Existing fixture suites are read in place

wikiskill MUST read a collection's existing evaluation fixtures through an adapter, without copying or
modifying them. It MUST provide an adapter for data-science-harness `bench/` tasks and rubrics.

A fixture format MUST be recognised from the file itself rather than from a prefix the caller
types, and anything wikiskill requires that the fixture does not declare MUST be supplied by
wikiskill rather than requested as a new field.

#### Scenario: data-science-harness routing suite

- **WHEN** `wikiskill eval --suite <dsh>/bench/tasks/routing-lifecycle.yaml` runs
- **THEN** the file is recognised as a data-science-harness fixture, each task's `expected_skill` and
  `expected_delegates_to` become its expected route, and the data-science-harness repository is
  unchanged

#### Scenario: Fixture declares no split

- **WHEN** a data-science-harness fixture is read and it declares no train/validation/test split
- **THEN** wikiskill places its tasks in a split of its own choosing rather than failing or asking
  the fixture to add one
