/**
 * Outcomes for tool calls, taken from tool parts rather than from the `tool.execute.after` hook.
 *
 * The hook's payload is `{title, output, metadata}` — it carries neither timing nor error, and it
 * does not fire at all when a tool fails. OpenCode's tool *parts* carry both: a terminal part is
 * either `status: "completed"` with `time.start`/`time.end`, or `status: "error"` with `error` and
 * the same timing. This module remembers those outcomes by call id so the hook can record a real
 * duration, and so a failed call is recorded as failed instead of being dropped.
 */

export interface ToolPartState {
  status?: string
  input?: Record<string, unknown>
  output?: string
  error?: string
  metadata?: Record<string, unknown>
  time?: { start?: number; end?: number }
}

export interface ToolPartInfo {
  type: string
  callID?: string
  tool?: string
  sessionID?: string
  state?: ToolPartState
}

export interface ToolOutcome {
  ok: boolean
  error: string | null
  durationMs: number | null
}

/** The terminal outcome a tool part describes, or null while the call is still running. */
export function outcomeOf(part: ToolPartInfo): ToolOutcome | null {
  const state = part.state
  if (!state) return null
  const start = state.time?.start
  const end = state.time?.end
  const durationMs =
    typeof start === "number" && typeof end === "number" && end >= start ? end - start : null
  if (state.status === "error") return { ok: false, error: state.error ?? "tool error", durationMs }
  if (state.status === "completed") return { ok: true, error: null, durationMs }
  return null
}

export class ToolCallStates {
  private readonly outcomes = new Map<string, ToolOutcome>()
  private readonly recorded = new Set<string>()

  /** Bounded so a long-lived server does not accumulate one entry per tool call it ever saw. */
  constructor(private readonly limit: number = 500) {}

  note(callId: string | undefined, outcome: ToolOutcome): void {
    if (!callId) return
    this.outcomes.set(callId, outcome)
    this.trim(this.outcomes)
  }

  outcome(callId: string | undefined): ToolOutcome | null {
    return callId ? this.outcomes.get(callId) ?? null : null
  }

  /**
   * Claim a call id for recording, returning true only the first time.
   *
   * A failed call is written from its error part and a successful one from the hook; claiming keeps
   * a call from being written twice if both ever describe the same one.
   */
  claim(callId: string | undefined): boolean {
    if (!callId) return true
    if (this.recorded.has(callId)) return false
    this.recorded.add(callId)
    this.trim(this.recorded)
    return true
  }

  private trim(store: Map<string, ToolOutcome> | Set<string>): void {
    while (store.size > this.limit) {
      const oldest = store.keys().next().value
      if (oldest === undefined) break
      store.delete(oldest as string)
    }
  }
}
