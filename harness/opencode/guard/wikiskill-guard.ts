/**
 * wikiskill's evaluation guard.
 *
 * Installed only into an evaluation run's own isolated config, never into a user's. It refuses the
 * command patterns a task declares under `guard.deny`, on top of the deny-by-default permissions the
 * runner already sets. The point is that a task suite can let a model run `git commit` inside its
 * throwaway workdir while still making `git push` impossible.
 *
 * Unlike the logger, this plugin is fail-CLOSED: a guard that cannot read its own configuration
 * blocks nothing it was not asked to block, but a pattern that matches always throws. Throwing from
 * `tool.execute.before` is how an OpenCode plugin refuses a call.
 *
 * Configuration is per-unit and arrives in the environment, because each task in a run denies
 * something different:
 *   WIKISKILL_GUARD_DENY  — JSON array of glob patterns matched against a shell command
 *   WIKISKILL_GUARD_TOOLS — JSON array of tool names to refuse outright (optional)
 */

/** Tools whose argument is a shell command line. */
const COMMAND_TOOLS = ["bash", "shell"]

/** Argument keys those tools use for the command line. */
const COMMAND_KEYS = ["command", "cmd", "script"]

export class GuardBlocked extends Error {
  constructor(
    readonly subject: string,
    readonly pattern: string,
  ) {
    super(`blocked by the wikiskill evaluation guard: ${subject} matches deny pattern ${pattern}`)
    this.name = "GuardBlocked"
  }
}

/** Parse a JSON array of strings from the environment, tolerating anything that is not one. */
export function parseList(raw: string | undefined): string[] {
  if (!raw) return []
  try {
    const parsed = JSON.parse(raw)
    if (!Array.isArray(parsed)) return []
    return parsed.filter((entry): entry is string => typeof entry === "string" && entry.length > 0)
  } catch {
    return []
  }
}

/**
 * Glob match, anchored at both ends: `*` spans any run of characters, `?` one character.
 *
 * A suite writes `git push*`, meaning "any command that starts with git push". Escaping every other
 * regex metacharacter keeps a pattern like `rm -rf /` from being read as a character class.
 */
export function matchesPattern(subject: string, pattern: string): boolean {
  const escaped = pattern.replace(/[.+^${}()|[\]\\]/g, "\\$&")
  const expanded = escaped.replace(/\*/g, "[\\s\\S]*").replace(/\?/g, "[\\s\\S]")
  return new RegExp(`^${expanded}$`).test(subject)
}

/**
 * Every shell command a tool call would run.
 *
 * A single call can carry several: `&&`, `;` and `|` chain commands, and a pattern that denies
 * `git push*` has to catch `cd x && git push`. Splitting is deliberately naive — it over-approximates,
 * which for a guard is the safe direction.
 */
export function commandsIn(args: Record<string, unknown>): string[] {
  const found: string[] = []
  for (const key of COMMAND_KEYS) {
    const value = args?.[key]
    if (typeof value !== "string" || value.trim() === "") continue
    found.push(value.trim())
    for (const part of value.split(/&&|\|\||;|\||\n/)) {
      const trimmed = part.trim()
      if (trimmed && trimmed !== value.trim()) found.push(trimmed)
    }
  }
  return found
}

/** The pattern that refuses this call, or null when nothing does. */
export function denialFor(
  tool: string,
  args: Record<string, unknown>,
  deny: string[],
  deniedTools: string[],
): { subject: string; pattern: string } | null {
  const name = (tool || "").toLowerCase()
  for (const denied of deniedTools) {
    if (matchesPattern(name, denied.toLowerCase())) return { subject: `tool ${name}`, pattern: denied }
  }
  if (!COMMAND_TOOLS.includes(name) || deny.length === 0) return null
  for (const command of commandsIn(args)) {
    for (const pattern of deny) {
      if (matchesPattern(command, pattern)) return { subject: command, pattern }
    }
  }
  return null
}

export const wikiskillGuard = async () => {
  const deny = parseList(process.env.WIKISKILL_GUARD_DENY)
  const deniedTools = parseList(process.env.WIKISKILL_GUARD_TOOLS)

  return {
    "tool.execute.before": async (input: any, output: any) => {
      const denial = denialFor(
        String(input?.tool ?? ""),
        (output?.args ?? input?.args ?? {}) as Record<string, unknown>,
        deny,
        deniedTools,
      )
      if (denial) throw new GuardBlocked(denial.subject, denial.pattern)
    },
  }
}

export default wikiskillGuard
