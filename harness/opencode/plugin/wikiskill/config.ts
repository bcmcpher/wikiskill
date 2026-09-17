/**
 * Reading the resolved logger configuration.
 *
 * Python owns the TOML manifest; `wikiskill collection check --sync` and `wikiskill install`
 * publish this JSON view. The plugin never parses TOML and never shells out to Python.
 */

import { existsSync, readFileSync, statSync } from "node:fs"
import { homedir } from "node:os"
import { join } from "node:path"

import type { CollectionConfig, RuntimeConfig } from "./types"

/** How long a loaded configuration is trusted before its mtime is checked again. */
const RECHECK_MS = 5_000

export function runtimeConfigPath(env: Record<string, string | undefined> = process.env): string {
  const base = env.XDG_CONFIG_HOME?.trim() || join(homedir(), ".config")
  return join(base, "wikiskill", "runtime.json")
}

export function parseRuntimeConfig(text: string): CollectionConfig[] {
  const parsed = JSON.parse(text) as RuntimeConfig
  if (!parsed || typeof parsed !== "object" || !Array.isArray(parsed.collections)) {
    throw new Error("runtime.json has no `collections` array")
  }
  return parsed.collections.map(normalise)
}

function normalise(raw: CollectionConfig): CollectionConfig {
  return {
    collection: raw.collection,
    raw_dir: raw.raw_dir,
    error_log: raw.error_log,
    buffer_size: raw.buffer_size > 0 ? raw.buffer_size : 200,
    output_limit_bytes: raw.output_limit_bytes > 0 ? raw.output_limit_bytes : 16 * 1024,
    redact: raw.redact !== false,
    watch: {
      skill: raw.watch?.skill ?? [],
      agent: raw.watch?.agent ?? [],
      command: raw.watch?.command ?? [],
    },
    source_roots: raw.source_roots ?? [],
    watched: raw.watched ?? [],
  }
}

/**
 * A configuration that reloads itself when the file changes.
 *
 * `wikiskill collection check --sync` can run while a session is open, so the plugin must pick up a
 * new watch list without a restart — but it must not stat the file on every tool call either.
 */
export class ConfigSource {
  private collections: CollectionConfig[] = []
  /** `<mtimeMs>:<size>`. Size is part of it because two edits can land in the same millisecond. */
  private signature = ""
  private checkedAt = 0
  private loadError: string | null = null

  constructor(private readonly path: string = runtimeConfigPath()) {}

  get error(): string | null {
    return this.loadError
  }

  current(now = Date.now()): CollectionConfig[] {
    if (now - this.checkedAt < RECHECK_MS) return this.collections
    this.checkedAt = now
    try {
      if (!existsSync(this.path)) {
        this.collections = []
        this.signature = ""
        return this.collections
      }
      const stats = statSync(this.path)
      const signature = `${stats.mtimeMs}:${stats.size}`
      if (signature === this.signature) return this.collections
      this.collections = parseRuntimeConfig(readFileSync(this.path, "utf8"))
      this.signature = signature
      this.loadError = null
    } catch (error) {
      // An unreadable or malformed configuration disables logging; it never breaks the session.
      this.loadError = error instanceof Error ? error.message : String(error)
      this.collections = []
    }
    return this.collections
  }
}
