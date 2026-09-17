import { afterEach, describe, expect, test } from "bun:test"
import { mkdtempSync, rmSync, writeFileSync } from "node:fs"
import { tmpdir } from "node:os"
import { join } from "node:path"

import { ConfigSource, parseRuntimeConfig, runtimeConfigPath } from "../wikiskill/config"

import { collection } from "./helpers"

const created: string[] = []

function runtimeFile(payload: unknown): string {
  const directory = mkdtempSync(join(tmpdir(), "wikiskill-config-"))
  created.push(directory)
  const path = join(directory, "runtime.json")
  writeFileSync(path, typeof payload === "string" ? payload : JSON.stringify(payload))
  return path
}

afterEach(() => {
  // Remove the directory, not just the file: leaving the mkdtemp dir behind litters /tmp with one
  // entry per test per run.
  for (const directory of created.splice(0)) {
    rmSync(directory, { recursive: true, force: true })
  }
})

describe("location", () => {
  test("follows XDG_CONFIG_HOME", () => {
    expect(runtimeConfigPath({ XDG_CONFIG_HOME: "/x/config" })).toBe(
      "/x/config/wikiskill/runtime.json",
    )
  })

  test("falls back to ~/.config", () => {
    expect(runtimeConfigPath({})).toMatch(/\/\.config\/wikiskill\/runtime\.json$/)
  })
})

describe("parsing", () => {
  test("reads what the Python side publishes", () => {
    const [parsed] = parseRuntimeConfig(
      JSON.stringify({ version: 1, collections: [collection()] }),
    )
    expect(parsed!.collection).toBe("dsh")
    expect(parsed!.watch.skill).toEqual(["govern/preregister"])
    expect(parsed!.watched[0]!.name).toBe("govern/preregister")
  })

  test("supplies defaults for absent bounds", () => {
    const [parsed] = parseRuntimeConfig(
      JSON.stringify({
        version: 1,
        collections: [{ collection: "c", raw_dir: "/r", error_log: "/e" }],
      }),
    )
    expect(parsed!.buffer_size).toBe(200)
    expect(parsed!.output_limit_bytes).toBe(16 * 1024)
    expect(parsed!.redact).toBe(true)
    expect(parsed!.watch).toEqual({ skill: [], agent: [], command: [] })
  })

  test("a payload without collections is refused", () => {
    expect(() => parseRuntimeConfig('{"version":1}')).toThrow(/collections/)
  })
})

describe("reloading", () => {
  test("no configuration means no logging, not an error", () => {
    const source = new ConfigSource(join(tmpdir(), "wikiskill-absent", "runtime.json"))
    expect(source.current()).toEqual([])
    expect(source.error).toBeNull()
  })

  test("a malformed configuration disables logging and records why", () => {
    const path = runtimeFile("{ not json")
    const source = new ConfigSource(path)
    expect(source.current()).toEqual([])
    expect(source.error).toBeTruthy()
  })

  test("an edited watch list is picked up without a restart", () => {
    const path = runtimeFile({ version: 1, collections: [collection()] })
    const source = new ConfigSource(path)
    const first = Date.now()
    expect(source.current(first)[0]!.watch.skill).toEqual(["govern/preregister"])

    writeFileSync(
      path,
      JSON.stringify({
        version: 1,
        collections: [collection({ watch: { skill: ["analyze/*"], agent: [], command: [] } })],
      }),
    )
    // A later clock reading is past the recheck window.
    expect(source.current(first + 60_000)[0]!.watch.skill).toEqual(["analyze/*"])
  })

  test("the file is not re-read on every call", () => {
    const path = runtimeFile({ version: 1, collections: [collection()] })
    const source = new ConfigSource(path)
    source.current(1_000_000)
    rmSync(path, { force: true })
    // Still within the recheck window, so the cached value is returned.
    expect(source.current(1_000_100)).toHaveLength(1)
  })
})
