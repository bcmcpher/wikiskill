/**
 * Guard cases shared with the Claude Code port (`src/wikiskill/guard.py`), which
 * `tests/test_parity.py` runs too. A case marked `known_divergence` records each side's current
 * output, so fixing either side fails a test until the fixture says the two agree.
 */

import { describe, expect, test } from "bun:test"
import { readFileSync } from "node:fs"
import { join } from "node:path"

import {
  GuardBlocked,
  StepBudgetExhausted,
  commandsIn,
  denialFor,
  matchesPattern,
  parseBudget,
  parseList,
} from "../wikiskill/guard"

const FIXTURE = join(import.meta.dir, "..", "..", "..", "..", "tests/fixtures/parity", "guard.json")
const fixture = JSON.parse(readFileSync(FIXTURE, "utf8"))

/** This side's expectation: the shared one, or its own for a known divergence. */
const expected = (c: any): any => ("known_divergence" in c ? c.typescript : c.expected)
const named = (cases: any[]) => cases.map((c: any) => [c.name, c])

describe("matchesPattern", () => {
  test.each(fixture.matches.map((c: any) => [JSON.stringify(c.subject), JSON.stringify(c.pattern), c]))(
    "%s ~ %s",
    (_subject, _pattern, c: any) => {
      expect(matchesPattern(c.subject, c.pattern)).toBe(expected(c))
    },
  )
})

describe("commandsIn", () => {
  test.each(named(fixture.commands_in))("%s", (_name, c: any) => {
    expect(commandsIn(c.args)).toEqual(expected(c))
  })
})

describe("denialFor", () => {
  test.each(named(fixture.denial_for))("%s", (_name, c: any) => {
    expect(denialFor(c.tool, c.args, c.deny, c.tools)).toEqual(expected(c))
  })
})

describe("parseList", () => {
  // A `raw` of null is an unset variable, which the plugin sees as undefined.
  test.each(named(fixture.parse_list))("%s", (_name, c: any) => {
    expect(parseList(c.raw ?? undefined)).toEqual(expected(c))
  })
})

describe("parseBudget", () => {
  test.each(named(fixture.parse_budget))("%s", (_name, c: any) => {
    expect(parseBudget(c.raw ?? undefined)).toEqual(expected(c))
  })
})

describe("refusal messages", () => {
  test.each(named(fixture.messages))("%s", (_name, c: any) => {
    const message = c.blocked
      ? new GuardBlocked(c.blocked[0], c.blocked[1]).message
      : new StepBudgetExhausted(c.step).message
    expect(message).toBe(expected(c))
  })
})
