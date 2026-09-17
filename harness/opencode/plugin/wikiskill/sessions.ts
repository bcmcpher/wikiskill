/**
 * Per-session state: identity, the pre-activation ring buffer, and the delegation tree.
 *
 * The watch list gates persistence. A session buffers what it sees but writes nothing until a
 * watched component activates; then the buffer flushes and the session logs from there on. A
 * session that never touches a watched component writes nothing at all.
 *
 * Buffered entries are factories rather than finished events, because which collection an event
 * belongs to is only known once something activates. Each factory captured the wall-clock time of
 * the event it describes, so a flushed event carries when it happened, not when it was flushed.
 */

import type { CollectionConfig, ComponentRef, Identity, RawEvent } from "./types"

/**
 * A buffered event, built once the collection it belongs to — and its bounds — are known.
 *
 * Returning null means "nothing to record after all", which is how a still-streaming part is held
 * without writing a placeholder.
 */
export type EventFactory = (config: CollectionConfig) => RawEvent | null

export interface SessionState {
  id: string
  parentId: string | null
  rootId: string
  provider: string
  model: string
  harnessVersion: string
  directory: string | null
  title: string | null
  origin: "live" | "eval"
  component: ComponentRef | null
  /** Collections this session is being logged for. Empty until a watched component activates. */
  logging: Set<string>
  buffer: EventFactory[]
  startedAt: number
  /** When this session was last touched, which is what decides whether it is stale. */
  lastSeenAt: number
  /** Whether a session_end has already been recorded for the current idle period. */
  idle: boolean
}

const UNKNOWN = "unknown"

/** How many message ids to remember a role for, across all sessions. */
const MESSAGE_ROLE_LIMIT = 2_000

export class SessionRegistry {
  private readonly sessions = new Map<string, SessionState>()
  private readonly messageRoles = new Map<string, string>()

  constructor(
    private bufferSize: number = 200,
    private readonly origin: "live" | "eval" = "live",
  ) {}

  /** The ring size follows the manifest, which can change while a session is open. */
  setBufferSize(size: number): void {
    if (size > 0) this.bufferSize = size
  }

  get size(): number {
    return this.sessions.size
  }

  ensure(id: string): SessionState {
    let state = this.sessions.get(id)
    if (!state) {
      state = {
        id,
        parentId: null,
        rootId: id,
        provider: UNKNOWN,
        model: UNKNOWN,
        harnessVersion: UNKNOWN,
        directory: null,
        title: null,
        origin: this.origin,
        component: null,
        logging: new Set(),
        buffer: [],
        startedAt: Date.now(),
        lastSeenAt: Date.now(),
        idle: false,
      }
      this.sessions.set(id, state)
    }
    // Any access is activity: pruning goes by when a session was last touched, not when it began,
    // so a long conversation is never dropped mid-flight.
    state.lastSeenAt = Date.now()
    return state
  }

  peek(id: string): SessionState | undefined {
    return this.sessions.get(id)
  }

  /**
   * Record a session's parentage.
   *
   * Parentage only; it deliberately does not start logging the child. A child of a logged session
   * must be *activated* for each inherited collection so that whatever it buffered before the link
   * is flushed — see `inherited`. Granting `logging` here instead would silently discard the child's
   * history, which for a subagent is its whole trajectory.
   */
  link(id: string, parentId: string | null | undefined): SessionState {
    const state = this.ensure(id)
    if (!parentId) return state
    state.parentId = parentId
    const parent = this.sessions.get(parentId)
    state.rootId = parent ? parent.rootId : parentId
    if (parent) {
      state.provider = state.provider === UNKNOWN ? parent.provider : state.provider
      state.model = state.model === UNKNOWN ? parent.model : state.model
      state.harnessVersion =
        state.harnessVersion === UNKNOWN ? parent.harnessVersion : state.harnessVersion
      state.origin = parent.origin
    }
    return state
  }

  /**
   * Collections an ancestor is logging that this session has not started logging yet.
   *
   * The caller activates the session for each one, which flushes what the session buffered before
   * the relationship was known. A `task` call is only recognised as an activation once it has
   * *finished*, so a child session routinely accumulates its entire trajectory before anyone knows
   * it should be logged.
   */
  inherited(id: string): string[] {
    const state = this.sessions.get(id)
    if (!state) return []
    const names = new Set<string>()
    const seen = new Set<string>([id])
    let parent = state.parentId ? this.sessions.get(state.parentId) : undefined
    while (parent && !seen.has(parent.id)) {
      seen.add(parent.id)
      for (const collection of parent.logging) {
        if (!state.logging.has(collection)) names.add(collection)
      }
      parent = parent.parentId ? this.sessions.get(parent.parentId) : undefined
    }
    return [...names]
  }

  /** Every session descended from `id`, so an activation can reach children already in flight. */
  descendants(id: string): string[] {
    const found: string[] = []
    const frontier = [id]
    const seen = new Set<string>([id])
    while (frontier.length > 0) {
      const current = frontier.pop()!
      for (const [childId, state] of this.sessions) {
        if (state.parentId !== current || seen.has(childId)) continue
        seen.add(childId)
        found.push(childId)
        frontier.push(childId)
      }
    }
    return found
  }

  noteIdentity(
    id: string,
    fields: { provider?: string; model?: string; harnessVersion?: string; directory?: string | null; title?: string | null },
  ): SessionState {
    const state = this.ensure(id)
    if (fields.provider) state.provider = fields.provider
    if (fields.model) state.model = fields.model
    if (fields.harnessVersion) state.harnessVersion = fields.harnessVersion
    if (fields.directory !== undefined) state.directory = fields.directory
    if (fields.title !== undefined) state.title = fields.title
    return state
  }

  identity(id: string, collection: string): Identity {
    const state = this.ensure(id)
    return {
      collection,
      harness_version: state.harnessVersion,
      provider: state.provider,
      model: state.model,
      session_id: state.id,
      root_session_id: state.rootId,
      parent_session_id: state.parentId,
      origin: state.origin,
      component: state.component,
    }
  }

  isLogging(id: string): boolean {
    return (this.sessions.get(id)?.logging.size ?? 0) > 0
  }

  collectionsFor(id: string): string[] {
    return [...(this.sessions.get(id)?.logging ?? [])]
  }

  /** Hold an event until the session earns persistence, dropping the oldest when the ring is full. */
  buffer(id: string, factory: EventFactory): void {
    const state = this.ensure(id)
    // Once the session is being logged, events are written rather than held.
    if (state.logging.size > 0) return
    state.buffer.push(factory)
    while (state.buffer.length > this.bufferSize) state.buffer.shift()
  }

  /**
   * Start logging this session for a collection and return the events that preceded the activation.
   *
   * Returns an empty list when the collection was already being logged, so a second activation in
   * the same session does not replay the buffer.
   */
  activate(id: string, config: CollectionConfig): RawEvent[] {
    const state = this.ensure(id)
    if (state.logging.has(config.collection)) return []
    const flushed = state.buffer
      .map((factory) => factory(config))
      .filter((event): event is RawEvent => event !== null)
    state.logging.add(config.collection)
    // The buffer is kept, not cleared: a second collection activating later in the same session
    // deserves the same history, and it is already bounded by the ring size.
    return flushed
  }

  setComponent(id: string, component: ComponentRef | null): void {
    this.ensure(id).component = component
  }

  /**
   * Mark a session idle, returning true only the first time.
   *
   * OpenCode emits `session.idle` after every turn, so without this a long conversation would
   * collect a `session_end` per turn.
   */
  markIdle(id: string): boolean {
    const state = this.ensure(id)
    if (state.idle) return false
    state.idle = true
    return true
  }

  /** Any further activity means the session is alive again and can end again later. */
  clearIdle(id: string): void {
    const state = this.sessions.get(id)
    if (state) state.idle = false
  }

  /**
   * Remember which message a part belongs to.
   *
   * OpenCode's text parts carry no role, and a session's parts include the user's own message, so
   * the only way to tell model output from user input is the role of the message the part belongs
   * to. The map is bounded: a session rarely has more than a few hundred messages, and the oldest
   * entry is dropped once it does.
   */
  noteMessageRole(messageId: string, role: string): void {
    if (!messageId) return
    this.messageRoles.set(messageId, role)
    while (this.messageRoles.size > MESSAGE_ROLE_LIMIT) {
      const oldest = this.messageRoles.keys().next().value
      if (oldest === undefined) break
      this.messageRoles.delete(oldest)
    }
  }

  isAssistantMessage(messageId: string | undefined): boolean {
    return messageId ? this.messageRoles.get(messageId) === "assistant" : false
  }

  forget(id: string): void {
    this.sessions.delete(id)
  }

  /**
   * Drop state for sessions untouched for `maxAgeMs`, so a long-lived server does not grow.
   *
   * Logged sessions are pruned on the same terms as any other. Exempting them would mean exactly
   * the sessions holding the most state are the ones never released, and a session silent for
   * `maxAgeMs` is over in every practical sense.
   */
  prune(maxAgeMs: number, now = Date.now()): number {
    let removed = 0
    for (const [id, state] of this.sessions) {
      if (now - state.lastSeenAt > maxAgeMs) {
        this.sessions.delete(id)
        removed += 1
      }
    }
    return removed
  }
}
