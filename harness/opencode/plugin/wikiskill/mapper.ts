/**
 * OpenCode event → raw record. Pure, so it can be contract-tested against recorded events without
 * a running harness, a model, or a writable log directory.
 *
 * Nothing here reads a file, the clock, or the environment: timestamps, source hashes and the
 * environment snapshot arrive as arguments. That is what makes the fixtures in ./test meaningful.
 */

import { bound, merge, redact, redactValue } from "./redact"
import { timestamp, ulid } from "./ulid"
import type {
  ComponentKind,
  ComponentRef,
  Identity,
  RawEvent,
  RawEventType,
  Redaction,
  WatchedComponent,
} from "./types"
import { SCHEMA_VERSION } from "./types"

export interface MapperOptions {
  outputLimitBytes: number
  envValues: string[]
  redactEnabled: boolean
  now: number
}

export const DEFAULT_OPTIONS: MapperOptions = {
  outputLimitBytes: 16 * 1024,
  envValues: [],
  redactEnabled: true,
  now: 0,
}

/** A detected activation, before its source file has been hashed. */
export interface ActivationHint {
  kind: ComponentKind
  name: string
  sourcePath: string | null
  trigger: "skill_tool" | "task_tool" | "command" | "read"
}

export function makeEvent(
  identity: Identity,
  type: RawEventType,
  payload: Record<string, unknown>,
  redactions: Redaction[] = [],
  now = Date.now(),
): RawEvent {
  const event: RawEvent = {
    schema_version: SCHEMA_VERSION,
    event_id: ulid(now),
    ts: timestamp(now),
    origin: identity.origin,
    harness: "opencode",
    harness_version: identity.harness_version,
    provider: identity.provider,
    model: identity.model,
    collection: identity.collection,
    session_id: identity.session_id,
    root_session_id: identity.root_session_id,
    parent_session_id: identity.parent_session_id,
    component: identity.component,
    type,
    payload,
  }
  if (redactions.length) event.redactions = redactions
  return event
}

// --------------------------------------------------------------------------- sessions

export interface SessionInfo {
  id: string
  parentID?: string
  directory?: string
  title?: string
  version?: string
}

export function mapSessionStart(
  info: SessionInfo,
  identity: Identity,
  now = Date.now(),
): RawEvent {
  return makeEvent(
    identity,
    "session_start",
    { cwd: info.directory ?? null, title: info.title ?? null, agent: null },
    [],
    now,
  )
}

export function mapSessionEnd(
  reason: string | null,
  identity: Identity,
  now = Date.now(),
): RawEvent {
  return makeEvent(identity, "session_end", { reason, duration_ms: null }, [], now)
}

// --------------------------------------------------------------------------- messages

// Token usage is taken from `step-finish` parts rather than from message totals: a multi-step
// turn emits one step-finish per step, and the message-level counts would double-count them.

export interface TextPartInfo {
  type: string
  text?: string
  messageID?: string
  synthetic?: boolean
  time?: { start?: number; end?: number }
}

/**
 * A completed assistant text part.
 *
 * Text parts carry no role of their own and a session's parts include the user's own message, so
 * the caller supplies `isAssistant` from the role of the message the part belongs to. Only parts
 * with an end time are logged, so a streaming part is recorded once rather than on every delta, and
 * synthetic parts are harness bookkeeping rather than model output.
 */
export function mapAssistantTurn(
  part: TextPartInfo,
  identity: Identity,
  options: MapperOptions,
  isAssistant: boolean,
  now = Date.now(),
): RawEvent | null {
  if (part.type !== "text" || part.synthetic || !isAssistant || !part.time?.end) return null
  const text = part.text ?? ""
  const { text: clean, redactions } = options.redactEnabled
    ? redact(text, options.envValues)
    : { text, redactions: [] as Redaction[] }
  const limited = bound(clean, options.outputLimitBytes)
  return makeEvent(
    identity,
    "assistant_turn",
    {
      text: limited.text,
      text_length: text.length,
      finish_reason: limited.truncated ? "truncated_by_logger" : null,
    },
    redactions,
    now,
  )
}

export interface StepFinishInfo {
  type: string
  reason?: string
  cost?: number
  tokens?: {
    input?: number
    output?: number
    reasoning?: number
    cache?: { read?: number; write?: number }
  }
}

export function mapStepUsage(
  part: StepFinishInfo,
  identity: Identity,
  now = Date.now(),
): RawEvent | null {
  if (part.type !== "step-finish" || !part.tokens) return null
  return makeEvent(
    identity,
    "step_usage",
    {
      tokens: {
        input: part.tokens.input ?? null,
        output: part.tokens.output ?? null,
        reasoning: part.tokens.reasoning ?? null,
        cache_read: part.tokens.cache?.read ?? null,
        cache_write: part.tokens.cache?.write ?? null,
      },
      cost: part.cost ?? null,
    },
    [],
    now,
  )
}

// --------------------------------------------------------------------------- tools

export interface ToolCallInfo {
  tool: string
  callID?: string
  args?: Record<string, unknown>
  output?: string
  metadata?: Record<string, unknown>
  error?: string
  durationMs?: number
}

export function mapToolCall(
  call: ToolCallInfo,
  identity: Identity,
  options: MapperOptions,
  now = Date.now(),
): RawEvent {
  const raw = call.output ?? ""
  const redactions: Redaction[] = []

  let output = raw
  if (options.redactEnabled) {
    const result = redact(raw, options.envValues)
    output = result.text
    redactions.push(...result.redactions)
  }
  const limited = bound(output, options.outputLimitBytes)

  let input: unknown = call.args ?? null
  if (options.redactEnabled && call.args) {
    const result = redactValue(call.args, options.envValues)
    input = result.value
    redactions.push(...result.redactions)
  }

  return makeEvent(
    identity,
    "tool_call",
    {
      tool: call.tool,
      call_id: call.callID ?? null,
      ok: !call.error,
      input: (input as Record<string, unknown> | null) ?? null,
      output: limited.text,
      output_length: raw.length,
      output_truncated: limited.truncated,
      output_hash: null,
      error: call.error ?? null,
      duration_ms: call.durationMs ?? null,
    },
    merge(redactions),
    now,
  )
}

export function mapError(
  message: string,
  where: string | null,
  identity: Identity,
  now = Date.now(),
): RawEvent {
  return makeEvent(identity, "error", { message, where, fatal: false }, [], now)
}

// --------------------------------------------------------------------------- detection

const SKILL_TOOLS = new Set(["skill", "skills"])
const TASK_TOOLS = new Set(["task", "agent"])
const READ_TOOLS = new Set(["read", "view", "cat"])

/**
 * Which watched component, if any, a tool call activated.
 *
 * `predicate` decides whether a candidate name is watched; the mapper does not own the watch list.
 * `metadata.dir` is where OpenCode reports a loaded skill's directory, and is the source of the path
 * whose content identifies the version that ran.
 */
export function detectActivation(
  call: ToolCallInfo,
  watchedName: (kind: ComponentKind, name: string) => boolean,
  watchedPath: (path: string) => WatchedComponent | null,
): ActivationHint | null {
  const tool = call.tool?.toLowerCase() ?? ""
  const args = call.args ?? {}
  const metadata = call.metadata ?? {}

  if (SKILL_TOOLS.has(tool)) {
    const name = stringField(args, "name", "skill", "skill_name")
    if (name && watchedName("skill", name)) {
      const dir = stringField(metadata, "dir", "directory", "path")
      return {
        kind: "skill",
        name,
        sourcePath: dir ? joinSkillMain(dir) : null,
        trigger: "skill_tool",
      }
    }
    return null
  }

  if (TASK_TOOLS.has(tool)) {
    const name = stringField(args, "subagent_type", "subagentType", "agent", "name")
    if (name && watchedName("agent", name)) {
      const path = stringField(metadata, "path", "agentPath", "file")
      return { kind: "agent", name, sourcePath: path ?? null, trigger: "task_tool" }
    }
    return null
  }

  if (READ_TOOLS.has(tool)) {
    // A model that reads a skill's text directly has activated it in every way that matters.
    const candidate = stringField(args, "filePath", "file_path", "path", "file")
    const match = candidate ? watchedPath(candidate) : null
    if (match) {
      return { kind: match.kind, name: match.name, sourcePath: match.path, trigger: "read" }
    }
  }
  return null
}

export function detectCommandActivation(
  command: string,
  watchedName: (kind: ComponentKind, name: string) => boolean,
): ActivationHint | null {
  const name = command.replace(/^\//, "")
  if (!name || !watchedName("command", name)) return null
  return { kind: "command", name, sourcePath: null, trigger: "command" }
}

export function mapActivation(
  hint: ActivationHint,
  sourceHash: string | null,
  identity: Identity,
  inputSummary: string | null,
  now = Date.now(),
): RawEvent {
  const component: ComponentRef = {
    kind: hint.kind,
    name: hint.name,
    source_hash: sourceHash,
  }
  return makeEvent(
    { ...identity, component },
    "component_activated",
    {
      trigger: hint.trigger,
      source_path: hint.sourcePath,
      input_summary: inputSummary,
    },
    [],
    now,
  )
}

/** The child session a `task` call spawned, if the harness reported one. */
export function mapDelegation(
  call: ToolCallInfo,
  identity: Identity,
  now = Date.now(),
): RawEvent | null {
  const tool = call.tool?.toLowerCase() ?? ""
  if (!TASK_TOOLS.has(tool)) return null
  const args = call.args ?? {}
  const metadata = call.metadata ?? {}
  const subagent = stringField(args, "subagent_type", "subagentType", "agent", "name")
  if (!subagent) return null
  const child = stringField(metadata, "sessionID", "sessionId", "session_id", "childSessionID")
  return makeEvent(
    identity,
    "delegation",
    {
      subagent_type: subagent,
      child_session_id: child ?? null,
      description: stringField(args, "description", "prompt")?.slice(0, 500) ?? null,
    },
    [],
    now,
  )
}

// --------------------------------------------------------------------------- helpers

export function stringField(
  source: Record<string, unknown>,
  ...names: string[]
): string | undefined {
  for (const name of names) {
    const value = source?.[name]
    if (typeof value === "string" && value.length) return value
  }
  return undefined
}

function joinSkillMain(dir: string): string {
  return dir.endsWith("SKILL.md") ? dir : `${dir.replace(/\/+$/, "")}/SKILL.md`
}
