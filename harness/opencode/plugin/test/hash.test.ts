/**
 * Version identity: the hash recorded on an activation must be the file that actually ran.
 */

import { afterEach, describe, expect, test } from "bun:test"
import { mkdtempSync, rmSync, writeFileSync } from "node:fs"
import { tmpdir } from "node:os"
import { join } from "node:path"

import { cacheSize, sourceHash } from "../wikiskill/hash"
const created: string[] = []

function skillFile(body: string): string {
  const directory = mkdtempSync(join(tmpdir(), "wikiskill-hash-"))
  created.push(directory)
  const path = join(directory, "SKILL.md")
  writeFileSync(path, body)
  return path
}

afterEach(() => {
  for (const directory of created.splice(0)) rmSync(directory, { recursive: true, force: true })
})

describe("source hash", () => {
  test("is a sha256 of the component's file", () => {
    expect(sourceHash(skillFile("---\nname: a\n---\n"))).toMatch(/^sha256:[0-9a-f]{64}$/)
  })

  test("differs between two versions of the same skill", () => {
    const path = skillFile("---\nname: a\ndescription: first\n---\n")
    const before = sourceHash(path)
    writeFileSync(path, "---\nname: a\ndescription: revised\n---\n")
    expect(sourceHash(path)).not.toBe(before)
  })

  test("is null for a file that cannot be read", () => {
    expect(sourceHash("/nonexistent/SKILL.md")).toBeNull()
    expect(sourceHash(null)).toBeNull()
  })

  test("the cache does not grow without bound", () => {
    const path = skillFile("x")
    for (let i = 0; i < 400; i++) {
      writeFileSync(path, `content ${i}`)
      sourceHash(path)
    }
    expect(cacheSize()).toBeLessThanOrEqual(256)
  })
})
