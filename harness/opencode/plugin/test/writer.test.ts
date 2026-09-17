/**
 * Writing: one file per root session, append-only, and never fatal.
 */

import { afterEach, describe, expect, test } from "bun:test"
import { chmodSync, existsSync, mkdtempSync, readFileSync, rmSync } from "node:fs"
import { tmpdir } from "node:os"
import { join } from "node:path"

import { mapSessionStart, mapToolCall, DEFAULT_OPTIONS } from "../wikiskill/mapper"
import { appendEvent, logError, sessionLogPath } from "../wikiskill/writer"

import { NOW, identity } from "./helpers"

const created: string[] = []

function tmp(): string {
  const path = mkdtempSync(join(tmpdir(), "wikiskill-writer-"))
  created.push(path)
  return path
}

afterEach(() => {
  for (const path of created.splice(0)) {
    try {
      chmodSync(path, 0o755)
      rmSync(path, { recursive: true, force: true })
    } catch {
      // Best effort; these are temporary directories.
    }
  }
})

const ROOT = identity({ session_id: "ses_root", root_session_id: "ses_root" })
const event = (overrides = {}) => ({
  ...mapSessionStart({ id: "ses_root" }, ROOT, NOW),
  ...overrides,
})

describe("paths", () => {
  test("one file per root session, under the event's day", () => {
    expect(sessionLogPath("/raw", "2026-09-17T19:44:16.523Z", "ses_root")).toBe(
      "/raw/2026-09-17/ses_root.jsonl",
    )
  })

  test("a hostile session id cannot escape the day directory", () => {
    expect(sessionLogPath("/raw", "2026-09-17T00:00:00.000Z", "../../etc/passwd")).toBe(
      "/raw/2026-09-17/.._.._etc_passwd.jsonl",
    )
  })
})

describe("appending", () => {
  test("creates the day directory and writes one JSON line", () => {
    const raw = tmp()
    const path = appendEvent(raw, event())
    expect(readFileSync(path, "utf8").trim().split("\n")).toHaveLength(1)
    expect(JSON.parse(readFileSync(path, "utf8"))).toMatchObject({ type: "session_start" })
  })

  test("appends rather than truncating", () => {
    const raw = tmp()
    appendEvent(raw, event())
    const path = appendEvent(
      raw,
      mapToolCall({ tool: "bash", output: "ok", args: {} }, ROOT, DEFAULT_OPTIONS, NOW),
    )
    const lines = readFileSync(path, "utf8").trim().split("\n")
    expect(lines).toHaveLength(2)
    expect(JSON.parse(lines[1]!).type).toBe("tool_call")
  })

  test("a child session writes into its root's file", () => {
    const raw = tmp()
    const child = identity({
      session_id: "ses_child",
      root_session_id: "ses_root",
      parent_session_id: "ses_root",
    })
    const rootPath = appendEvent(raw, event())
    const childPath = appendEvent(
      raw,
      mapToolCall({ tool: "bash", output: "ok", args: {} }, child, DEFAULT_OPTIONS, NOW),
    )
    expect(childPath).toBe(rootPath)
    expect(readFileSync(rootPath, "utf8").trim().split("\n")).toHaveLength(2)
  })

  test("each line is a complete JSON object with no embedded newline", () => {
    const raw = tmp()
    const path = appendEvent(
      raw,
      mapToolCall(
        { tool: "bash", output: "line one\nline two\n", args: {} },
        identity(),
        DEFAULT_OPTIONS,
        NOW,
      ),
    )
    const lines = readFileSync(path, "utf8").trim().split("\n")
    expect(lines).toHaveLength(1)
    expect(JSON.parse(lines[0]!).payload.output).toContain("\n")
  })
})

describe("failing open", () => {
  test("an unwritable raw directory raises for the caller to catch, not the session", () => {
    const raw = tmp()
    chmodSync(raw, 0o500)
    expect(() => appendEvent(raw, event())).toThrow()
  })

  test("the error log records what failed", () => {
    const raw = tmp()
    const errorLog = join(raw, "_logger-errors.log")
    logError(errorLog, "append", new Error("disk full"))
    expect(readFileSync(errorLog, "utf8")).toContain("append: Error: disk full")
  })

  test("an unwritable error log is dropped rather than thrown", () => {
    const raw = tmp()
    chmodSync(raw, 0o500)
    expect(() => logError(join(raw, "nested", "_logger-errors.log"), "append", "x")).not.toThrow()
    expect(existsSync(join(raw, "nested"))).toBe(false)
  })
})
