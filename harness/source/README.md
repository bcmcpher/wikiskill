# Single-source components

wikiskill's own skills, commands and meta-agents are authored **here, once**. Every harness layout
is generated from this tree by `wikiskill build`, so a fix reaches every harness by rebuilding:

```bash
wikiskill build --harness opencode --collection <name>
wikiskill install --harness opencode --scope global --collection <name>
```

Never edit a built file under `dist/` or inside a harness config directory. `dist/` is git-ignored
and is deleted and rewritten on every build, and `wikiskill install --uninstall` removes exactly the
files it wrote.

## Layout

```
harness/source/
  skills/<name>/SKILL.md     # plus any references/, scripts/ — copied unchanged
  agents/<name>.md
  commands/<name>.md
```

## Neutral frontmatter

Frontmatter here is harness-neutral. The build translates it; a harness-specific key does not
belong in this tree.

| Key | Applies to | Meaning |
|---|---|---|
| `name` | all | Component id. Defaults to the directory or file name. |
| `description` | all | **Required.** What it does and when to use it — this is what a model routes on. |
| `role_model` | agents, commands | An *alias* (`judge`, `maintainer`, `proposer`, `haiku`, …), never a concrete model. |
| `capabilities` | agents | Subset of `read`, `search`, `bash`, `edit`, `web`. Anything omitted is denied. |

### `role_model` resolves per harness

The manifest's `[aliases.<harness>]` table maps an alias to a concrete `provider/model`:

```toml
[aliases.opencode]
maintainer = "ollama/qwen3:30b-a3b"
```

An alias with **no** mapping is not an error. The built component omits the model key and inherits
its caller's model, and the build lists the alias as unmapped so the omission is visible.

### `capabilities` is a deny-by-default allowlist

`capabilities: [read, search]` becomes, for OpenCode, `mode: subagent` plus a permission block that
denies `edit`, `bash` and `webfetch`, and a `tools` map that leaves only the read and search tools
enabled. Grant the least a component needs; a meta-agent that summarises logs has no business
running a shell.

## Status

This tree is intentionally near-empty. `add-experience-wiki` adds the first meta-agent
(the wiki maintainer); `add-skill-refinement` adds the proposer. What exists now is the packaging
path those changes build on.
