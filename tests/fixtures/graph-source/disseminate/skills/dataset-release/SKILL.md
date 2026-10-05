---
name: dataset-release
description: >
  Cut a citable, versioned release of a product: bump the version, write a CHANGES entry, tag the
  exact state, and (optionally) mint a DOI. Trigger on "release the dataset", "cut a release".
plane: workflow
stamped: [D, M]
delegates_to: [archive]
---

# Skill: dataset-release

Freeze a product at a named version so it can be cited. You own the release judgment and delegate
DOI minting to the archive doer. Push the tagged state with `disseminate/publish`.
