import type { CollectionConfig, Identity } from "../wikiskill/types"

import real from "./fixtures/opencode-1.18.31-events.json"
import toolCalls from "./fixtures/tool-calls.json"

export const events = real.events as Record<string, any>

/**
 * The oldest OpenCode this plugin targets. The harness is updated often, so the fixtures are
 * expected to be re-captured from newer versions; tests compare against this floor and against the
 * recorded version below, never against a hard-coded release.
 */
export const MIN_OPENCODE_VERSION = "1.18.31"

/** The version the fixtures were actually captured from. */
export const RECORDED_VERSION: string =
  (real.events as any)["session.created"].properties.info.version

/** Compare two dotted versions. Returns <0, 0 or >0. */
export function compareVersions(a: string, b: string): number {
  const left = a.split(".").map(Number)
  const right = b.split(".").map(Number)
  for (let i = 0; i < Math.max(left.length, right.length); i++) {
    const diff = (left[i] ?? 0) - (right[i] ?? 0)
    if (diff !== 0) return diff
  }
  return 0
}
export const chatMessage = real.chat_message as any
export const tools = toolCalls as Record<string, any>

export const WATCHED_SKILL_PATH =
  "/home/u/Projects/dsh/plugins/govern/skills/preregister/SKILL.md"

export function collection(overrides: Partial<CollectionConfig> = {}): CollectionConfig {
  return {
    collection: "dsh",
    raw_dir: "/tmp/wikiskill-test/raw",
    error_log: "/tmp/wikiskill-test/raw/_logger-errors.log",
    buffer_size: 200,
    output_limit_bytes: 16 * 1024,
    redact: true,
    watch: { skill: ["govern/preregister"], agent: ["datalad-doer"], command: ["wikiskill-trace"] },
    source_roots: [{ path: "/home/u/Projects/dsh/plugins", layout: "claude-plugin" }],
    watched: [
      { kind: "skill", name: "govern/preregister", path: WATCHED_SKILL_PATH },
      {
        kind: "agent",
        name: "datalad-doer",
        path: "/home/u/Projects/dsh/plugins/datalad/agents/datalad-doer.md",
      },
    ],
    ...overrides,
  }
}

export function identity(overrides: Partial<Identity> = {}): Identity {
  return {
    collection: "dsh",
    harness_version: RECORDED_VERSION,
    provider: "ollama",
    model: "qwen3:1.7b",
    session_id: "ses_f4f1a0774ffepL3wqqJ5f72ctQ",
    root_session_id: "ses_f4f1a0774ffepL3wqqJ5f72ctQ",
    parent_session_id: null,
    origin: "live",
    component: null,
    ...overrides,
  }
}

export const NOW = 1789674260000
