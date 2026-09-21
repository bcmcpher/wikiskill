import { describe, expect, test } from "bun:test"

import * as plugin from "../wikiskill-guard"
import { wikiskillGuard } from "../wikiskill-guard"
import {
  GuardBlocked,
  StepBudgetExhausted,
  commandsIn,
  denialFor,
  matchesPattern,
  parseBudget,
  parseList,
} from "../wikiskill/guard"

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

describe("parseBudget", () => {
  test("reads a positive integer and nothing else", () => {
    expect(parseBudget("40")).toBe(40)
    expect(parseBudget(undefined)).toBeNull()
    expect(parseBudget("0")).toBeNull()
    expect(parseBudget("-1")).toBeNull()
    expect(parseBudget("2.5")).toBeNull()
    expect(parseBudget("lots")).toBeNull()
  })
})

describe("the step budget", () => {
  test("allows exactly the budget and refuses the next call", async () => {
    process.env.WIKISKILL_MAX_STEPS = "2"
    const plugin = await wikiskillGuard()
    const hook = plugin["tool.execute.before"]

    expect(await hook({ tool: "read" }, { args: {} })).toBeUndefined()
    expect(await hook({ tool: "read" }, { args: {} })).toBeUndefined()
    await expect(hook({ tool: "read" }, { args: {} })).rejects.toBeInstanceOf(StepBudgetExhausted)
    delete process.env.WIKISKILL_MAX_STEPS
  })

  test("a refused call still costs a step", async () => {
    process.env.WIKISKILL_MAX_STEPS = "1"
    process.env.WIKISKILL_GUARD_DENY = '["git push*"]'
    const plugin = await wikiskillGuard()
    const hook = plugin["tool.execute.before"]

    await expect(hook({ tool: "bash" }, { args: { command: "git push" } })).rejects.toBeInstanceOf(
      GuardBlocked,
    )
    await expect(hook({ tool: "bash" }, { args: { command: "ls" } })).rejects.toBeInstanceOf(
      StepBudgetExhausted,
    )
    delete process.env.WIKISKILL_MAX_STEPS
    delete process.env.WIKISKILL_GUARD_DENY
  })

  test("with no budget a unit runs as long as its timeout allows", async () => {
    delete process.env.WIKISKILL_MAX_STEPS
    const plugin = await wikiskillGuard()
    for (let call = 0; call < 50; call += 1) {
      expect(await plugin["tool.execute.before"]({ tool: "read" }, { args: {} })).toBeUndefined()
    }
  })

  test("the message is the one the runner classifies on", async () => {
    expect(new StepBudgetExhausted(40).message).toContain("step budget of 40 exhausted")
  })
})

describe("the plugin module's exports", () => {
  /**
   * OpenCode calls every export of a plugin file as a plugin factory. When this module also
   * exported its error classes the whole plugin failed to load with
   * `Cannot call a class constructor GuardBlocked without |new|`, and the failure was one ERROR
   * line in a log while the run carried on with no guard at all. This test is that bug's alarm.
   */
  test("is nothing but callable plugin factories", async () => {
    const exported = Object.entries(plugin)
    expect(exported.length).toBeGreaterThan(0)

    for (const [name, value] of exported) {
      expect(typeof value, `export ${name} must be a function`).toBe("function")
      const hooks = await (value as () => Promise<Record<string, unknown>>)()
      expect(hooks, `export ${name} must return hooks`).toBeObject()
      expect(Object.keys(hooks), `export ${name} must register a hook`).not.toBeEmpty()
    }
  })
})
