## REMOVED Requirements

### Requirement: Unsent follow-up turns are reported

**Reason**: Follow-up turns are now sent by every evaluation backend, so the warning would be false.

**Migration**: None. Suites with `followups` keep their hash. Runs made while the warning applied
record it in `run.json` `warnings`, and `eval-scoring` keeps them from pooling with new runs.
