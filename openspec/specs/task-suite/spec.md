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

A task prompt MUST NOT name its expected skill, agent, or plugin, so that routing is tested rather
than instructed.

#### Scenario: Prompt names the skill

- **WHEN** a routing task's prompt contains the string `dataset-release` and that skill is its
  expected route
- **THEN** `wikiskill suite check` reports the leak and exits non-zero

### Requirement: Existing fixture suites are read in place

wikiskill MUST read a collection's existing evaluation fixtures through an adapter, without copying or
modifying them. It MUST provide an adapter for data-science-harness `bench/` tasks and rubrics.

#### Scenario: data-science-harness routing suite

- **WHEN** `wikiskill eval --suite dsh:bench/tasks/routing-lifecycle.yaml` runs
- **THEN** each task's `expected_skill` and `expected_delegates_to` become its expected route, and the
  data-science-harness repository is unchanged
