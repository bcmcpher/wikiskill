/**
 * Appending to the raw log, and the fail-open error log of last resort.
 *
 * Bun's own write API (`Bun.write`, `Bun.file().writer()`) truncates, so appending goes through
 * Bun's `node:fs` implementation. Writes are synchronous and per-line: a killed harness loses at
 * most the line in flight, and a log never interleaves half-events from two sessions.
 */

import { appendFileSync, mkdirSync } from "node:fs"
import { dirname, join } from "node:path"

import type { RawEvent } from "./types"

/** `raw/<YYYY-MM-DD>/<root_session_id>.jsonl` — one file per root session. */
export function sessionLogPath(rawDir: string, ts: string, rootSessionId: string): string {
  const day = ts.slice(0, 10)
  const safe = rootSessionId.replace(/[^A-Za-z0-9._-]/g, "_")
  return join(rawDir, day, `${safe}.jsonl`)
}

export function appendEvent(rawDir: string, event: RawEvent): string {
  const path = sessionLogPath(rawDir, event.ts, event.root_session_id)
  mkdirSync(dirname(path), { recursive: true })
  appendFileSync(path, JSON.stringify(event) + "\n", "utf8")
  return path
}

/**
 * Record a logger failure without ever raising.
 *
 * If even this fails — an unwritable directory, a full disk — the failure is dropped. A user's
 * session is never interrupted to report a problem with logging.
 */
export function logError(errorLogPath: string, where: string, error: unknown): void {
  try {
    const message = error instanceof Error ? (error.stack ?? error.message) : String(error)
    mkdirSync(dirname(errorLogPath), { recursive: true })
    appendFileSync(errorLogPath, `${new Date().toISOString()} ${where}: ${message}\n`, "utf8")
  } catch {
    // Dropped on purpose.
  }
}
