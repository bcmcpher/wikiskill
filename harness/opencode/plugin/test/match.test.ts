import { describe, expect, test } from "bun:test"

import { globToRegExp, matchesAny, watchedComponentFor, watches } from "../wikiskill/match"

import { WATCHED_SKILL_PATH, collection } from "./helpers"

const config = collection()

describe("glob semantics match Python's fnmatch", () => {
  test("* spans path separators", () => {
    expect(globToRegExp("analyze/*").test("analyze/run-comparison")).toBe(true)
    expect(globToRegExp("*").test("govern/preregister")).toBe(true)
  })

  test("? is exactly one character", () => {
    expect(globToRegExp("skill-?").test("skill-a")).toBe(true)
    expect(globToRegExp("skill-?").test("skill-ab")).toBe(false)
  })

  test("a character class works, including negation", () => {
    expect(globToRegExp("v[0-9]").test("v3")).toBe(true)
    expect(globToRegExp("v[!0-9]").test("v3")).toBe(false)
  })

  test("regex metacharacters in a pattern are literal", () => {
    expect(globToRegExp("qwen3:1.7b").test("qwen3:1.7b")).toBe(true)
    expect(globToRegExp("qwen3:1.7b").test("qwen3:1X7b")).toBe(false)
  })

  test("matching is anchored at both ends", () => {
    expect(matchesAny("preregister-old", ["preregister"])).toBe(false)
  })
})

describe("watch list", () => {
  test("a qualified watch entry matches the name the harness reports", () => {
    // The manifest knows `govern/preregister`; OpenCode's skill tool says `preregister`.
    expect(watches(config, "skill", "preregister")).toBe(true)
    expect(watches(config, "skill", "govern/preregister")).toBe(true)
  })

  test("an unrelated component is not watched", () => {
    expect(watches(config, "skill", "some-other-skill")).toBe(false)
    expect(watches(config, "agent", "preregister")).toBe(false)
  })

  test("kinds do not bleed into each other", () => {
    expect(watches(config, "command", "datalad-doer")).toBe(false)
    expect(watches(config, "agent", "datalad-doer")).toBe(true)
  })
})

describe("watched paths", () => {
  test("a watched component is found by its source file", () => {
    expect(watchedComponentFor(config, WATCHED_SKILL_PATH)?.name).toBe("govern/preregister")
  })

  test("an unrelated path matches nothing", () => {
    expect(watchedComponentFor(config, "/etc/hosts")).toBeNull()
    expect(watchedComponentFor(config, "")).toBeNull()
  })
})

describe("false activations", () => {
  test("a qualified name is not matched by another plugin's copy of it", () => {
    // `govern/preregister` is watched; a same-named skill from a different plugin is not the same
    // component and must not be logged under the watched name.
    expect(watches(config, "skill", "other-plugin/preregister")).toBe(false)
    expect(watches(config, "skill", "govern/preregister")).toBe(true)
    // An unqualified name still matches, because OpenCode reports skills bare.
    expect(watches(config, "skill", "preregister")).toBe(true)
  })

  test("a bare file name does not match a watched component", () => {
    // A relative read of `SKILL.md` used to match whichever watched component came first.
    expect(watchedComponentFor(config, "SKILL.md")).toBeNull()
    expect(watchedComponentFor(config, "/SKILL.md")).toBeNull()
  })

  test("a relative path matches only on a directory boundary", () => {
    expect(watchedComponentFor(config, "preregister/SKILL.md")?.name).toBe("govern/preregister")
    expect(watchedComponentFor(config, "skills/preregister/SKILL.md")?.name).toBe(
      "govern/preregister",
    )
    // Same tail characters, different directory.
    expect(watchedComponentFor(config, "/other/notpreregister/SKILL.md")).toBeNull()
  })
})
