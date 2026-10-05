/**
 * The plugin as OpenCode actually drives it: hooks in, files on disk out.
 *
 * These are the tests for the guarantees that only hold end to end — that an unwatched session
 * writes nothing, that a watched one flushes its history, and that no failure in the logger can
 * reach the session.
 */

import { afterEach, beforeEach, describe, expect, test } from "bun:test"
import { chmodSync, existsSync, mkdirSync, mkdtempSync, readFileSync, readdirSync, rmSync, writeFileSync } from "node:fs"
import { createHash } from "node:crypto"
import { tmpdir } from "node:os"
import { join } from "node:path"

import { wikiskillLogger } from "../wikiskill-logger"
import { activeSessionsPath } from "../wikiskill/writer"
import type { CollectionConfig } from "../wikiskill/types"

import { RECORDED_VERSION, collection, events, tools } from "./helpers"

let home: string
let rawDir: string
let skillPath: string
const created: string[] = []

function writeRuntime(overrides: Partial<CollectionConfig> = {}) {
  const config = collection({
    raw_dir: rawDir,
    error_log: join(rawDir, "_logger-errors.log"),
    watched: [{ kind: "skill", name: "govern/preregister", path: skillPath }],
    ...overrides,
  })
  const directory = join(home, "wikiskill")
  mkdirSync(directory, { recursive: true })
  writeFileSync(
    join(directory, "runtime.json"),
    JSON.stringify({ version: 1, collections: [config] }),
  )
  return config
}

beforeEach(() => {
  home = mkdtempSync(join(tmpdir(), "wikiskill-logger-"))
  created.push(home)
  rawDir = join(home, "raw")
  const skillDir = join(home, "skills", "preregister")
  mkdirSync(skillDir, { recursive: true })
  skillPath = join(skillDir, "SKILL.md")
  writeFileSync(skillPath, "---\nname: preregister\ndescription: d\n---\n\nbody\n")
  process.env.XDG_CONFIG_HOME = home
})

afterEach(() => {
  delete process.env.XDG_CONFIG_HOME
  for (const directory of created.splice(0)) {
    try {
      chmodSync(directory, 0o755)
      rmSync(directory, { recursive: true, force: true })
    } catch {
      // Temporary directories; best effort.
    }
  }
})

function logLines(): any[] {
  if (!existsSync(rawDir)) return []
  const lines: any[] = []
  for (const day of readdirSync(rawDir)) {
    const dayDir = join(rawDir, day)
    if (!existsSync(dayDir) || !day.match(/^\d{4}-\d{2}-\d{2}$/)) continue
    for (const file of readdirSync(dayDir)) {
      for (const line of readFileSync(join(dayDir, file), "utf8").trim().split("\n")) {
        if (line) lines.push(JSON.parse(line))
      }
    }
  }
  return lines
}

const SESSION = "ses_f4f1a0774ffepL3wqqJ5f72ctQ"

async function session(hooks: any) {
  await hooks.event({ event: events["session.created"] })
  await hooks["chat.message"]({ sessionID: SESSION, model: { providerID: "ollama", modelID: "qwen3:1.7b" } })
}

const toolCall = (fixture: any): [any, any] => [fixture.input, fixture.output]

/** The skill fixture, pointed at a SKILL.md that really exists in this test's temp directory. */
const realSkillCall = (): [any, any] => [
  tools.skill.input,
  { ...tools.skill.output, metadata: { dir: join(home, "skills", "preregister") } },
]

describe("the watch-list gate", () => {
  test("a session that never activates a watched component writes nothing", async () => {
    writeRuntime()
    const hooks = await wikiskillLogger()
    await session(hooks)
    await hooks["tool.execute.after"](...toolCall(tools.unwatched))
    await hooks.event({ event: events["session.idle"] })

    expect(logLines()).toEqual([])
  })

  test("with no configuration at all, nothing is written and nothing throws", async () => {
    const hooks = await wikiskillLogger()
    await session(hooks)
    await hooks["tool.execute.after"](...toolCall(tools.skill))
    expect(logLines()).toEqual([])
  })

  test("an activation flushes the turns that preceded it, then logs from there on", async () => {
    writeRuntime()
    const hooks = await wikiskillLogger()
    await session(hooks)
    await hooks["tool.execute.after"](...toolCall(tools.unwatched))
    await hooks["tool.execute.after"](...toolCall(tools.skill))
    await hooks.event({ event: events["session.idle"] })

    const types = logLines().map((e) => e.type)
    expect(types).toContain("session_start")
    expect(types).toContain("component_activated")
    expect(types).toContain("session_end")
    // The unwatched call that preceded the activation was buffered, then flushed with it.
    expect(logLines().filter((e) => e.type === "tool_call").length).toBeGreaterThanOrEqual(2)
  })

  test("the activation records the component version that ran", async () => {
    writeRuntime()
    const hooks = await wikiskillLogger()
    await session(hooks)
    await hooks["tool.execute.after"](...realSkillCall())

    const activation = logLines().find((e) => e.type === "component_activated")
    expect(activation.component.name).toBe("preregister")
    expect(activation.component.source_hash).toMatch(/^sha256:[0-9a-f]{64}$/)
    expect(activation.payload.trigger).toBe("skill_tool")
  })

  test("the version is the watched source file's, not the installed copy's", async () => {
    // The build rewrites frontmatter, so the copy OpenCode loads hashes differently from the source.
    const sourceDir = join(home, "source", "preregister")
    mkdirSync(sourceDir, { recursive: true })
    const sourcePath = join(sourceDir, "SKILL.md")
    writeFileSync(sourcePath, "---\nname: preregister\ndescription: >\n  d\n---\n\nbody\n")
    writeRuntime({ watched: [{ kind: "skill", name: "govern/preregister", path: sourcePath }] })
    const hooks = await wikiskillLogger()
    await session(hooks)
    await hooks["tool.execute.after"](...realSkillCall())

    const expected = "sha256:" + createHash("sha256").update(readFileSync(sourcePath)).digest("hex")
    const activation = logLines().find((e) => e.type === "component_activated")
    expect(activation.component.source_hash).toBe(expected)
  })

  test("a component whose file cannot be read is still an activation", async () => {
    writeRuntime({ watched: [] })
    const hooks = await wikiskillLogger()
    await session(hooks)
    // The fixture's metadata.dir points somewhere that does not exist on this machine.
    await hooks["tool.execute.after"](...toolCall(tools.skill))

    const activation = logLines().find((e) => e.type === "component_activated")
    expect(activation).toBeDefined()
    expect(activation.component.source_hash).toBeNull()
  })

  test("every logged event carries the session's model", async () => {
    writeRuntime()
    const hooks = await wikiskillLogger()
    await session(hooks)
    await hooks["tool.execute.after"](...toolCall(tools.skill))

    const lines = logLines()
    expect(lines.length).toBeGreaterThan(0)
    expect(lines.every((e) => e.model === "qwen3:1.7b" && e.provider === "ollama")).toBe(true)
    expect(lines.every((e) => e.harness_version === RECORDED_VERSION)).toBe(true)
  })
})

describe("reading a skill counts as using it", () => {
  test("a read of a watched skill's file activates the session", async () => {
    writeRuntime()
    const hooks = await wikiskillLogger()
    await session(hooks)
    await hooks["tool.execute.after"](
      { tool: "read", sessionID: SESSION, callID: "c1", args: { filePath: skillPath } },
      { title: "SKILL.md", output: "---\n", metadata: {} },
    )

    const activation = logLines().find((e) => e.type === "component_activated")
    expect(activation.payload.trigger).toBe("read")
    expect(activation.component.name).toBe("govern/preregister")
  })
})

describe("delegation", () => {
  test("a child session's events land in its root's file, tagged with its parent", async () => {
    writeRuntime()
    const hooks = await wikiskillLogger()
    await session(hooks)
    await hooks["tool.execute.after"](...toolCall(tools.skill))
    await hooks["tool.execute.after"](...toolCall(tools.task))

    const childId = tools.task.output.metadata.sessionID
    await hooks["tool.execute.after"]({
      tool: "bash",
      sessionID: childId,
      callID: "c9",
      args: { command: "datalad create pilot" },
    }, { title: "bash", output: "created", metadata: {} })

    const lines = logLines()
    const delegation = lines.find((e) => e.type === "delegation")
    expect(delegation.payload.child_session_id).toBe(childId)

    const childEvent = lines.find((e) => e.session_id === childId)
    expect(childEvent).toBeDefined()
    expect(childEvent.parent_session_id).toBe(SESSION)
    expect(childEvent.root_session_id).toBe(SESSION)

    // One file, because the whole chain is one trajectory.
    const days = readdirSync(rawDir).filter((d) => d.match(/^\d{4}-\d{2}-\d{2}$/))
    expect(readdirSync(join(rawDir, days[0]!))).toHaveLength(1)
  })
})

describe("commands", () => {
  test("a watched slash command activates the session", async () => {
    writeRuntime()
    const hooks = await wikiskillLogger()
    await session(hooks)
    await hooks["command.execute.before"]({
      command: "wikiskill-trace",
      sessionID: SESSION,
      arguments: "dsh",
    })

    const activation = logLines().find((e) => e.type === "component_activated")
    expect(activation.component.kind).toBe("command")
    expect(activation.payload.trigger).toBe("command")
  })
})

describe("failing open", () => {
  test("an unwritable raw directory does not stop the session", async () => {
    mkdirSync(rawDir, { recursive: true })
    chmodSync(rawDir, 0o500)
    writeRuntime()
    const hooks = await wikiskillLogger()

    await session(hooks)
    await hooks["tool.execute.after"](...toolCall(tools.skill))
    await hooks.event({ event: events["session.idle"] })

    // Nothing threw, and nothing was written.
    expect(logLines()).toEqual([])
    chmodSync(rawDir, 0o755)
  })

  test("a malformed runtime configuration disables logging rather than breaking a session", async () => {
    mkdirSync(join(home, "wikiskill"), { recursive: true })
    writeFileSync(join(home, "wikiskill", "runtime.json"), "{ not json")
    const hooks = await wikiskillLogger()

    await session(hooks)
    await hooks["tool.execute.after"](...toolCall(tools.skill))

    expect(logLines()).toEqual([])
  })

  test("a garbled event is survived", async () => {
    writeRuntime()
    const hooks = await wikiskillLogger()
    await hooks.event({ event: undefined })
    await hooks.event({ event: { type: "session.created", properties: {} } })
    await hooks.event({ event: { type: "message.part.updated", properties: { part: null } } })
    await hooks["tool.execute.after"]({}, {})
    await hooks["command.execute.before"]({})
    await hooks["chat.message"]({})
    expect(logLines()).toEqual([])
  })

  test("a session error is recorded rather than swallowed", async () => {
    writeRuntime()
    const hooks = await wikiskillLogger()
    await session(hooks)
    await hooks["tool.execute.after"](...toolCall(tools.skill))
    await hooks.event({ event: events["session.error"] })

    const error = logLines().find((e) => e.type === "error")
    expect(error.payload.message).toContain("does not support tools")
  })
})

describe("no model is called", () => {
  test("the logger issues no network request", async () => {
    writeRuntime()
    const originalFetch = globalThis.fetch
    let calls = 0
    globalThis.fetch = (async (...args: any[]) => {
      calls += 1
      return originalFetch(...(args as Parameters<typeof fetch>))
    }) as typeof fetch

    try {
      const hooks = await wikiskillLogger()
      await session(hooks)
      await hooks["tool.execute.after"](...toolCall(tools.skill))
      await hooks["tool.execute.after"](...toolCall(tools.bash_with_secret))
      await hooks.event({ event: events["session.idle"] })
    } finally {
      globalThis.fetch = originalFetch
    }

    expect(calls).toBe(0)
  })
})

describe("redaction reaches the file", () => {
  test("a secret in a tool output never lands on disk", async () => {
    writeRuntime()
    const hooks = await wikiskillLogger()
    await session(hooks)
    await hooks["tool.execute.after"](...toolCall(tools.skill))
    await hooks["tool.execute.after"](...toolCall(tools.bash_with_secret))

    const blob = JSON.stringify(logLines())
    expect(blob).not.toContain("sk-ant-api03")
    expect(blob).toContain("[REDACTED:")
  })
})

describe("delegation", () => {
  const CHILD = "ses_9c21bb3310ceqT8mzzR4d91xKW"

  /** A completed tool call in an arbitrary session, as the hook delivers it. */
  const callIn = (sessionID: string, callID: string, command: string): [any, any] => [
    { tool: "bash", sessionID, callID, args: { command } },
    { title: "bash", output: "done", metadata: {} },
  ]

  test("a subagent's work before the task call returns is logged, not dropped", async () => {
    // The real order of a delegation: the child session runs to completion, and only when the
    // `task` call returns does the harness reveal which parent it belonged to.
    writeRuntime()
    const hooks = await wikiskillLogger()
    await session(hooks)
    await hooks["tool.execute.after"](...realSkillCall())

    await hooks["tool.execute.after"](...callIn(CHILD, "call_child_1", "datalad create"))
    await hooks["tool.execute.after"](...callIn(CHILD, "call_child_2", "datalad save"))
    await hooks["tool.execute.after"](...toolCall(tools.task))

    const childCalls = logLines().filter((e) => e.session_id === CHILD)
    expect(childCalls.map((e) => e.payload.input.command)).toEqual([
      "datalad create",
      "datalad save",
    ])
    // Into the root's file, under the root's id, so the chain reads as one trajectory.
    expect(childCalls.every((e) => e.root_session_id === SESSION)).toBe(true)
    expect(readdirSync(join(rawDir, childCalls[0].ts.slice(0, 10)))).toEqual([`${SESSION}.jsonl`])
  })

  test("a watched agent's own child session is logged even though it finished first", async () => {
    // Here nothing was logging while the child ran: the activation *is* the task call.
    writeRuntime({ watch: { skill: [], agent: ["datalad-doer"], command: [] } })
    const hooks = await wikiskillLogger()
    await session(hooks)

    await hooks["tool.execute.after"](...callIn(CHILD, "call_child_1", "datalad create"))
    await hooks["tool.execute.after"](...toolCall(tools.task))

    const lines = logLines()
    expect(lines.map((e) => e.type)).toContain("component_activated")
    expect(lines.map((e) => e.type)).toContain("delegation")
    const child = lines.filter((e) => e.session_id === CHILD)
    expect(child.map((e) => e.payload.input.command)).toEqual(["datalad create"])
  })

  test("a child session created while logging is logged from its first event", async () => {
    writeRuntime()
    const hooks = await wikiskillLogger()
    await session(hooks)
    await hooks["tool.execute.after"](...realSkillCall())

    await hooks.event({
      event: {
        type: "session.created",
        properties: { info: { id: CHILD, parentID: SESSION, version: RECORDED_VERSION } },
      },
    })

    const starts = logLines().filter((e) => e.type === "session_start" && e.session_id === CHILD)
    expect(starts).toHaveLength(1)
    expect(starts[0].parent_session_id).toBe(SESSION)
  })
})

describe("tool outcomes", () => {
  const toolPart = (state: any, callID = "call_fail") => ({
    type: "message.part.updated",
    properties: {
      part: { type: "tool", sessionID: SESSION, callID, tool: "bash", messageID: "msg_a", state },
    },
  })

  test("a failed tool call is recorded as failed, with its duration", async () => {
    // `tool.execute.after` never fires for a failed call, so the tool part is the only record of it.
    writeRuntime()
    const hooks = await wikiskillLogger()
    await session(hooks)
    await hooks["tool.execute.after"](...realSkillCall())

    await hooks.event({
      event: toolPart({
        status: "error",
        error: "exit status 1",
        input: { command: "false" },
        time: { start: 1_000, end: 1_250 },
      }),
    })

    const call = logLines().find((e) => e.type === "tool_call" && e.payload.tool === "bash")
    expect(call.payload.ok).toBe(false)
    expect(call.payload.error).toBe("exit status 1")
    expect(call.payload.duration_ms).toBe(250)
  })

  test("a completed call carries a real duration and is written once", async () => {
    writeRuntime()
    const hooks = await wikiskillLogger()
    await session(hooks)
    await hooks["tool.execute.after"](...realSkillCall())

    const state = {
      status: "completed",
      input: { command: "echo hi" },
      output: "hi",
      metadata: {},
      time: { start: 5_000, end: 5_040 },
    }
    await hooks.event({ event: toolPart(state, "call_ok") })
    await hooks["tool.execute.after"](
      { tool: "bash", sessionID: SESSION, callID: "call_ok", args: state.input },
      { title: "bash", output: "hi", metadata: {} },
    )

    const calls = logLines().filter((e) => e.type === "tool_call" && e.payload.tool === "bash")
    expect(calls).toHaveLength(1)
    expect(calls[0].payload.ok).toBe(true)
    expect(calls[0].payload.duration_ms).toBe(40)
  })

  test("a running call is not recorded until it finishes", async () => {
    writeRuntime()
    const hooks = await wikiskillLogger()
    await session(hooks)
    await hooks["tool.execute.after"](...realSkillCall())

    await hooks.event({
      event: toolPart({ status: "running", input: { command: "sleep 1" }, time: { start: 1 } }),
    })

    expect(logLines().filter((e) => e.payload?.tool === "bash")).toEqual([])
  })
})

describe("the pre-activation buffer", () => {
  test("streaming deltas do not evict the history the buffer exists to keep", async () => {
    // A streamed reply used to push one factory per delta into the ring, all of which evaluate to
    // nothing, shifting out the real events that preceded the activation.
    writeRuntime({ buffer_size: 4 })
    const hooks = await wikiskillLogger()
    await session(hooks)
    await hooks.event({
      event: {
        type: "message.updated",
        properties: { info: { id: "msg_stream", sessionID: SESSION, role: "assistant" } },
      },
    })
    await hooks["tool.execute.after"](
      { tool: "bash", sessionID: SESSION, callID: "call_early", args: { command: "echo early" } },
      { title: "bash", output: "early", metadata: {} },
    )

    for (let i = 0; i < 50; i++) {
      await hooks.event({
        event: {
          type: "message.part.updated",
          properties: {
            part: {
              type: "text",
              sessionID: SESSION,
              messageID: "msg_stream",
              text: `partial ${i}`,
              time: { start: 1_000 },
            },
          },
        },
      })
    }

    await hooks["tool.execute.after"](...realSkillCall())

    const commands = logLines()
      .filter((e) => e.type === "tool_call")
      .map((e) => e.payload.input?.command)
    expect(commands).toContain("echo early")
    // And no half-written turn from a delta that never ended.
    expect(logLines().filter((e) => e.type === "assistant_turn")).toEqual([])
  })

  test("a finished turn is still recorded once the session is logging", async () => {
    writeRuntime()
    const hooks = await wikiskillLogger()
    await session(hooks)
    await hooks["tool.execute.after"](...realSkillCall())
    await hooks.event({
      event: {
        type: "message.updated",
        properties: { info: { id: "msg_done", sessionID: SESSION, role: "assistant" } },
      },
    })
    await hooks.event({
      event: {
        type: "message.part.updated",
        properties: {
          part: {
            type: "text",
            sessionID: SESSION,
            messageID: "msg_done",
            text: "the answer",
            time: { start: 1_000, end: 1_200 },
          },
        },
      },
    })

    const turn = logLines().find((e) => e.type === "assistant_turn")
    expect(turn.payload.text).toBe("the answer")
  })
})

describe("correction signals", () => {
  const say = (hooks: any, text: string, sessionID = SESSION) =>
    hooks["chat.message"](
      { sessionID, model: { providerID: "ollama", modelID: "qwen3:1.7b" } },
      { message: { role: "user" }, parts: [{ type: "text", text }] },
    )
  const turns = () => logLines().filter((e) => e.type === "user_turn")

  test("the first message after an activation is a high-confidence user turn for it", async () => {
    writeRuntime()
    const hooks = await wikiskillLogger()
    await session(hooks)
    await hooks["tool.execute.after"](...realSkillCall())
    await say(hooks, "no, use a mixed model")

    const activated = logLines().find((e) => e.type === "component_activated")
    const [turn] = turns()
    expect(turn.confidence).toBe("high")
    expect(turn.component).toEqual(activated.component)
    expect(turn.payload.text).toBe("no, use a mixed model")
    expect(turn.payload.turns_since_activation).toBe(1)
    expect(turn.payload.seconds_since_component).toBeGreaterThanOrEqual(0)
  })

  test("later turns are medium, and the window closes after three", async () => {
    writeRuntime()
    const hooks = await wikiskillLogger()
    await session(hooks)
    await hooks["tool.execute.after"](...realSkillCall())
    for (const text of ["one", "two", "three", "four", "five"]) await say(hooks, text)

    expect(turns().map((e) => [e.payload.text, e.confidence])).toEqual([
      ["one", "high"],
      ["two", "medium"],
      ["three", "medium"],
    ])
  })

  test("the manifest sets the window's length", async () => {
    writeRuntime({ follow_up_turns: 1 })
    const hooks = await wikiskillLogger()
    await session(hooks)
    await hooks["tool.execute.after"](...realSkillCall())
    await say(hooks, "one")
    await say(hooks, "two")
    expect(turns().map((e) => e.payload.text)).toEqual(["one"])
  })

  test("a message before any activation is nobody's follow-up", async () => {
    writeRuntime()
    const hooks = await wikiskillLogger()
    await session(hooks)
    await say(hooks, "please preregister the comparison")
    await hooks["tool.execute.after"](...realSkillCall())
    expect(turns()).toEqual([])
  })

  test("another component's activation takes the window over", async () => {
    writeRuntime()
    const hooks = await wikiskillLogger()
    await session(hooks)
    await hooks["tool.execute.after"](...realSkillCall())
    await hooks["tool.execute.after"](...toolCall(tools.task))
    await say(hooks, "the dataset is in the wrong place")

    const [turn] = turns()
    expect(turn.component.kind).toBe("agent")
    expect(turn.component.name).toBe("datalad-doer")
    expect(turn.confidence).toBe("high")
  })

  test("a follow-up is stored as said, with no correction or approval label", async () => {
    writeRuntime()
    const hooks = await wikiskillLogger()
    await session(hooks)
    await hooks["tool.execute.after"](...realSkillCall())
    await say(hooks, "thanks, that's exactly right")
    const [turn] = turns()
    expect(Object.keys(turn.payload).sort()).toEqual([
      "seconds_since_component",
      "text",
      "text_length",
      "text_truncated",
      "turns_since_activation",
    ])
  })

  test("a secret in a follow-up is redacted like any other text", async () => {
    writeRuntime()
    const hooks = await wikiskillLogger()
    await session(hooks)
    await hooks["tool.execute.after"](...realSkillCall())
    await say(hooks, "use key sk-ant-api03-abcdefghijklmnopqrstuvwxyz0123456789")
    const [turn] = turns()
    expect(turn.payload.text).not.toContain("sk-ant-api03")
    expect(turn.redactions?.length).toBeGreaterThan(0)
  })

  test("a command's expansion is not a user turn", async () => {
    writeRuntime()
    const hooks = await wikiskillLogger()
    await session(hooks)
    await hooks["tool.execute.after"](...realSkillCall())
    await hooks["command.execute.before"]({ sessionID: SESSION, command: "unwatched-cmd" })
    await say(hooks, "<the command's template text>")
    await say(hooks, "that was wrong")
    expect(turns().map((e) => e.payload.text)).toEqual(["that was wrong"])
  })

  test("re-running the same skill after a follow-up records a repeat activation", async () => {
    writeRuntime()
    const hooks = await wikiskillLogger()
    await session(hooks)
    await hooks["tool.execute.after"](...realSkillCall())
    await say(hooks, "try again")
    await hooks["tool.execute.after"](...realSkillCall())

    const types = logLines().map((e) => e.type)
    const repeat = logLines().find((e) => e.type === "repeat_activation")
    expect(repeat.confidence).toBe("high")
    expect(repeat.payload.turns_since_previous).toBe(1)
    expect(repeat.payload.trigger).toBe("skill_tool")
    // It accompanies the second activation, so it is written after it.
    expect(types.lastIndexOf("component_activated")).toBeLessThan(types.indexOf("repeat_activation"))
  })

  test("loading a skill twice in one answer is not a repeat", async () => {
    writeRuntime()
    const hooks = await wikiskillLogger()
    await session(hooks)
    await hooks["tool.execute.after"](...realSkillCall())
    await hooks["tool.execute.after"](...realSkillCall())
    expect(logLines().some((e) => e.type === "repeat_activation")).toBe(false)
  })

  test("a re-run after the window closed is not a repeat", async () => {
    writeRuntime({ follow_up_turns: 1 })
    const hooks = await wikiskillLogger()
    await session(hooks)
    await hooks["tool.execute.after"](...realSkillCall())
    await say(hooks, "one")
    await say(hooks, "two")
    await hooks["tool.execute.after"](...realSkillCall())
    expect(logLines().some((e) => e.type === "repeat_activation")).toBe(false)
  })

  test("an evaluation has no user, so records no user turns", async () => {
    writeRuntime()
    process.env.WIKISKILL_ORIGIN = "eval"
    try {
      const hooks = await wikiskillLogger()
      await session(hooks)
      await hooks["tool.execute.after"](...realSkillCall())
      await say(hooks, "task prompt")
      expect(turns()).toEqual([])
    } finally {
      delete process.env.WIKISKILL_ORIGIN
    }
  })

  test("a logged session publishes itself for `wikiskill note`", async () => {
    writeRuntime()
    const hooks = await wikiskillLogger()
    await session(hooks)
    await hooks["tool.execute.after"](...realSkillCall())

    const directory = events["session.created"].properties.info.directory
    const path = activeSessionsPath(rawDir, directory)
    const published = JSON.parse(readFileSync(path, "utf8"))
    expect(published.directory).toBe(directory)
    expect(Object.keys(published.sessions)).toEqual([SESSION])
  })

  test("an unlogged session publishes nothing", async () => {
    writeRuntime()
    const hooks = await wikiskillLogger()
    await session(hooks)
    await say(hooks, "hello")
    expect(existsSync(join(rawDir, ".sessions"))).toBe(false)
  })
})

describe("produced files", () => {
  test("a write after an activation records the file and its hash", async () => {
    writeRuntime()
    const hooks = await wikiskillLogger()
    await session(hooks)
    await hooks["tool.execute.after"](...realSkillCall())
    const target = join(home, "analysis.py")
    writeFileSync(target, "print(1)\n")
    await hooks["tool.execute.after"](
      { tool: "write", sessionID: SESSION, callID: "call_write", args: { filePath: target } },
      { title: "", output: "Wrote file", metadata: {} },
    )

    const write = logLines().find((e) => e.type === "tool_call" && e.payload.tool === "write")
    expect(write.payload.produced_files).toEqual([
      { path: target, hash: expect.stringMatching(/^sha256:[0-9a-f]{64}$/) },
    ])
    expect(write.component.kind).toBe("skill")
    const other = logLines().find((e) => e.type === "tool_call" && e.payload.tool === "skill")
    expect(other.payload.produced_files).toBeUndefined()
  })
})
