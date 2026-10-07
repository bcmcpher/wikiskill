# data-science-harness pilot

This branch, `results/dsh-pilot`, holds everything specific to the data-science-harness (DSH)
pilot. `main` holds none of it, so that it stays a clean starting point for a new collection.
Merge `main` into this branch for new wikiskill code.

| path | what |
|---|---|
| `pilots/<unit>/suite.yaml`, `dsh-<unit>.toml` | each unit's suite and collection manifest |
| `pilots/gen-data-dict/rubric.yaml` | curate's judge rubric |
| `pilots/data-science-harness.toml` | a manifest for the whole DSH marketplace |
| `pilots/models.toml` | the model catalogue: family, size and shape |
| `pilots/dsh-sweep/` | the model sweep (`sweep.sh`) and its completeness check |
| `docs/pilots/dsh`, `dsh-bids`, `dsh-curate` | the studies: bundled runs, tables, figures, report, slides |
| `openspec/changes/add-dsh-pilot/` | the pilot's design and its open tasks |

Copy a unit's manifest to `${XDG_CONFIG_HOME:-~/.config}/wikiskill/collections/` and point its
source at a DSH checkout before running its suite.
