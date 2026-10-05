---
name: checkpoint
description: >
  Save a named, provenanced checkpoint of work in progress. Trigger on "checkpoint this", "save
  where I am". Not a release.
plane: workflow
delegates_to: [datalad]
---

# Skill: checkpoint

Save the current state with a message. Hand the save itself to the datalad doer.
