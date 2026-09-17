import { describe, expect, test } from "bun:test"

import { MIN_OPENCODE_VERSION, RECORDED_VERSION, compareVersions } from "./helpers"

describe("version comparison", () => {
  test("orders releases the way a human would", () => {
    expect(compareVersions("1.18.31", "1.18.31")).toBe(0)
    expect(compareVersions("1.18.32", "1.18.31")).toBeGreaterThan(0)
    expect(compareVersions("1.18.4", "1.18.31")).toBeLessThan(0)
    expect(compareVersions("1.19.0", "1.18.99")).toBeGreaterThan(0)
    expect(compareVersions("2.0", "1.18.31")).toBeGreaterThan(0)
    expect(compareVersions("1.14.22", "1.18.31")).toBeLessThan(0)
  })

  test("a missing component counts as zero", () => {
    expect(compareVersions("1.18", "1.18.0")).toBe(0)
    expect(compareVersions("1.18", "1.18.1")).toBeLessThan(0)
  })

  test("the fixtures satisfy the floor this plugin targets", () => {
    expect(compareVersions(RECORDED_VERSION, MIN_OPENCODE_VERSION)).toBeGreaterThanOrEqual(0)
  })
})
