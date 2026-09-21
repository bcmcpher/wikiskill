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
 * It also holds the unit's step budget. OpenCode's `run` has no step limit of its own, so the only
 * place to count steps is the hook every tool call passes through. A model that loops forever would
 * otherwise burn the whole `timeout_s` and be recorded as an infrastructure failure, which is the
 * wrong answer: running out of steps is something the *model* did.
 *
 * Configuration is per-unit and arrives in the environment, because each task in a run denies
 * something different:
 *   WIKISKILL_GUARD_DENY  — JSON array of glob patterns matched against a shell command
 *   WIKISKILL_GUARD_TOOLS — JSON array of tool names to refuse outright (optional)
 *   WIKISKILL_MAX_STEPS   — tool calls this unit may make before it is cut off (optional)
 */

import { GuardBlocked, StepBudgetExhausted, denialFor, parseBudget, parseList } from "./wikiskill/guard"

export const wikiskillGuard = async () => {
  const deny = parseList(process.env.WIKISKILL_GUARD_DENY)
  const deniedTools = parseList(process.env.WIKISKILL_GUARD_TOOLS)
  const budget = parseBudget(process.env.WIKISKILL_MAX_STEPS)
  let steps = 0

  return {
    "tool.execute.before": async (input: any, output: any) => {
      // Counted before the deny check, so a model cannot buy extra steps by making calls it knows
      // will be refused.
      steps += 1
      if (budget !== null && steps > budget) throw new StepBudgetExhausted(budget)

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
