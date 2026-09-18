import { describe, expect, test } from "bun:test"

import {
  GuardBlocked,
  commandsIn,
  denialFor,
  matchesPattern,
  parseList,
  wikiskillGuard,
} from "../wikiskill-guard"

describe("parseList", () => {
  test("reads a JSON array of strings", () => {
    expect(parseList('["git push*", "sudo *"]')).toEqual(["git push*", "sudo *"])
  })

  test("treats anything else as no patterns at all", () => {
    expect(parseList(undefined)).toEqual([])
    expect(parseList("not json")).toEqual([])
    expect(parseList('{"deny": []}')).toEqual([])
    expect(parseList('["ok", 3, ""]')).toEqual(["ok"])
  })
})

describe("matchesPattern", () => {
  test("anchors at both ends", () => {
    expect(matchesPattern("git push", "git push")).toBe(true)
    expect(matchesPattern("git pushx", "git push")).toBe(false)
    expect(matchesPattern("xgit push", "git push*")).toBe(false)
  })

  test("* spans anything and ? one character", () => {
    expect(matchesPattern("git push origin main", "git push*")).toBe(true)
    expect(matchesPattern("rm -rf /", "rm -r? /")).toBe(true)
  })

  test("other metacharacters are literal", () => {
    expect(matchesPattern("rm -rf /", "rm -rf /")).toBe(true)
    expect(matchesPattern("rm -rX /", "rm -rf /")).toBe(false)
    expect(matchesPattern("a.b", "a.b")).toBe(true)
    expect(matchesPattern("axb", "a.b")).toBe(false)
  })
})

describe("commandsIn", () => {
  test("splits a chained command line", () => {
    expect(commandsIn({ command: "cd repo && git push origin main" })).toEqual([
      "cd repo && git push origin main",
      "cd repo",
      "git push origin main",
    ])
  })

  test("ignores arguments that are not commands", () => {
    expect(commandsIn({ filePath: "/tmp/x" })).toEqual([])
    expect(commandsIn({ command: "   " })).toEqual([])
  })
})

describe("denialFor", () => {
  const deny = ["git push*", "datalad push*"]

  test("refuses a denied command, chained or not", () => {
    expect(denialFor("bash", { command: "git push origin main" }, deny, [])).toEqual({
      subject: "git push origin main",
      pattern: "git push*",
    })
    expect(denialFor("bash", { command: "cd x && git push" }, deny, [])?.pattern).toBe("git push*")
  })

  test("allows what the suite did not deny", () => {
    expect(denialFor("bash", { command: "git commit -m 'v1.0'" }, deny, [])).toBeNull()
    expect(denialFor("read", { filePath: "README.md" }, deny, [])).toBeNull()
  })

  test("only shell tools are matched against command patterns", () => {
    expect(denialFor("edit", { command: "git push" }, deny, [])).toBeNull()
  })

  test("a denied tool is refused whatever its arguments", () => {
    expect(denialFor("webfetch", {}, [], ["webfetch"])?.subject).toBe("tool webfetch")
  })
})

describe("the plugin", () => {
  test("throws on a denied call and returns quietly otherwise", async () => {
    process.env.WIKISKILL_GUARD_DENY = '["git push*"]'
    const plugin = await wikiskillGuard()
    const hook = plugin["tool.execute.before"]

    await expect(
      hook({ tool: "bash" }, { args: { command: "git push origin main" } }),
    ).rejects.toBeInstanceOf(GuardBlocked)
    expect(await hook({ tool: "bash" }, { args: { command: "ls" } })).toBeUndefined()
    delete process.env.WIKISKILL_GUARD_DENY
  })

  test("with no configuration it blocks nothing", async () => {
    delete process.env.WIKISKILL_GUARD_DENY
    delete process.env.WIKISKILL_GUARD_TOOLS
    const plugin = await wikiskillGuard()
    expect(
      await plugin["tool.execute.before"]({ tool: "bash" }, { args: { command: "git push" } }),
    ).toBeUndefined()
  })
})
