/**
 * Redaction cases shared with the Python port (`src/wikiskill/redact.py`), which
 * `tests/test_parity.py` runs too. A case marked `known_divergence` records each side's current
 * output, so fixing either side fails a test until the fixture says the two agree.
 */

import { describe, expect, test } from "bun:test"
import { readFileSync } from "node:fs"
import { join } from "node:path"

import { bound, envSecrets, redact, redactValue } from "../wikiskill/redact"

const FIXTURE = join(import.meta.dir, "..", "..", "..", "..", "tests/fixtures/parity", "redact.json")
const fixture = JSON.parse(readFileSync(FIXTURE, "utf8"))

/** This side's expectation: the shared one, or its own for a known divergence. */
const expected = (c: any): any => ("known_divergence" in c ? c.typescript : c.expected)
const textOf = (t: any): string => (typeof t === "string" ? t : t.repeat.repeat(t.times))

describe("redact", () => {
  test.each(fixture.redact.map((c: any) => [c.name, c]))("%s", (_name, c: any) => {
    expect(redact(c.text, envSecrets(c.env))).toEqual(expected(c))
  })
})

describe("envSecrets", () => {
  test.each(fixture.env_secrets.map((c: any) => [c.name, c]))("%s", (_name, c: any) => {
    expect(envSecrets(c.env)).toEqual(expected(c))
  })
})

describe("redactValue", () => {
  test.each(fixture.redact_value.map((c: any) => [c.name, c]))("%s", (_name, c: any) => {
    expect(redactValue(c.value)).toEqual(expected(c))
  })
})

describe("bound", () => {
  test.each(fixture.bound.map((c: any) => [c.name, c]))("%s", (_name, c: any) => {
    expect(bound(textOf(c.text), c.limit)).toEqual(expected(c))
  })
})
