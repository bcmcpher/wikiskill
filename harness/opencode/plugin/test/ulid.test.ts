import { describe, expect, test } from "bun:test"

import { isUlid, timestamp, ulid } from "../wikiskill/ulid"

describe("ulid", () => {
  test("is 26 Crockford base32 characters", () => {
    expect(ulid()).toHaveLength(26)
    expect(isUlid(ulid())).toBe(true)
  })

  test("sorts by creation time", () => {
    const early = ulid(1_700_000_000_000)
    const late = ulid(1_800_000_000_000)
    expect(early < late).toBe(true)
  })

  test("two ids from the same millisecond differ", () => {
    expect(ulid(NOW_MS)).not.toBe(ulid(NOW_MS))
  })

  test("excludes the ambiguous letters Crockford drops", () => {
    const id = ulid()
    expect(id).not.toMatch(/[ILOU]/)
  })
})

const NOW_MS = 1789674260000

describe("timestamp", () => {
  test("is RFC 3339 in UTC with milliseconds", () => {
    expect(timestamp(NOW_MS)).toMatch(/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$/)
  })
})
