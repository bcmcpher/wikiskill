/**
 * Files a write, edit or patch call left on disk, and the background scan that later compares them.
 *
 * The logger only records what a call produced: the path and its hash just after the call. Whether
 * the file was changed afterwards by someone else is `wikiskill corrections scan`'s question, asked
 * at the start of a later session. Mirrors `produced_files` in `src/wikiskill/corrections.py`.
 */

import { spawn } from "node:child_process"
import { createHash } from "node:crypto"
import { readFileSync } from "node:fs"
import { isAbsolute, join, normalize } from "node:path"
import { homedir } from "node:os"

import type { ProducedFile } from "./types"

/** Tools that write one named file, and the argument naming it. */
const WRITE_TOOLS: Record<string, string> = {
  write: "filePath",
  edit: "filePath",
  multiedit: "filePath",
}
const PATCH_TOOLS = new Set(["patch", "apply_patch"])
const PATCH_HEADERS = ["*** Add File: ", "*** Update File: ", "*** Delete File: ", "*** Move to: "]

/** The produced files one tool call may record. */
export const PRODUCED_LIMIT = 50

/** The files an `apply_patch` envelope adds, updates, deletes or moves to. */
export function patchPaths(text: string): string[] {
  const found: string[] = []
  for (const line of text.split(/\r?\n/)) {
    for (const header of PATCH_HEADERS) {
      const name = line.startsWith(header) ? line.slice(header.length).trim() : ""
      if (name && !found.includes(name)) found.push(name)
    }
  }
  return found
}

function fileHash(path: string): string | null {
  try {
    return "sha256:" + createHash("sha256").update(readFileSync(path)).digest("hex")
  } catch {
    // Deleted by the call, or unreadable: either way there is no content to compare later.
    return null
  }
}

/** Hashed now, by the caller, while the file is as the call left it. */
export function producedFiles(
  tool: string,
  args: Record<string, unknown> | undefined,
  directory: string | null,
): ProducedFile[] {
  const input = args ?? {}
  let names: string[] = []
  if (tool in WRITE_TOOLS) {
    const name = input[WRITE_TOOLS[tool]]
    if (typeof name === "string" && name) names = [name]
  } else if (PATCH_TOOLS.has(tool)) {
    const text = input.patchText ?? input.patch ?? input.input
    if (typeof text === "string") names = patchPaths(text)
  }
  return names.slice(0, PRODUCED_LIMIT).map((name) => {
    const expanded = name.startsWith("~/") ? join(homedir(), name.slice(2)) : name
    const path = normalize(
      isAbsolute(expanded) ? expanded : join(directory ?? process.cwd(), expanded),
    )
    return { path, hash: fileHash(path) }
  })
}

/** A session starting within this long of the last scan this process started does not start one. */
export const SCAN_EVERY_MS = 10 * 60 * 1000

export type Spawner = (argv: string[]) => void

/** Detached and unwaited: the scan outlives nothing it could slow down, and prints nowhere. */
export const spawnDetached: Spawner = (argv) => {
  const child = spawn(argv[0], argv.slice(1), { detached: true, stdio: "ignore" })
  child.on("error", () => {})
  child.unref()
}

export class Scanner {
  private last = -Infinity

  constructor(private readonly spawner: Spawner = spawnDetached) {}

  /** Start a scan unless one started recently. Returns whether it did. */
  maybeStart(cli: string[] | null, now: number): boolean {
    if (!cli || cli.length === 0 || now - this.last < SCAN_EVERY_MS) return false
    this.last = now
    this.spawner([...cli, "corrections", "scan", "--quiet"])
    return true
  }
}
