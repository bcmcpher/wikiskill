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
  // Only an unqualified name falls back to the pattern's last segment. Stripping the qualifier from
  // the *pattern* as well would make `other-plugin/preregister` match `govern/preregister`, and log
  // a different plugin's component under a watched name.
  if (name.includes("/")) return false
  return patterns.some((pattern) => {
    const patternBare = pattern.includes("/") ? pattern.slice(pattern.lastIndexOf("/") + 1) : pattern
    return globToRegExp(patternBare).test(name)
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
    if (samePath(candidate, component.path)) return component
  }
  return null
}

/**
 * Whether two paths name the same file, allowing one to be a relative form of the other.
 *
 * A suffix has to begin at a directory boundary and carry a directory of its own: models do read
 * relative paths, but treating a bare `SKILL.md` as a match would attribute an activation to
 * whichever watched component happened to be listed first.
 */
function samePath(candidate: string, path: string): boolean {
  if (candidate === path) return true
  const [longer, shorter] = candidate.length >= path.length ? [candidate, path] : [path, candidate]
  const relative = shorter.replace(/^\/+/, "")
  // A directory of its own is what makes the suffix specific enough to trust.
  if (!relative.includes("/")) return false
  return longer.endsWith(`/${relative}`)
}
