/**
 * Version identity: the SHA-256 of a component's file as it was when it ran.
 *
 * Refinement (`add-skill-refinement`) compares a skill before and after on this hash, so it has to
 * be the file that actually ran — not the one that happens to be on disk later.
 */

import { createHash } from "node:crypto"
import { readFileSync, statSync } from "node:fs"

/** Bounded: a session touches a handful of components, not thousands. */
const CACHE_LIMIT = 256

/**
 * Cached by path *and* mtime/size.
 *
 * Keying on the path alone would mean a skill edited during a long-lived session kept reporting the
 * hash it had that morning.
 */
const cache = new Map<string, string>()

export function sourceHash(path: string | null): string | null {
  if (!path) return null
  try {
    const stats = statSync(path)
    const key = `${path}:${stats.mtimeMs}:${stats.size}`
    const cached = cache.get(key)
    if (cached) return cached
    const digest = "sha256:" + createHash("sha256").update(readFileSync(path)).digest("hex")
    cache.set(key, digest)
    while (cache.size > CACHE_LIMIT) {
      const oldest = cache.keys().next().value
      if (oldest === undefined) break
      cache.delete(oldest)
    }
    return digest
  } catch {
    // A component whose file we cannot read is still an activation worth recording.
    return null
  }
}

export function cacheSize(): number {
  return cache.size
}
