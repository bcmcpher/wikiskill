/**
 * The watch-list gate: what is held, what is written, and when.
 */

import { describe, expect, test } from "bun:test"

import { mapSessionStart, mapToolCall, DEFAULT_OPTIONS } from "../wikiskill/mapper"
import { SessionRegistry } from "../wikiskill/sessions"

import { NOW, RECORDED_VERSION, collection, identity } from "./helpers"

const config = collection()

function registryWithSession(bufferSize = 200) {
  const registry = new SessionRegistry(bufferSize)
  registry.ensure("ses_root")
  registry.noteIdentity("ses_root", {
    provider: "ollama",
    model: "qwen3:1.7b",
    harnessVersion: RECORDED_VERSION,
  })
  return registry
}

function bufferTurn(registry: SessionRegistry, session: string, n: number) {
  registry.buffer(session, (cfg) =>
    mapToolCall(
      { tool: "bash", args: { command: `echo ${n}` }, output: String(n) },
      registry.identity(session, cfg.collection),
      { ...DEFAULT_OPTIONS, envValues: [] },
      NOW + n,
    ),
  )
}

describe("a session that never activates a watched component", () => {
  test("writes nothing", () => {
    const registry = registryWithSession()
    for (let i = 0; i < 5; i++) bufferTurn(registry, "ses_root", i)
    expect(registry.isLogging("ses_root")).toBe(false)
    expect(registry.collectionsFor("ses_root")).toEqual([])
  })
})

describe("activation mid-session", () => {
  test("flushes the turns that preceded it", () => {
    const registry = registryWithSession()
    for (let i = 0; i < 4; i++) bufferTurn(registry, "ses_root", i)

    const flushed = registry.activate("ses_root", config)

    expect(flushed).toHaveLength(4)
    expect(flushed.every((e) => e.collection === "dsh")).toBe(true)
    expect(registry.isLogging("ses_root")).toBe(true)
  })

  test("a flushed event keeps the time it happened, not the time it was flushed", () => {
    const registry = registryWithSession()
    bufferTurn(registry, "ses_root", 1)
    const [event] = registry.activate("ses_root", config)
    expect(event.ts).toBe(new Date(NOW + 1).toISOString())
  })

  test("a second activation does not replay the buffer", () => {
    const registry = registryWithSession()
    bufferTurn(registry, "ses_root", 1)
    expect(registry.activate("ses_root", config)).toHaveLength(1)
    expect(registry.activate("ses_root", config)).toHaveLength(0)
  })

  test("a second collection activating later gets the same history", () => {
    const registry = registryWithSession()
    bufferTurn(registry, "ses_root", 1)
    registry.activate("ses_root", config)
    const other = collection({ collection: "other" })
    expect(registry.activate("ses_root", other)).toHaveLength(1)
    expect(registry.collectionsFor("ses_root").sort()).toEqual(["dsh", "other"])
  })

  test("once logging, events are written rather than held", () => {
    const registry = registryWithSession()
    registry.activate("ses_root", config)
    bufferTurn(registry, "ses_root", 9)
    expect(registry.activate("ses_root", collection({ collection: "third" }))).toHaveLength(0)
  })
})

describe("the ring buffer is bounded", () => {
  test("the oldest turns are dropped past the buffer size", () => {
    const registry = registryWithSession(3)
    for (let i = 0; i < 10; i++) bufferTurn(registry, "ses_root", i)
    const flushed = registry.activate("ses_root", config)
    expect(flushed).toHaveLength(3)
    expect(flushed.map((e) => (e.payload.output as string))).toEqual(["7", "8", "9"])
  })

  test("the size follows the manifest", () => {
    const registry = registryWithSession(2)
    registry.setBufferSize(5)
    for (let i = 0; i < 10; i++) bufferTurn(registry, "ses_root", i)
    expect(registry.activate("ses_root", config)).toHaveLength(5)
  })
})

describe("delegation chains", () => {
  test("a child of a logged session is logged, into its root's file", () => {
    const registry = registryWithSession()
    registry.activate("ses_root", config)

    registry.link("ses_child", "ses_root")

    expect(registry.isLogging("ses_child")).toBe(true)
    const child = registry.identity("ses_child", "dsh")
    expect(child.root_session_id).toBe("ses_root")
    expect(child.parent_session_id).toBe("ses_root")
  })

  test("a grandchild still resolves to the original root", () => {
    const registry = registryWithSession()
    registry.activate("ses_root", config)
    registry.link("ses_child", "ses_root")
    registry.link("ses_grandchild", "ses_child")
    expect(registry.identity("ses_grandchild", "dsh").root_session_id).toBe("ses_root")
  })

  test("a child inherits its parent's model when it has none of its own", () => {
    const registry = registryWithSession()
    registry.activate("ses_root", config)
    registry.link("ses_child", "ses_root")
    const child = registry.identity("ses_child", "dsh")
    expect(child.model).toBe("qwen3:1.7b")
    expect(child.harness_version).toBe(RECORDED_VERSION)
  })

  test("a child of an unlogged session is not logged", () => {
    const registry = registryWithSession()
    registry.link("ses_child", "ses_root")
    expect(registry.isLogging("ses_child")).toBe(false)
  })
})

describe("message roles", () => {
  test("a text part is attributed through the message it belongs to", () => {
    const registry = registryWithSession()
    registry.noteMessageRole("msg_a", "assistant")
    registry.noteMessageRole("msg_u", "user")
    expect(registry.isAssistantMessage("msg_a")).toBe(true)
    expect(registry.isAssistantMessage("msg_u")).toBe(false)
    expect(registry.isAssistantMessage(undefined)).toBe(false)
    expect(registry.isAssistantMessage("msg_unknown")).toBe(false)
  })

  test("the role map does not grow without bound", () => {
    const registry = registryWithSession()
    for (let i = 0; i < 3_000; i++) registry.noteMessageRole(`msg_${i}`, "assistant")
    expect(registry.isAssistantMessage("msg_0")).toBe(false)
    expect(registry.isAssistantMessage("msg_2999")).toBe(true)
  })
})

describe("identity", () => {
  test("a session with no model yet is recorded as unknown rather than dropped", () => {
    const registry = new SessionRegistry()
    const id = registry.identity("ses_new", "dsh")
    expect(id.provider).toBe("unknown")
    expect(id.model).toBe("unknown")
    expect(id.root_session_id).toBe("ses_new")
  })

  test("origin follows the run mode", () => {
    const registry = new SessionRegistry(200, "eval")
    expect(registry.identity("ses_eval", "dsh").origin).toBe("eval")
  })

  test("the most recent activation is carried on later events", () => {
    const registry = registryWithSession()
    registry.setComponent("ses_root", { kind: "skill", name: "govern/preregister", source_hash: null })
    expect(registry.identity("ses_root", "dsh").component?.name).toBe("govern/preregister")
  })
})

describe("housekeeping", () => {
  test("stale unlogged sessions are forgotten", () => {
    const registry = registryWithSession()
    registry.ensure("ses_old")
    const later = Date.now() + 10 * 60 * 60 * 1000
    expect(registry.prune(6 * 60 * 60 * 1000, later)).toBe(2)
    expect(registry.size).toBe(0)
  })

  test("a logged session is kept even when idle", () => {
    const registry = registryWithSession()
    registry.activate("ses_root", config)
    registry.prune(6 * 60 * 60 * 1000, Date.now() + 10 * 60 * 60 * 1000)
    expect(registry.peek("ses_root")).toBeDefined()
  })
})

describe("session start", () => {
  test("is buffered like anything else until something activates", () => {
    const registry = registryWithSession()
    registry.buffer("ses_root", (cfg) =>
      mapSessionStart({ id: "ses_root", directory: "/tmp" }, registry.identity("ses_root", cfg.collection), NOW),
    )
    const [first] = registry.activate("ses_root", config)
    expect(first.type).toBe("session_start")
  })
})

describe("idle", () => {
  test("a session ends once per idle period, not once per turn", () => {
    const registry = registryWithSession()
    expect(registry.markIdle("ses_root")).toBe(true)
    expect(registry.markIdle("ses_root")).toBe(false)

    registry.clearIdle("ses_root")
    expect(registry.markIdle("ses_root")).toBe(true)
  })

  test("the flag lives with the session, so it goes when the session does", () => {
    const registry = registryWithSession()
    registry.markIdle("ses_root")
    registry.forget("ses_root")
    expect(registry.markIdle("ses_root")).toBe(true)
  })
})
