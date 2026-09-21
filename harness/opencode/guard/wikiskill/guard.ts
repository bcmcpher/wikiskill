/**
 * The evaluation guard's logic, kept out of the plugin module on purpose.
 *
 * OpenCode calls *every* export of a plugin file as a plugin factory. A module that also exports a
 * class therefore fails to load in its entirety — `Cannot call a class constructor GuardBlocked
 * without |new|` — and fails silently, as an ERROR line in a log nobody reads while the run carries
 * on unguarded. So the plugin file next door exports the factory and nothing else, and everything
 * that needs a name for a test lives here.
 */

/** Tools whose argument is a shell command line. */
const COMMAND_TOOLS = ["bash", "shell"]

/** Argument keys those tools use for the command line. */
const COMMAND_KEYS = ["command", "cmd", "script"]

/**
 * Distinct from `GuardBlocked` on purpose: the runner reads this text to classify the unit
 * `step_exhausted` rather than `permission_blocked`. Changing the wording changes the outcome class,
 * so `_STEP_EXHAUSTED_MARKER` in `runner/opencode.py` must change with it.
 */
export class StepBudgetExhausted extends Error {
  constructor(readonly budget: number) {
    super(`blocked by the wikiskill evaluation guard: step budget of ${budget} exhausted`)
    this.name = "StepBudgetExhausted"
  }
}

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

/** A step budget from the environment, or null when the unit was given none. */
export function parseBudget(raw: string | undefined): number | null {
  if (!raw) return null
  const parsed = Number(raw)
  if (!Number.isFinite(parsed) || !Number.isInteger(parsed) || parsed < 1) return null
  return parsed
}
