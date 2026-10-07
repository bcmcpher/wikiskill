# add-unit-retry

Repair a unit lost to a harness crash without rerunning its run: retry transient `infra_error` units inside a run, fill an existing run's unscored units with `eval --fill`, and have the DSH sweep fill before it gives up.
