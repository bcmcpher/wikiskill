## Purpose

Turns a study's evaluation runs into findings that can be versioned and shared. The runs are tracked
in the repo. Tables, data and figures are made from those runs alone, and versioned markdown builds
to documents and slides that import into office suites.

## ADDED Requirements

### Requirement: A study declares its runs and tables

A study MUST be a directory with a `findings.toml` that names its runs, each with a role, and
declares its tables. A table's kind MUST be one of `leaderboard`, `version-board` or `report`, and it
draws on runs by role. A manifest that names an unknown kind, a role no run has, or a run twice MUST
be refused, naming the entry.

#### Scenario: A sweep and a version board

- **WHEN** `findings.toml` names ten runs with role `sweep` and three with role `versions`, and
  declares a `leaderboard` table over `sweep` and a `version-board` table over `versions`
- **THEN** the study loads with two tables, each drawing on its own runs

#### Scenario: A table over a missing role

- **WHEN** a table draws on role `routing` and no run has that role
- **THEN** the study is refused, naming the table and the role

### Requirement: A study's runs are bundled into the repo

`wikiskill findings bundle <study>` MUST copy each named run's `run.json` and `results.jsonl` into the
study directory. It MUST NOT copy transcripts, unit directories, or anything else under a run. A run
already bundled MUST be left unchanged. A bundled run whose files differ from its source MUST be
refused, never overwritten. A named run that cannot be found MUST be reported, and the other runs
bundled.

#### Scenario: Bundling the sweep

- **WHEN** a study names twelve runs in the collection's evals, and two are bundled already
- **THEN** ten runs gain `run.json` and `results.jsonl` in the study, the two are untouched, and no
  transcript is copied

#### Scenario: A run changed after bundling

- **WHEN** a bundled run's `results.jsonl` differs from the run at its source
- **THEN** the bundle refuses that run, naming it, and leaves the bundled copy as it was

### Requirement: Tables are made from the bundle alone

`wikiskill findings tables <study>` MUST render every declared table from the bundled runs, needing
neither the collection's evals nor the network. It MUST write each table as a markdown fragment in
two forms: a full one, as the pooled output gives it, and slide-sized ones of at most six columns
and one table each.
With `--check`, it MUST write nothing and MUST fail when any written fragment differs from what the
bundle now gives.

#### Scenario: Regenerating on another machine

- **WHEN** a fresh clone runs `wikiskill findings tables docs/pilots/dsh`
- **THEN** the fragments are rewritten from the bundle, unchanged from the committed ones

#### Scenario: A stale fragment

- **WHEN** a run is added to the study and bundled, and the fragments are not regenerated
- **THEN** `findings tables --check` fails, naming the stale fragments

### Requirement: Findings are exported as long-format data

`findings tables` MUST also write one CSV per study, with one row per table, entrant and cell, where a
cell is a model, condition, version and task, the task being empty for pooled rows. Each row MUST
give:
- passes, total, rate and the Wilson interval
- outcome counts
- median seconds and median input and output tokens
- family and size, when a catalogue is given

#### Scenario: Re-plotting elsewhere

- **WHEN** a user loads the study CSV into a spreadsheet
- **THEN** every rate in the markdown tables is in it, with its interval and its run count

### Requirement: Figures come from the exported data

The figures script MUST draw its figures from the study CSV alone: pass rates with intervals per
model and condition, and lift per version and model. It MUST NOT add a plotting library to the
project's dependencies.

#### Scenario: Drawing the sweep

- **WHEN** the figures script runs on the DSH study CSV
- **THEN** it writes PNG figures into the study directory, and `pyproject.toml` is unchanged

### Requirement: Documents are versioned as markdown and built to office formats

A study's report and slides MUST be markdown files that include table fragments by reference. The
document build MUST expand the includes and produce a `.docx` from the report and a `.pptx` from the
slides. The slides MUST use native text and tables, and speaker notes where given, so they stay
editable after import. When the study supplies reference templates, the build MUST use them. The
office files MUST NOT be tracked by git. When pandoc is not on `PATH`, the build MUST fail, saying so,
and write nothing.

#### Scenario: Building the DSH documents

- **WHEN** `bin/build-docs docs/pilots/dsh` runs with pandoc installed
- **THEN** `report.docx` and `slides.pptx` are written beside their markdown, with each included
  table's current content, and `git status` does not list them

#### Scenario: No pandoc

- **WHEN** the build runs without pandoc on `PATH`
- **THEN** it exits non-zero with a message naming pandoc, and no office file is written

#### Scenario: An include that does not exist

- **WHEN** `report.md` includes a fragment the study does not have
- **THEN** the build fails, naming the include, and no office file is written

### Requirement: Every output formats rates one way

Every rate an output prints MUST read `passed/total (rate, low-high)`, with the 95% Wilson interval.
A per-task cell, where one task's few repeats make an interval noise, MAY print its counts alone
as `passed/total`. A missing rate or value MUST print as `—`. A signed difference MUST carry its sign. This applies to
the leaderboard, the version board, compare, the gate and the run report alike.

#### Scenario: One rate in two outputs

- **WHEN** a run's 9/10 appears in its report and in a leaderboard over it
- **THEN** both print `9/10 (90%, 60-98%)`
