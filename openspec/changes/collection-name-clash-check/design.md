## Context

See proposal.md for why. Current state:

- `Collection.duplicates` (`collection.py`) groups discovered components by `(kind, qualified
  name)`. `build_collection` (`build.py`) keys its owners map on `(kind directory, flat name)`,
  where the flat name is the bare name (`_flat_names`). It also keys `("plugins", plugin)` for the
  plugin mirror. The check therefore misses every clash whose qualified names differ.
- `_build_skill` copies every entry of the skill directory except `SKILL.md` and `skip`. `build()`
  passes a non-empty `skip` only for a plugin-root skill (`plugin_skill_skip`), which includes each
  top-level child that holds a `SKILL.md` at any depth (`rglob`).
- Discovery reports only `skills/<name>/SKILL.md` and, for a flat plugin, the plugin and its direct
  children. A deeper `SKILL.md` is never a component, but OpenCode loads it from the built layout.
- Version hashes read only a component's main file. No hash covers built output.

## Goals / Non-Goals

**Goals:**
- Every clash the collection build rejects is also a `collection check` failure.
- One nested-skill rule for every skill the build installs.

**Non-Goals:**
- No change to how a plugin-root skill treats `evals/`, its other skills, or plugin-level entries.
- No change to the single-tree `wikiskill build` clash check (`built` map in `build()`), which keys
  on the output path already.
- No change to the claude-code rule that drops a command shadowed by a skill of the same name. That
  is a warning in the build, not a clash.

## Decisions

1. **Check reuses the build's key.** A new `Collection.flat_clashes(components)` groups by
   `(kind, names.bare(name))` and reports groups whose qualified names differ. Groups with equal
   qualified names stay in `duplicates`, so one clash is not reported twice. Alternative: replace
   `duplicates` with a bare-name check. Rejected: the existing message for `dup/dup` names two paths
   for one qualified name, which reads better than a flat-name message.
2. **Plugin-name clash from sources, not components.** `Collection.plugin_clashes()` walks
   `component_roots` of each claude-plugin source, as the build does, and reports a plugin name
   seen twice. Reading components would miss two plugins that share a name but no component.
3. **One helper for nested skills.** Move the `rglob("SKILL.md")` test out of `plugin_skill_skip`
   into `nested_skill_dirs(skill_dir) -> set[str]`. `_build_skill` always unions it into `skip`;
   `plugin_skill_skip` keeps calling it. The rule stays "top-level child with a `SKILL.md` at any
   depth", the same as today for a plugin-root skill. Alternative: drop only the directory that
   directly holds the nested `SKILL.md`, and keep its siblings. Rejected for this change: it would
   alter the plugin-root rule too, and the existing spec scenario (`p/examples/inner/SKILL.md`) is
   written against the top-level rule.
4. **Warning, not failure, for left-out content.** A nested `SKILL.md` is often a template or an
   example. The build behaviour is safe; the author needs to know, not to be blocked. The warning
   uses the `~` marker that `_check_plugin_paths` already uses.
5. **`_check_plugin_paths` uses the same skip.** A `${CLAUDE_SKILL_DIR}` path into a left-out
   directory is then reported as resolving to nothing, for every skill, not only a plugin-root one.

## Risks / Trade-offs

- [A skill keeps real content beside a nested `SKILL.md`, e.g. `examples/` with a README and a
  sample skill] → The whole `examples/` directory is left out. The check warning names it, so the
  author can move the sample skill or rename the file.
- [A collection that builds today now fails `collection check`] → Not possible for the flat-name
  and plugin-name checks: those collections already fail the build. The warning never fails.
- [Runs of a skill with a nested `SKILL.md`, before and after, installed different files on
  OpenCode and pool under one version hash] → No known collection has one. Note the change in the
  guide's build section; do not add a hash input.
- [The bare-name group for an opencode-layout source has no plugin] → `names.qualify` already
  returns the bare name for it, and the message names it as such.

## Open Questions

None that change the specs. The alternative in Decision 3 (narrower exclusion) is left for a later
change if a real collection needs it.
