/** Watch-list matching. Pure, and deliberately the same glob semantics as Python's fnmatch. */

import type { CollectionConfig, ComponentKind, WatchedComponent } from "./types"

const cache = new Map<string, RegExp>()

/** `*` matches any run of characters including `/`, `?` matches one — as fnmatch does. */
export function globToRegExp(pattern: string): RegExp {
  const cached = cache.get(pattern)
  if (cached) return cached
  let source = "^"
  for (let i = 0; i < pattern.length; i++) {
    const char = pattern[i]
    if (char === "*") source += ".*"
    else if (char === "?") source += "."
    else if (char === "[") {
      const close = pattern.indexOf("]", i + 1)
      if (close === -1) {
        source += "\\["
      } else {
        let set = pattern.slice(i + 1, close)
        if (set.startsWith("!")) set = "^" + set.slice(1)
        source += `[${set}]`
        i = close
      }
    } else source += char.replace(/[.+^${}()|\\]/g, "\\$&")
  }
  const re = new RegExp(source + "$")
  cache.set(pattern, re)
  return re
}

export function matchesAny(name: string, patterns: string[]): boolean {
  return patterns.some((pattern) => globToRegExp(pattern).test(name))
}

/**
 * Whether a collection watches a component.
 *
 * Both the bare name and any plugin-qualified name are tried, because OpenCode reports a skill as
 * `preregister` while a claude-plugin source tree names it `govern/preregister`.
 */
export function watches(config: CollectionConfig, kind: ComponentKind, name: string): boolean {
  const patterns = config.watch[kind] ?? []
  if (matchesAny(name, patterns)) return true
  const bare = name.includes("/") ? name.slice(name.lastIndexOf("/") + 1) : name
  return patterns.some((pattern) => {
    const patternBare = pattern.includes("/") ? pattern.slice(pattern.lastIndexOf("/") + 1) : pattern
    return globToRegExp(patternBare).test(bare)
  })
}

/**
 * The watched component whose source file a path refers to, if any.
 *
 * This is how a direct read of a skill's text counts as an activation. The manifest side resolved
 * each watched component to its main file and its canonical name, so nothing here has to infer a
 * name from a path layout.
 */
export function watchedComponentFor(
  config: CollectionConfig,
  candidate: string,
): WatchedComponent | null {
  if (!candidate) return null
  for (const component of config.watched) {
    const path = component.path
    if (candidate === path || candidate.endsWith(path) || path.endsWith(candidate)) return component
  }
  return null
}
