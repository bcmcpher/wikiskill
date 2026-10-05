import { afterEach, describe, expect, test } from "bun:test"
import { createHash } from "node:crypto"
import { mkdtempSync, rmSync, writeFileSync } from "node:fs"
import { tmpdir } from "node:os"
import { join } from "node:path"

import { parseCli } from "../wikiskill/config"
import { SCAN_EVERY_MS, Scanner, patchPaths, producedFiles } from "../wikiskill/produced"

const created: string[] = []
afterEach(() => {
  for (const directory of created.splice(0)) rmSync(directory, { recursive: true, force: true })
})

function project(): string {
  const directory = mkdtempSync(join(tmpdir(), "wikiskill-produced-"))
  created.push(directory)
  return directory
}

const sha = (text: string) => "sha256:" + createHash("sha256").update(text).digest("hex")

describe("produced files", () => {
  test("a write names its file, hashed as the call left it", () => {
    const directory = project()
    writeFileSync(join(directory, "analysis.py"), "print(1)\n")
    expect(producedFiles("write", { filePath: "analysis.py" }, directory)).toEqual([
      { path: join(directory, "analysis.py"), hash: sha("print(1)\n") },
    ])
  })

  test("a deleted file is recorded with no hash", () => {
    const directory = project()
    expect(producedFiles("edit", { filePath: join(directory, "gone.py") }, null)).toEqual([
      { path: join(directory, "gone.py"), hash: null },
    ])
  })

  test("a patch names every file it touches, once", () => {
    const text = [
      "*** Begin Patch",
      "*** Update File: src/a.py",
      "@@",
      "-x",
      "+y",
      "*** Add File: src/b.py",
      "+z",
      "*** Update File: src/a.py",
      "*** Move to: src/c.py",
      "*** End Patch",
    ].join("\n")
    expect(patchPaths(text)).toEqual(["src/a.py", "src/b.py", "src/c.py"])
    expect(producedFiles("apply_patch", { patchText: text }, "/p").map((f) => f.path)).toEqual([
      "/p/src/a.py",
      "/p/src/b.py",
      "/p/src/c.py",
    ])
  })

  test("other tools produce nothing", () => {
    expect(producedFiles("bash", { command: "echo > x" }, "/p")).toEqual([])
    expect(producedFiles("read", { filePath: "x" }, "/p")).toEqual([])
  })
})

describe("the background scan", () => {
  test("starts at most once per interval, and only with a cli to run", () => {
    const spawned: string[][] = []
    const scanner = new Scanner((argv) => spawned.push(argv))
    expect(scanner.maybeStart(null, 0)).toBe(false)
    expect(scanner.maybeStart(["/bin/wikiskill"], 1_000)).toBe(true)
    expect(scanner.maybeStart(["/bin/wikiskill"], 2_000)).toBe(false)
    expect(scanner.maybeStart(["/bin/wikiskill"], 1_000 + SCAN_EVERY_MS)).toBe(true)
    expect(spawned[0]).toEqual(["/bin/wikiskill", "corrections", "scan", "--quiet"])
  })

  test("the cli comes from runtime.json, when it is well formed", () => {
    expect(parseCli(JSON.stringify({ cli: ["/usr/bin/python3", "-m", "wikiskill"] }))).toEqual([
      "/usr/bin/python3",
      "-m",
      "wikiskill",
    ])
    expect(parseCli(JSON.stringify({ collections: [] }))).toBeNull()
    expect(parseCli(JSON.stringify({ cli: [3] }))).toBeNull()
  })
})
