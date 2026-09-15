## Context

data-science-harness has three layers:
- workflow-plane planner skills with `delegates_to` frontmatter
- capability-plane doer agents (datalad, nipoppy, bids, containers, archive)
- vendored CLI toolbox skills whose descriptions overlap with planners — datalad-save vs checkpoint,
  datalad-push vs publish, zenodo vs dataset-release

Its `openspec/specs/evaluation-protocol/spec.md` defines four probes: routing, provenance,
reproducibility, and cost. It requires a named control for each, per-model reporting, reuse of existing
instruments, and a plain statement of what is unrun.

Its `bin/install.sh --harness opencode` drops agent `tools:` and maps `haiku/sonnet/opus` to Anthropic
ids. It pins models only on `bids-doer` and `coordinator`.

The development machine is CPU-only, and Ollama defaults to a 4096-token context. Realistic pilot
models are:
- a small tool-capable local model, for smoke runs
- a mid-size open model on a remote OpenAI-compatible endpoint, for results

## Goals / Non-Goals

**Goals:**
- First executed routing probe for data-science-harness, reported per model and condition.
- Evidence on whether routing failures come from descriptions (routing loss) or instructions (content
  value).
- Real-use logs that seed the wiki.

**Non-Goals:**
- **Editing data-science-harness** — proposals from the pilot are delivered as patches for its owner.
- **Phase 2 execution** — specified only.
- **Cost probe** — its instrument is Claude Code-specific; token and time figures are reported without
  claiming the probe.

## Decisions

**Build, not install.sh.** wikiskill's collection build reads data-science-harness sources in place
and applies this repository's alias table. It maps `haiku` to the small tier and `sonnet`/`opus` to the
large tier, and translates `tools:` into OpenCode permission blocks. data-science-harness's own
installer is untouched.

**Probe mapping.**
- *Control:* the protocol's harness-off condition is OFF.
- *Conditions:* ROUTED and INJECTED add the decomposition the protocol does not define. They are
  reported as supplementary.
- *Route metrics:* `route@1`, `route@k` (k=3), and `capability@k` as defined in data-science-harness
  `bench/probes/routing.yaml`.
- *Handoff:* `handoff@k` uses three judges, per that fixture.

**Namespacing.** Expected routes like `govern/preregister` match OpenCode's flat skill names. The
adapter keeps a mapping, and the report prints both.

**Safety.** The guard denies `git push`, `datalad push|save|siblings`, network CLIs, and credential
access. Runs use a fixture workdir with a stub `.datalad` marker only where a prompt needs it;
`DATALAD_AUTOSAVE=0` is set.

**Model plan.**
1. A smoke run on one small local tool-capable model at context ≥ 16k.
2. The reported run on at least two open models from different families on a remote endpoint.

The judge comes from a third family.

**Watch list for passive use.** All workflow-plane planner skills plus `datalad-doer` and
`archive-doer`. Toolbox skills are excluded at first, to keep logs small.

## Risks / Trade-offs

- [No remote endpoint available] → Phase 1 reports only smoke results, labelled as such; the report
  states the reported run as unrun.
- [Flat skill-name collisions after build] → build fails on collision; mapping printed.
- [Small models fail preflight] → recorded per model; the pilot proceeds with those that pass.
- [Stop hook auto-commits in DataLad datasets] → `DATALAD_AUTOSAVE=0` in every run environment.

## Open Questions

- Which remote endpoint and model families will the reported run use?
- Should toolbox skills join the watch list once planners are stable?
