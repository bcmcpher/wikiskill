/**
 * Contract tests for the pure mapper, run against payloads recorded from OpenCode 1.18.31.
 *
 * These are the tests that catch an event-shape drift between OpenCode versions: if a field the
 * mapper reads moves or is renamed, a recorded payload stops producing the record it used to.
 */

import { describe, expect, test } from "bun:test"

import {
  DEFAULT_OPTIONS,
  detectActivation,
  detectCommandActivation,
  mapActivation,
  mapAssistantTurn,
  mapDelegation,
  mapError,
  mapSessionEnd,
  mapSessionStart,
  mapStepUsage,
  mapToolCall,
  type MapperOptions,
} from "../wikiskill/mapper"
import { watchedComponentFor, watches } from "../wikiskill/match"
import type { ComponentKind } from "../wikiskill/types"

import {
  MIN_OPENCODE_VERSION,
  NOW,
  RECORDED_VERSION,
  WATCHED_SKILL_PATH,
  collection,
  compareVersions,
  events,
  identity,
  tools,
} from "./helpers"

const config = collection()
const options: MapperOptions = { ...DEFAULT_OPTIONS, envValues: [], redactEnabled: true }
const watchedName = (kind: ComponentKind, name: string) => watches(config, kind, name)
const watchedPath = (path: string) => watchedComponentFor(config, path)

function call(fixture: any) {
  return {
    tool: fixture.input.tool,
    callID: fixture.input.callID,
    args: fixture.input.args,
    output: fixture.output.output,
    metadata: fixture.output.metadata,
  }
}

describe("envelope", () => {
  test("every event carries harness, model and session identity", () => {
    const event = mapSessionStart(
      events["session.created"].properties.info,
      identity(),
      NOW,
    )
    expect(event.schema_version).toBe(1)
    expect(event.harness).toBe("opencode")
    expect(event.harness_version).toBe(RECORDED_VERSION)
    expect(event.provider).toBe("ollama")
    expect(event.model).toBe("qwen3:1.7b")
    expect(event.session_id).toBe("ses_f4f1a0774ffepL3wqqJ5f72ctQ")
    expect(event.root_session_id).toBe(event.session_id)
    expect(event.origin).toBe("live")
  })

  test("event ids are ULIDs and sort by time", () => {
    const early = mapSessionStart({ id: "s" }, identity(), 1_700_000_000_000)
    const late = mapSessionStart({ id: "s" }, identity(), 1_800_000_000_000)
    expect(early.event_id).toMatch(/^[0-7][0-9ABCDEFGHJKMNPQRSTVWXYZ]{25}$/)
    expect(early.event_id < late.event_id).toBe(true)
  })

  test("timestamps are RFC 3339 with milliseconds in UTC", () => {
    const event = mapSessionStart({ id: "s" }, identity(), NOW)
    expect(event.ts).toMatch(/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$/)
  })
})

describe("recorded session events", () => {
  test("session.created becomes session_start with the real cwd and title", () => {
    const info = events["session.created"].properties.info
    const event = mapSessionStart(info, identity(), NOW)
    expect(event.type).toBe("session_start")
    expect(event.payload.cwd).toBe("/tmp/wikiskill-capture")
    expect(event.payload.title).toBe(info.title)
  })

  test("the fixtures come from a version this plugin targets", () => {
    // The harness is updated regularly; re-capturing from a newer release is expected and fine,
    // going backwards below the floor is not.
    expect(compareVersions(RECORDED_VERSION, MIN_OPENCODE_VERSION)).toBeGreaterThanOrEqual(0)
  })

  test("the recorded session carries the harness version the plugin stamps", () => {
    expect(events["session.created"].properties.info.version).toBe(RECORDED_VERSION)
  })

  test("session.updated exposes the session's model", () => {
    const info = events["session.updated"].properties.info
    expect(info.model.providerID).toBe("ollama")
    expect(info.model.id).toBeTruthy()
  })

  test("a recorded assistant message exposes provider, model and completion", () => {
    const info = events["message.updated:assistant"].properties.info
    expect(info.role).toBe("assistant")
    expect(info.providerID).toBe("ollama")
    expect(info.modelID).toBeTruthy()
    expect(info.time.completed).toBeGreaterThan(0)
  })

  test("session.error carries its message where mapError looks for it", () => {
    const properties = events["session.error"].properties
    const event = mapError(properties.error.data.message, "session", identity(), NOW)
    expect(event.type).toBe("error")
    expect(event.payload.message).toContain("does not support tools")
  })
})

describe("assistant turns", () => {
  const part = {
    type: "text",
    text: "done",
    messageID: "msg_1",
    time: { start: NOW - 100, end: NOW },
  }

  test("a completed assistant part is recorded once", () => {
    const event = mapAssistantTurn(part, identity(), options, true, NOW)
    expect(event?.type).toBe("assistant_turn")
    expect(event?.payload.text_length).toBe(4)
  })

  test("a user's text part is not an assistant turn", () => {
    expect(mapAssistantTurn(part, identity(), options, false, NOW)).toBeNull()
  })

  test("a recorded user text part has no end time and is skipped", () => {
    const recorded = events["message.part.updated"].properties.part
    expect(mapAssistantTurn(recorded, identity(), options, false, NOW)).toBeNull()
  })

  test("a still-streaming part is held rather than logged per delta", () => {
    expect(
      mapAssistantTurn({ ...part, time: { start: NOW } }, identity(), options, true, NOW),
    ).toBeNull()
  })

  test("a synthetic part is harness bookkeeping, not model output", () => {
    expect(mapAssistantTurn({ ...part, synthetic: true }, identity(), options, true, NOW)).toBeNull()
  })
})

describe("usage", () => {
  test("a step-finish part becomes step_usage with cache counts flattened", () => {
    const event = mapStepUsage(
      {
        type: "step-finish",
        reason: "stop",
        cost: 0,
        tokens: { input: 4871, output: 233, reasoning: 0, cache: { read: 12, write: 3 } },
      },
      identity(),
      NOW,
    )
    expect(event?.payload.tokens).toEqual({
      input: 4871,
      output: 233,
      reasoning: 0,
      cache_read: 12,
      cache_write: 3,
    })
  })

  test("a part that is not a step-finish yields nothing", () => {
    expect(mapStepUsage({ type: "text" }, identity(), NOW)).toBeNull()
  })
})

describe("activation detection", () => {
  test("a skill call names the skill and its source file", () => {
    const hint = detectActivation(call(tools.skill), watchedName, watchedPath)
    expect(hint).toEqual({
      kind: "skill",
      name: "preregister",
      sourcePath: WATCHED_SKILL_PATH,
      trigger: "skill_tool",
    })
  })

  test("an unwatched skill does not start logging", () => {
    expect(detectActivation(call(tools.unwatched), watchedName, watchedPath)).toBeNull()
  })

  test("a task call names the subagent", () => {
    const hint = detectActivation(call(tools.task), watchedName, watchedPath)
    expect(hint?.kind).toBe("agent")
    expect(hint?.name).toBe("datalad-doer")
    expect(hint?.trigger).toBe("task_tool")
  })

  test("reading a watched skill's file counts as an activation", () => {
    const hint = detectActivation(call(tools.read_watched), watchedName, watchedPath)
    expect(hint?.trigger).toBe("read")
    expect(hint?.name).toBe("govern/preregister")
    expect(hint?.sourcePath).toBe(WATCHED_SKILL_PATH)
  })

  test("reading an unrelated file does not", () => {
    const unrelated = { ...call(tools.read_watched), args: { filePath: "/etc/hosts" } }
    expect(detectActivation(unrelated, watchedName, watchedPath)).toBeNull()
  })

  test("an ordinary tool call is not an activation", () => {
    expect(detectActivation(call(tools.bash_with_secret), watchedName, watchedPath)).toBeNull()
  })

  test("a watched slash command activates", () => {
    expect(detectCommandActivation("/wikiskill-trace", watchedName)?.kind).toBe("command")
    expect(detectCommandActivation("/something-else", watchedName)).toBeNull()
  })

  test("an activation records the component version that ran", () => {
    const hint = detectActivation(call(tools.skill), watchedName, watchedPath)!
    const event = mapActivation(hint, "sha256:" + "a".repeat(64), identity(), "freeze it", NOW)
    expect(event.type).toBe("component_activated")
    expect(event.component).toEqual({
      kind: "skill",
      name: "preregister",
      source_hash: "sha256:" + "a".repeat(64),
    })
    expect(event.payload.trigger).toBe("skill_tool")
  })

  test("an unreadable component file still produces an activation", () => {
    const hint = detectActivation(call(tools.skill), watchedName, watchedPath)!
    expect(mapActivation(hint, null, identity(), null, NOW).component?.source_hash).toBeNull()
  })
})

describe("delegation", () => {
  test("a task call records the child session it spawned", () => {
    const event = mapDelegation(call(tools.task), identity(), NOW)
    expect(event?.type).toBe("delegation")
    expect(event?.payload.subagent_type).toBe("datalad-doer")
    expect(event?.payload.child_session_id).toBe("ses_9c21bb3310ceqT8mzzR4d91xKW")
  })

  test("a non-task call is not a delegation", () => {
    expect(mapDelegation(call(tools.bash_with_secret), identity(), NOW)).toBeNull()
  })

  test("a child's events are attributed to its root and parent", () => {
    const child = identity({
      session_id: "ses_child",
      root_session_id: "ses_root",
      parent_session_id: "ses_root",
    })
    const event = mapToolCall(call(tools.bash_with_secret), child, options, NOW)
    expect(event.root_session_id).toBe("ses_root")
    expect(event.parent_session_id).toBe("ses_root")
  })
})

describe("tool calls", () => {
  test("a successful call keeps its input and output", () => {
    const event = mapToolCall(call(tools.read_watched), identity(), options, NOW)
    expect(event.type).toBe("tool_call")
    expect(event.payload.tool).toBe("read")
    expect(event.payload.ok).toBe(true)
    expect(event.payload.output_truncated).toBe(false)
  })

  test("a failed call records the error and stays ok: false", () => {
    const event = mapToolCall(
      { ...call(tools.read_watched), error: "ENOENT" },
      identity(),
      options,
      NOW,
    )
    expect(event.payload.ok).toBe(false)
    expect(event.payload.error).toBe("ENOENT")
  })

  test("a secret in a tool output is replaced and counted", () => {
    const event = mapToolCall(call(tools.bash_with_secret), identity(), options, NOW)
    expect(event.payload.output).not.toContain("sk-ant-api03")
    expect(event.payload.output).toContain("[REDACTED:")
    expect(event.redactions?.length).toBeGreaterThan(0)
  })

  test("a secret in a tool's arguments is redacted too", () => {
    const event = mapToolCall(call(tools.bash_with_secret), identity(), options, NOW)
    expect(JSON.stringify(event.payload.input)).not.toContain("sk-ant-api03")
  })

  test("output above the bound is truncated but its true length is kept", () => {
    const long = "x".repeat(40_000)
    const event = mapToolCall(
      { tool: "bash", output: long, args: {} },
      identity(),
      { ...options, outputLimitBytes: 1024 },
      NOW,
    )
    expect(event.payload.output_truncated).toBe(true)
    expect(event.payload.output_length).toBe(40_000)
    expect((event.payload.output as string).length).toBeLessThanOrEqual(1024)
  })

  test("redaction can be turned off for a collection", () => {
    const event = mapToolCall(
      call(tools.bash_with_secret),
      identity(),
      { ...options, redactEnabled: false },
      NOW,
    )
    expect(event.payload.output).toContain("sk-ant-api03")
    expect(event.redactions).toBeUndefined()
  })
})

describe("session end", () => {
  test("an idle session ends with a reason", () => {
    const event = mapSessionEnd("idle", identity(), NOW)
    expect(event.type).toBe("session_end")
    expect(event.payload.reason).toBe("idle")
  })
})
