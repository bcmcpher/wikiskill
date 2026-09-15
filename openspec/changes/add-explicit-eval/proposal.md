## Why

Passive logs cannot answer "is this skill better on model X than model Y?" or "did the patch help?".
Traffic is uneven, unrepeatable, and rarely covers the same task twice. Explicit task suites fix
this. Each suite runs in fresh, isolated headless sessions: the same tasks, across a list of models,
with and without the collection, repeated. That gives controlled comparisons, supplies the replay the
refinement gate needs, and lets data-science-harness's already-specified routing suite run for the
first time.

## What Changes

- A declarative task-suite format (YAML): prompts, expected skill/agent routes, verifiers, rubric
  references, splits, fixtures, and required capabilities. An adapter reads data-science-harness
  `bench/` fixtures.
- A runner with a backend interface and an OpenCode backend. Each run gets isolated XDG dirs, inline
  config, project config disabled, a guard plugin blocking mutating commands, and deny-by-default
  permissions.
- Three conditions:
  - OFF: no collection
  - ROUTED: normal discovery
  - INJECTED: component text forced in, self-loading denied, or the agent run directly
- Repeats, a model matrix, and an endpoint preflight (reachability, tool calling, context length).
- Outcome classes that separate model behaviour from infrastructure failure.
- Verifier-first scoring, a rubric judge that is never a model under test, and a report with routing,
  pass rate, transfer/regression rates, and tokens per component × model × condition.
- `wikiskill eval` CLI and a `/wikiskill-eval` command that launches it in the background — never
  in the calling session.
- Eval trajectories are written into the raw log with `origin: eval`.

## Capabilities

### New Capabilities

- `task-suite`: the declarative task fixture format and its validation.
- `eval-runner`: isolated headless execution across conditions, repeats, and models, with preflight and
  outcome classification.
- `eval-scoring`: verifiers, rubric judging, metrics, and reports.

## Impact

- **Depends on `add-trace-logging`** for the raw schema, collection manifest, alias tables, and
  OpenCode build.
- Second on the roadmap: it needs only `add-trace-logging`, and it gives every later change real
  trajectories to build and test against.
- Enables replay in `add-skill-refinement`, conflict edges in `add-collection-graph`, and the routing
  probe in `add-dsh-pilot`. `add-claude-code-adapter` adds a second backend.
- New: `src/wikiskill/{suite,runner/,score/,report}.py`, `schemas/task-suite.schema.json`,
  `harness/opencode/guard/`, `harness/source/commands/wikiskill-eval.md`.
