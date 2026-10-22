## Context

`Source.dirs_for("skill")` returns `<plugin>/skills/` (or `skill/`) for each plugin, and `discover`
treats every entry holding a `SKILL.md` as a skill named `names.qualify(plugin, entry.name)`. The
plugin is the parent of the scanned directory (`_plugin_of`). The build copies a skill's directory
into the harness layout.

## Goals / Non-Goals

**Goals:**
- Find skills in the two flat forms with names that keep the `<plugin>/<name>` shape.
- Keep the current form's results byte-for-byte when a plugin has `skills/`.

**Non-Goals:**
- Flat forms for agents or commands.
- Reading `.claude-plugin/plugin.json` or `marketplace.json` to locate skills.
- A new layout name in the manifest.

## Decisions

- **Per-plugin fallback, not a new layout.** A plugin without `skills/` is scanned flat. This keeps
  manifests unchanged and handles a source that mixes forms. Alternative: a `claude-plugin-flat`
  layout; rejected because skills-comm mixes forms within one source.
- **`<plugin>/SKILL.md` is named `<plugin>/<plugin>`.** Every claude-plugin component stays
  qualified, so watch globs such as `<plugin>/*` and `plugins` narrowing behave the same for all
  forms. Alternative: the bare plugin name; rejected as the only unqualified name in the source.
- **Flat subdirectory scan skips the plugin's known non-skill directories.** `agents/`, `commands/`,
  `references/`, `scripts/`, hidden directories, and any subdirectory without a `SKILL.md` are not
  components. Only a direct child holding `SKILL.md` counts.
- **A plugin-level skill's build copies only what the skill needs.** When the skill directory is the
  plugin directory, the build copies it without its child skill directories, `agents/`, `commands/`
  and `.claude-plugin/`, so a ROUTED run does not install a sibling skill twice.

## Risks / Trade-offs

- [Risk] A plugin's helper directory happens to contain a `SKILL.md` and becomes a component →
  Mitigation: `collection init` lists what it found; the watch list decides what is evaluated.
- [Risk] A plugin both is a skill and holds flat skills, so the plugin-level skill's directory
  contains other skills → Mitigation: the build exclusion above; a test covers the case.
- [Risk] A collection later adds `skills/` to a flat plugin, and its flat skills vanish → Mitigation:
  `collection check` reports watch entries that no longer resolve, as today.

## Open Questions

None.
