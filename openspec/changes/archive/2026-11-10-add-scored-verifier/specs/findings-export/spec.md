## ADDED Requirements

### Requirement: Scores are exported with the long-format data

For a `report` table whose run declared a verifier `score`, `findings tables` MUST add to each task
row of `findings.csv` the score field's name, mean, interval low and high, the count of scored units,
and the count without a score. Rows with no score MUST leave those columns empty. The values MUST
come from the bundle alone and MUST equal the run report's.

#### Scenario: A scored study

- **WHEN** a study's `report` table covers a run whose task declared `score: score`
- **THEN** each of that task's rows in `findings.csv` gives the mean, interval and counts that the
  run report gives

#### Scenario: A study without scores

- **WHEN** no run in a study declared a `score`
- **THEN** the score columns are present in `findings.csv` and empty in every row
