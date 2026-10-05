/**
 * Appending to the raw log, and the fail-open error log of last resort.
 *
 * Bun's own write API (`Bun.write`, `Bun.file().writer()`) truncates, so appending goes through
 * Bun's `node:fs` implementation. Writes are synchronous and per-line: a killed harness loses at
 * most the line in flight, and a log never interleaves half-events from two sessions.
 */

import { createHash } from "node:crypto"
import { appendFileSync, existsSync, mkdirSync, readFileSync, renameSync, writeFileSync } from "node:fs"
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

/** How long a session counts as active for `wikiskill note`, and how many are remembered. */
const ACTIVE_SESSION_TTL_MS = 24 * 60 * 60 * 1000
const ACTIVE_SESSION_LIMIT = 20

/**
 * `raw/.sessions/<project-hash>.json`: which logged sessions are open in a project directory.
 *
 * The hash is the first 16 hex digits of the SHA-256 of the directory path, which is what
 * `wikiskill note` computes from its own working directory to find the session it was run from.
 */
export function activeSessionsPath(rawDir: string, directory: string): string {
  const hash = createHash("sha256").update(directory).digest("hex").slice(0, 16)
  return join(rawDir, ".sessions", `${hash}.json`)
}

/**
 * Record that a logged root session is active in `directory`, keeping the others that still are.
 *
 * Read, merged and replaced by rename, so a reader never sees half a file. Two sessions writing at
 * the same instant can lose one entry, which costs that session a `--session` flag, nothing more.
 */
export function noteActiveSession(
  rawDir: string,
  directory: string,
  sessionId: string,
  now = Date.now(),
): string {
  const path = activeSessionsPath(rawDir, directory)
  let sessions: Record<string, string> = {}
  if (existsSync(path)) {
    try {
      const parsed = JSON.parse(readFileSync(path, "utf8"))
      if (parsed && typeof parsed.sessions === "object") sessions = parsed.sessions
    } catch {
      // A damaged file is replaced rather than trusted.
    }
  }
  sessions[sessionId] = new Date(now).toISOString()
  const kept = Object.entries(sessions)
    .filter(([, seen]) => now - Date.parse(seen) <= ACTIVE_SESSION_TTL_MS)
    .sort(([, a], [, b]) => Date.parse(b) - Date.parse(a))
    .slice(0, ACTIVE_SESSION_LIMIT)
  mkdirSync(dirname(path), { recursive: true })
  const staging = `${path}.${process.pid}.tmp`
  writeFileSync(staging, JSON.stringify({ directory, sessions: Object.fromEntries(kept) }) + "\n")
  renameSync(staging, path)
  return path
}
