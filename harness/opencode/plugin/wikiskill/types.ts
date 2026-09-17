/**
 * The raw event shape, mirroring schemas/raw-event.schema.json.
 *
 * Kept as plain types rather than a validator: validation is Python's job, and the logger must not
 * spend a session's time on it.
 */

export const SCHEMA_VERSION = 1

export type ComponentKind = "skill" | "agent" | "command"

export type RawEventType =
  | "session_start"
  | "component_activated"
  | "delegation"
  | "tool_call"
  | "assistant_turn"
  | "step_usage"
  | "error"
  | "session_end"

export type RedactionKind =
  | "env_value"
  | "api_key"
  | "token"
  | "private_key"
  | "password"
  | "url_credentials"

export interface Redaction {
  kind: RedactionKind
  count: number
  field?: string
}

export interface ComponentRef {
  kind: ComponentKind
  name: string
  source_hash: string | null
}

export interface RawEvent {
  schema_version: number
  event_id: string
  ts: string
  origin: "live" | "eval"
  harness: "opencode" | "claude-code"
  harness_version: string
  provider: string
  model: string
  collection: string
  session_id: string
  root_session_id: string
  parent_session_id: string | null
  component: ComponentRef | null
  type: RawEventType
  payload: Record<string, unknown>
  redactions?: Redaction[]
}

/** Everything the mapper needs about a session to stamp identity onto an event. */
export interface Identity {
  collection: string
  harness_version: string
  provider: string
  model: string
  session_id: string
  root_session_id: string
  parent_session_id: string | null
  origin: "live" | "eval"
  component: ComponentRef | null
}

/** A watched component the logger resolved from a source tree. */
export interface WatchedComponent {
  kind: ComponentKind
  name: string
  path: string
}

/** One collection as published by `wikiskill collection check --sync`. */
export interface CollectionConfig {
  collection: string
  raw_dir: string
  error_log: string
  buffer_size: number
  output_limit_bytes: number
  redact: boolean
  watch: { skill: string[]; agent: string[]; command: string[] }
  source_roots: { path: string; layout: string }[]
  watched: WatchedComponent[]
}

export interface RuntimeConfig {
  version: number
  collections: CollectionConfig[]
}
