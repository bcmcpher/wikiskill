/**
 * wikiskill's OpenCode logger.
 *
 * Passive, opt-in, model-free. It watches the event bus and completed tool calls, and appends a
 * harness-neutral raw record for sessions that touch a watched component. It makes no model calls,
 * never blocks, and every hook body is wrapped so a logging failure cannot alter a session.
 *
 * Configuration comes from ${XDG_CONFIG_HOME:-~/.config}/wikiskill/runtime.json, published by
 * `wikiskill collection check --sync` or `wikiskill install`. With no configuration, or none that
 * watches anything in this session, the plugin does nothing at all.
 */

import { ConfigSource } from "./wikiskill/config"
import { sourceHash } from "./wikiskill/hash"
import {
  DEFAULT_OPTIONS,
  detectActivation,
  detectCommandActivation,
  isDelegation,
  mapActivation,
  mapAssistantTurn,
  mapDelegation,
  mapError,
  mapSessionEnd,
  mapSessionStart,
  mapStepUsage,
  mapToolCall,
  stringField,
  type ActivationHint,
  type MapperOptions,
  type TextPartInfo,
  type ToolCallInfo,
} from "./wikiskill/mapper"
import { watchedComponentFor, watches } from "./wikiskill/match"
import { envSecrets } from "./wikiskill/redact"
import { SessionRegistry, type EventFactory } from "./wikiskill/sessions"
import { ToolCallStates, outcomeOf, type ToolPartInfo } from "./wikiskill/toolstate"
import { appendEvent, logError } from "./wikiskill/writer"
import type { CollectionConfig, ComponentKind, RawEvent } from "./wikiskill/types"

/** Sessions idle longer than this are forgotten, so a long-lived server does not accumulate state. */
const SESSION_TTL_MS = 6 * 60 * 60 * 1000

export const wikiskillLogger = async () => {
  const config = new ConfigSource()
  const origin = process.env.WIKISKILL_ORIGIN === "eval" ? "eval" : "live"
  const registry = new SessionRegistry(200, origin)
  const toolStates = new ToolCallStates()
  const envValues = envSecrets(process.env)
  let lastPrune = Date.now()

  const collections = (): CollectionConfig[] => config.current()

  const optionsFor = (collection: CollectionConfig): MapperOptions => ({
    ...DEFAULT_OPTIONS,
    outputLimitBytes: collection.output_limit_bytes,
    envValues,
    redactEnabled: collection.redact,
  })

  const errorLog = (): string => collections()[0]?.error_log ?? ""

  const write = (collection: CollectionConfig, event: RawEvent | null): void => {
    if (!event) return
    try {
      appendEvent(collection.raw_dir, event)
    } catch (error) {
      logError(collection.error_log, "append", error)
    }
  }

  /** Write, or hold, one event. The factory runs once per collection that is logging. */
  const emit = (sessionId: string, factory: EventFactory): void => {
    const names = registry.collectionsFor(sessionId)
    if (names.length === 0) {
      registry.buffer(sessionId, factory)
      return
    }
    for (const collection of collections()) {
      if (names.includes(collection.collection)) write(collection, factory(collection))
    }
  }

  const configFor = (name: string): CollectionConfig | undefined =>
    collections().find((collection) => collection.collection === name)

  /**
   * Start logging a session for the collections an ancestor is already logging.
   *
   * Flushing is the whole point: a child session is usually only known to belong to a logged
   * trajectory once its `task` call has finished, by which time everything it did is sitting in its
   * own buffer. Adding it to `logging` without flushing would write the subagent's remaining events
   * and silently drop its actual work.
   */
  const adopt = (sessionId: string): void => {
    for (const name of registry.inherited(sessionId)) {
      const collection = configFor(name)
      if (!collection) continue
      for (const event of registry.activate(sessionId, collection)) write(collection, event)
    }
  }

  /**
   * Record a terminal tool part.
   *
   * Whichever of the part and the `tool.execute.after` hook describes a call first is the one that
   * writes it, which is why both claim the call id. The part is the only source of a duration, and
   * the only source at all for a failed call — the hook does not fire when a tool throws.
   */
  const recordToolPart = (part: ToolPartInfo, now: number): void => {
    const sessionId = part.sessionID
    const outcome = outcomeOf(part)
    if (!sessionId || !outcome) return
    toolStates.note(part.callID, outcome)
    if (!toolStates.claim(part.callID)) return
    const state = part.state ?? {}
    const call: ToolCallInfo = {
      tool: String(part.tool ?? ""),
      callID: part.callID,
      args: state.input ?? {},
      output: typeof state.output === "string" ? state.output : "",
      metadata: state.metadata ?? {},
      error: outcome.error ?? undefined,
      durationMs: outcome.durationMs ?? undefined,
    }
    emit(sessionId, (collection) =>
      mapToolCall(
        call,
        registry.identity(sessionId, collection.collection),
        optionsFor(collection),
        now,
      ),
    )
  }

  /**
   * Begin logging a session for every collection that watches the activated component.
   *
   * The buffered events that preceded the activation are written first, then the activation itself,
   * so the log reads in the order things happened.
   */
  const startLogging = (
    sessionId: string,
    hint: ActivationHint,
    inputSummary: string | null,
    now: number,
  ): void => {
    const hash = sourceHash(hint.sourcePath)
    for (const collection of collections()) {
      if (!watches(collection, hint.kind, hint.name)) continue
      for (const event of registry.activate(sessionId, collection)) write(collection, event)
      const identity = registry.identity(sessionId, collection.collection)
      write(collection, mapActivation(hint, hash, identity, inputSummary, now))
    }
    registry.setComponent(sessionId, { kind: hint.kind, name: hint.name, source_hash: hash })
    // Children spawned before the activation was recognised are part of this trajectory too.
    for (const child of registry.descendants(sessionId)) adopt(child)
  }

  /** A component counts as watched if any configured collection watches it. */
  const anyWatchesName = (kind: ComponentKind, name: string): boolean =>
    collections().some((collection) => watches(collection, kind, name))

  const anyWatchedPath = (path: string) => {
    for (const collection of collections()) {
      const found = watchedComponentFor(collection, path)
      if (found) return found
    }
    return null
  }

  const ready = (now: number): CollectionConfig[] => {
    const loaded = collections()
    if (loaded.length === 0) return loaded
    if (now - lastPrune >= SESSION_TTL_MS) {
      lastPrune = now
      registry.prune(SESSION_TTL_MS, now)
    }
    registry.setBufferSize(Math.max(...loaded.map((c) => c.buffer_size)))
    return loaded
  }

  return {
    /** Every bus event: session lifecycle, assistant output, step usage, and session errors. */
    event: async ({ event }: { event: any }) => {
      try {
        const now = Date.now()
        if (ready(now).length === 0) return
        const properties = event?.properties ?? {}

        switch (event?.type) {
          case "session.created":
          case "session.updated": {
            const info = properties.info
            if (!info?.id) return
            registry.link(info.id, info.parentID)
            // A child created while its parent is already logging starts logging immediately.
            adopt(info.id)
            registry.noteIdentity(info.id, {
              harnessVersion: info.version,
              directory: info.directory ?? null,
              title: info.title ?? null,
              // `session.updated` carries the session's model before any message does.
              provider: info.model?.providerID,
              model: info.model?.id ?? info.model?.modelID,
            })
            if (event.type === "session.created") {
              emit(info.id, (collection) =>
                mapSessionStart(info, registry.identity(info.id, collection.collection), now),
              )
            }
            return
          }

          case "message.updated": {
            const info = properties.info
            if (!info?.sessionID) return
            registry.clearIdle(info.sessionID)
            registry.noteMessageRole(info.id, info.role)
            if (info.role === "assistant") {
              registry.noteIdentity(info.sessionID, {
                provider: info.providerID,
                model: info.modelID,
              })
            } else if (info.role === "user" && info.model) {
              registry.noteIdentity(info.sessionID, {
                provider: info.model.providerID,
                model: info.model.modelID,
              })
            }
            return
          }

          case "message.part.updated": {
            const part = properties.part
            if (!part?.sessionID) return
            registry.clearIdle(part.sessionID)
            // Usage comes from step-finish parts rather than message totals, which would
            // double-count a multi-step turn.
            if (part.type === "text") {
              // Parts carry no role; the user's own message is a text part too.
              const isAssistant = registry.isAssistantMessage(part.messageID)
              // Only the final update of a streamed part is recorded. Buffering the deltas as well
              // would push hundreds of factories that all evaluate to null through the ring and
              // evict the history the buffer exists to keep.
              if (!isAssistant || part.synthetic || !part.time?.end) return
              // Snapshot the fields used, rather than closing over a part the harness still owns.
              const text: TextPartInfo = {
                type: "text",
                text: typeof part.text === "string" ? part.text : "",
                messageID: part.messageID,
                synthetic: false,
                time: { start: part.time?.start, end: part.time.end },
              }
              emit(part.sessionID, (collection) =>
                mapAssistantTurn(
                  text,
                  registry.identity(part.sessionID, collection.collection),
                  optionsFor(collection),
                  true,
                  now,
                ),
              )
            } else if (part.type === "tool") {
              // Tool parts are where an outcome lives: the `tool.execute.after` hook reports neither
              // timing nor failure, and does not fire at all for a failed call.
              recordToolPart(part as ToolPartInfo, now)
            } else if (part.type === "step-finish") {
              emit(part.sessionID, (collection) =>
                mapStepUsage(part, registry.identity(part.sessionID, collection.collection), now),
              )
            }
            return
          }

          case "session.idle": {
            const sessionId = properties.sessionID
            if (!sessionId || !registry.markIdle(sessionId)) return
            emit(sessionId, (collection) =>
              mapSessionEnd("idle", registry.identity(sessionId, collection.collection), now),
            )
            return
          }

          case "session.deleted": {
            const info = properties.info
            if (!info?.id) return
            emit(info.id, (collection) =>
              mapSessionEnd("deleted", registry.identity(info.id, collection.collection), now),
            )
            registry.forget(info.id)
            return
          }

          case "session.error": {
            const sessionId = properties.sessionID
            if (!sessionId) return
            const message =
              stringField(properties.error?.data ?? {}, "message") ??
              properties.error?.name ??
              "session error"
            emit(sessionId, (collection) =>
              mapError(
                message,
                "session",
                registry.identity(sessionId, collection.collection),
                now,
              ),
            )
            return
          }
        }
      } catch (error) {
        logError(errorLog(), "event", error)
      }
    },

    /** Model identity arrives here before the first assistant message does. */
    "chat.message": async (input: any) => {
      try {
        const now = Date.now()
        if (!input?.sessionID || ready(now).length === 0) return
        registry.noteIdentity(input.sessionID, {
          provider: input.model?.providerID,
          model: input.model?.modelID,
        })
        registry.clearIdle(input.sessionID)
      } catch (error) {
        logError(errorLog(), "chat.message", error)
      }
    },

    /** A slash command can itself be a watched component. */
    "command.execute.before": async (input: any) => {
      try {
        const now = Date.now()
        if (!input?.sessionID || ready(now).length === 0) return
        const hint = detectCommandActivation(String(input.command ?? ""), anyWatchesName)
        if (hint) startLogging(input.sessionID, hint, input.arguments || null, now)
      } catch (error) {
        logError(errorLog(), "command.execute.before", error)
      }
    },

    /**
     * Completed tool calls: the activation signal, the delegation signal, and the trajectory.
     *
     * A `skill` call names the skill it loaded; a `task` call names the subagent and the child
     * session it spawned; a `read` of a watched component's source file counts as an activation,
     * because a model that read the text has used the skill whether or not it invoked it.
     */
    "tool.execute.after": async (input: any, output: any) => {
      try {
        const now = Date.now()
        const sessionId = input?.sessionID
        if (!sessionId || ready(now).length === 0) return
        registry.clearIdle(sessionId)

        // The hook's own payload carries no timing and no error; a tool part may already have
        // reported both for this call.
        const outcome = toolStates.outcome(input.callID)
        const call: ToolCallInfo = {
          tool: String(input.tool ?? ""),
          callID: input.callID,
          args: input.args ?? {},
          output: typeof output?.output === "string" ? output.output : "",
          metadata: output?.metadata ?? {},
          error: outcome?.error ?? undefined,
          durationMs: outcome?.durationMs ?? undefined,
        }

        const hint = detectActivation(call, anyWatchesName, anyWatchedPath)
        if (hint) {
          const summary =
            stringField(call.args ?? {}, "description", "prompt", "query")?.slice(0, 500) ?? null
          startLogging(sessionId, hint, summary, now)
        }

        // A child session of a logged session is logged too, into its root's file — and it is
        // adopted rather than merely linked, so what it did before this call returned is flushed.
        const childId = stringField(call.metadata ?? {}, "sessionID", "sessionId", "session_id")
        if (childId && childId !== sessionId) {
          registry.link(childId, sessionId)
          adopt(childId)
        }

        // A delegation is recorded before the `task` call that produced it, so the chain reads in
        // order; every tool call, delegating or not, is then recorded as itself.
        if (isDelegation(call)) {
          emit(sessionId, (collection) =>
            mapDelegation(call, registry.identity(sessionId, collection.collection), now),
          )
        }
        if (toolStates.claim(call.callID)) {
          emit(sessionId, (collection) =>
            mapToolCall(
              call,
              registry.identity(sessionId, collection.collection),
              optionsFor(collection),
              now,
            ),
          )
        }
      } catch (error) {
        logError(errorLog(), "tool.execute.after", error)
      }
    },
  }
}

export default wikiskillLogger
