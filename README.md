# wikiskill

An in-harness package for **logging, evaluating and refining agent skills and subagents** across
models and harnesses. It follows the WikiSkill approach: raw traces → a persistent wiki of distilled
patterns → gated skill refinement.

- **Primary target:** [OpenCode](https://opencode.ai) with open models behind any OpenAI-compatible endpoint.
- **Secondary target:** Claude Code.
- **Signals:** what a skill or subagent does with a given model, and what the user had to correct.
- **Modes:** passive (real sessions over time) and explicit (task suites in fresh headless sessions).

Based on *WikiSkill: Compiling Agent Experience into Persistent Knowledge for Skill Evolution*
(Tang et al., arXiv [2608.27454](https://arxiv.org/abs/2608.27454)). This is an independent
implementation, not affiliated with the authors.

**Status:** design only. Nothing is implemented yet.

## Documents

- [Paper and unofficial implementations, reconciled](docs/research/wikiskill-paper-and-implementations.md)
- [Related work and what to borrow](docs/research/related-work.md)
- [Architecture](docs/design/architecture.md)
- [Roadmap: implementation order](ROADMAP.md)
- [Implementation plan as OpenSpec changes](openspec/changes/)
