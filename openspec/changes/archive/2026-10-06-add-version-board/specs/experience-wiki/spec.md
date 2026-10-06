## ADDED Requirements

### Requirement: Review evidence can be restricted to one model

`wikiskill review --model <model>` and `wikiskill sample --model <model>` MUST sample only eval units
and live sessions run on that model, named with or without its provider, and the prompt MUST say so.
A live session whose model was not recorded MUST be left out. `--model` MUST be refused beside
`--sample`, whose evidence was fixed when it was taken. A proposal refined from that review MUST
record the model in its metadata. How the proposal is gated MUST NOT change.

#### Scenario: A proposal for a small model

- **WHEN** the user reviews `archive/archive-doer` with `--model ollama/qwen3:1.7b`, then refines it
- **THEN** every cited unit and session ran on `qwen3:1.7b`, and the proposal's metadata names
  that model
