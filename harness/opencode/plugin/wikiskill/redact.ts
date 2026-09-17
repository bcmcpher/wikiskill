/**
 * Redaction and output bounds. Pure: no I/O, no environment reads.
 *
 * The caller supplies the environment values to scrub, so this module is testable and so the
 * snapshot of the environment is taken once at plugin start rather than per event.
 */

import type { Redaction, RedactionKind } from "./types"

/** Environment values shorter than this are too common to redact without mangling output. */
const MIN_ENV_VALUE = 8

/** Environment variable names whose values are never secrets and would ruin readability. */
const ENV_ALLOW = new Set([
  "PATH",
  "HOME",
  "PWD",
  "OLDPWD",
  "SHELL",
  "TERM",
  "LANG",
  "LC_ALL",
  "USER",
  "LOGNAME",
  "HOSTNAME",
  "TMPDIR",
  "EDITOR",
  "XDG_CONFIG_HOME",
  "XDG_DATA_HOME",
  "XDG_STATE_HOME",
  "XDG_CACHE_HOME",
])

interface Pattern {
  kind: RedactionKind
  re: RegExp
  /** Which capture group holds the secret; 0 means the whole match. */
  group?: number
}

const PATTERNS: Pattern[] = [
  { kind: "private_key", re: /-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----/g },
  { kind: "api_key", re: /\b(?:sk|rk|pk)-[A-Za-z0-9_-]{16,}\b/g },
  { kind: "api_key", re: /\bsk-ant-[A-Za-z0-9_-]{16,}\b/g },
  { kind: "api_key", re: /\bAKIA[0-9A-Z]{16}\b/g },
  { kind: "api_key", re: /\bgh[pousr]_[A-Za-z0-9]{16,}\b/g },
  { kind: "api_key", re: /\bxox[abprs]-[A-Za-z0-9-]{10,}\b/g },
  { kind: "token", re: /\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b/g },
  { kind: "token", re: /\b[Bb]earer\s+([A-Za-z0-9._~+/=-]{20,})/g, group: 1 },
  {
    kind: "password",
    re: /\b(?:password|passwd|secret|api[_-]?key|access[_-]?token|auth[_-]?token)["']?\s*[:=]\s*["']?([^\s"',;]{6,})/gi,
    group: 1,
  },
  { kind: "url_credentials", re: /\b([a-z][a-z0-9+.-]*):\/\/[^\s/:@]+:([^\s/@]+)@/gi, group: 2 },
]

export interface RedactResult {
  text: string
  redactions: Redaction[]
}

/** Values worth scrubbing from a snapshot of the environment. */
export function envSecrets(env: Record<string, string | undefined>): string[] {
  const values: string[] = []
  for (const [name, value] of Object.entries(env)) {
    if (!value || value.length < MIN_ENV_VALUE) continue
    if (ENV_ALLOW.has(name)) continue
    // A value that is just a path is location, not a secret.
    if (value.startsWith("/") && !/[:@]/.test(value)) continue
    values.push(value)
  }
  // Longest first, so a value that contains another is replaced whole.
  return values.sort((a, b) => b.length - a.length)
}

export function redact(text: string, envValues: string[] = []): RedactResult {
  if (!text) return { text, redactions: [] }
  const counts = new Map<RedactionKind, number>()
  let out = text

  for (const value of envValues) {
    let seen = 0
    while (out.includes(value)) {
      out = out.replace(value, "[REDACTED:env_value]")
      seen += 1
      if (seen > 100) break
    }
    if (seen) counts.set("env_value", (counts.get("env_value") ?? 0) + seen)
  }

  for (const { kind, re, group } of PATTERNS) {
    out = out.replace(new RegExp(re.source, re.flags), (match, ...groups) => {
      const secret = group ? (groups[group - 1] as string | undefined) : match
      if (!secret) return match
      counts.set(kind, (counts.get(kind) ?? 0) + 1)
      const marker = `[REDACTED:${kind}]`
      return group ? match.replace(secret, marker) : marker
    })
  }

  const redactions: Redaction[] = [...counts.entries()]
    .map(([kind, count]) => ({ kind, count }))
    .sort((a, b) => a.kind.localeCompare(b.kind))
  return { text: out, redactions }
}

/** Redact every string inside a tool's arguments, preserving the structure. */
export function redactValue(
  value: unknown,
  envValues: string[] = [],
  depth = 0,
): { value: unknown; redactions: Redaction[] } {
  if (depth > 8) return { value: "[TRUNCATED:depth]", redactions: [] }
  if (typeof value === "string") {
    const result = redact(value, envValues)
    return { value: result.text, redactions: result.redactions }
  }
  if (Array.isArray(value)) {
    const redactions: Redaction[] = []
    const items = value.map((item) => {
      const result = redactValue(item, envValues, depth + 1)
      redactions.push(...result.redactions)
      return result.value
    })
    return { value: items, redactions: merge(redactions) }
  }
  if (value && typeof value === "object") {
    const redactions: Redaction[] = []
    const out: Record<string, unknown> = {}
    for (const [key, item] of Object.entries(value as Record<string, unknown>)) {
      const result = redactValue(item, envValues, depth + 1)
      redactions.push(...result.redactions.map((r) => ({ ...r, field: r.field ?? key })))
      out[key] = result.value
    }
    return { value: out, redactions: merge(redactions) }
  }
  return { value: value ?? null, redactions: [] }
}

export function merge(redactions: Redaction[]): Redaction[] {
  const counts = new Map<RedactionKind, number>()
  for (const entry of redactions) {
    counts.set(entry.kind, (counts.get(entry.kind) ?? 0) + entry.count)
  }
  return [...counts.entries()]
    .map(([kind, count]) => ({ kind, count }))
    .sort((a, b) => a.kind.localeCompare(b.kind))
}

export interface BoundedOutput {
  text: string
  length: number
  truncated: boolean
}

/** Bound a tool output, keeping the original length so the record stays honest. */
export function bound(text: string, limitBytes: number): BoundedOutput {
  const length = text.length
  if (Buffer.byteLength(text, "utf8") <= limitBytes) {
    return { text, length, truncated: false }
  }
  // Cut on a character boundary at or below the byte limit.
  let end = Math.min(text.length, limitBytes)
  while (end > 0 && Buffer.byteLength(text.slice(0, end), "utf8") > limitBytes) end -= 1
  return { text: text.slice(0, end), length, truncated: true }
}
