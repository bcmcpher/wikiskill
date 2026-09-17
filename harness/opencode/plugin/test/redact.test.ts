import { describe, expect, test } from "bun:test"

import { bound, envSecrets, redact, redactValue } from "../wikiskill/redact"

describe("secret patterns", () => {
  const cases: [string, string, string][] = [
    ["anthropic key", "key=sk-ant-api03-AAAABBBBCCCCDDDDEEEE rest", "api_key"],
    ["openai key", "sk-AAAABBBBCCCCDDDDEEEEFFFF", "api_key"],
    ["aws access key", "AKIAIOSFODNN7EXAMPLE", "api_key"],
    ["github token", "ghp_AAAABBBBCCCCDDDDEEEEFFFFGGGG", "api_key"],
    ["slack token", "xoxb-1234567890-abcdefghij", "api_key"],
    ["bearer token", "Authorization: Bearer abcdefghijklmnopqrstuvwxyz12", "token"],
    ["jwt", "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NX0.dBjftJeZ4CVPmB92K27u", "token"],
    ["password assignment", 'password="hunter2hunter2"', "password"],
    ["url credentials", "postgres://user:s3cr3tpass@db.internal/app", "url_credentials"],
  ]

  test.each(cases)("%s is replaced and counted", (_label, input, kind) => {
    const result = redact(input)
    expect(result.text).toContain(`[REDACTED:${kind}]`)
    expect(result.redactions.some((r) => r.kind === kind)).toBe(true)
  })

  test("a private key block is removed whole", () => {
    const input =
      "-----BEGIN OPENSSH PRIVATE KEY-----\nbase64here\n-----END OPENSSH PRIVATE KEY-----"
    const result = redact(input)
    expect(result.text).toBe("[REDACTED:private_key]")
  })

  test("url credentials keep the host readable", () => {
    const result = redact("postgres://user:s3cr3tpass@db.internal/app")
    expect(result.text).toContain("db.internal")
    expect(result.text).not.toContain("s3cr3tpass")
  })

  test("ordinary text is left exactly alone", () => {
    const input = "created 4 files in /home/u/Projects/dsh and ran 12 tests"
    expect(redact(input)).toEqual({ text: input, redactions: [] })
  })
})

describe("environment values", () => {
  test("a secret-looking env value is scrubbed wherever it appears", () => {
    const secrets = envSecrets({ MY_TOKEN: "correct-horse-battery" })
    const result = redact("echo correct-horse-battery | wc -c", secrets)
    expect(result.text).not.toContain("correct-horse-battery")
    expect(result.redactions[0]).toEqual({ kind: "env_value", count: 1 })
  })

  test("common non-secret variables are left alone", () => {
    const secrets = envSecrets({ PATH: "/usr/bin:/bin", HOME: "/home/u", TERM: "xterm-256color" })
    expect(secrets).toEqual([])
  })

  test("a bare path is location, not a secret", () => {
    expect(envSecrets({ PROJECT_ROOT: "/home/u/Projects/dsh" })).toEqual([])
  })

  test("short values are too common to scrub safely", () => {
    expect(envSecrets({ TZ: "UTC" })).toEqual([])
  })

  test("longer values are scrubbed before shorter ones that they contain", () => {
    const secrets = envSecrets({ A: "abcdefghij", B: "abcdefghijKLMNOP" })
    expect(secrets[0]).toBe("abcdefghijKLMNOP")
  })
})

describe("structured values", () => {
  test("strings nested in a tool's arguments are redacted in place", () => {
    const { value, redactions } = redactValue({
      command: "curl -H 'Authorization: Bearer abcdefghijklmnopqrstuvwxyz12'",
      files: ["ok.txt", "sk-ant-api03-AAAABBBBCCCCDDDDEEEE"],
      count: 3,
      nested: { deeper: { token: "ghp_AAAABBBBCCCCDDDDEEEEFFFFGGGG" } },
    })
    const blob = JSON.stringify(value)
    expect(blob).not.toContain("abcdefghijklmnopqrstuvwxyz12")
    expect(blob).not.toContain("sk-ant-api03")
    expect(blob).not.toContain("ghp_AAAA")
    expect(blob).toContain('"count":3')
    expect(redactions.length).toBeGreaterThan(0)
  })

  test("a pathological structure is cut off rather than recursed forever", () => {
    const deep: any = {}
    let cursor = deep
    for (let i = 0; i < 40; i++) {
      cursor.next = {}
      cursor = cursor.next
    }
    expect(() => redactValue(deep)).not.toThrow()
    expect(JSON.stringify(redactValue(deep).value)).toContain("TRUNCATED:depth")
  })
})

describe("output bounds", () => {
  test("short output is untouched", () => {
    expect(bound("hello", 1024)).toEqual({ text: "hello", length: 5, truncated: false })
  })

  test("long output is cut and its real length reported", () => {
    const result = bound("x".repeat(5000), 100)
    expect(result.truncated).toBe(true)
    expect(result.length).toBe(5000)
    expect(result.text.length).toBe(100)
  })

  test("a cut never splits a multi-byte character", () => {
    const result = bound("é".repeat(100), 51)
    expect(Buffer.byteLength(result.text, "utf8")).toBeLessThanOrEqual(51)
    expect(result.text.endsWith("é")).toBe(true)
  })
})

describe("truncation boundaries", () => {
  test("a multibyte character is never cut in half", () => {
    // Each emoji is 4 UTF-8 bytes, so a 10-byte limit has to stop after the second one.
    const text = "\u{1f9ea}".repeat(8)
    const limited = bound(text, 10)
    expect(limited.truncated).toBe(true)
    expect(Buffer.byteLength(limited.text, "utf8")).toBeLessThanOrEqual(10)
    expect(limited.text).toBe("\u{1f9ea}\u{1f9ea}")
    // No replacement character, and no lone surrogate half.
    expect(limited.text).not.toContain("\ufffd")
    expect(JSON.parse(JSON.stringify(limited.text))).toBe(limited.text)
    // The recorded length stays the true one, in characters.
    expect(limited.length).toBe(text.length)
  })

  test("a large output is bounded without a per-character rescan", () => {
    const text = "\u00e9".repeat(500_000)
    const started = Date.now()
    const limited = bound(text, 16 * 1024)
    expect(Buffer.byteLength(limited.text, "utf8")).toBeLessThanOrEqual(16 * 1024)
    expect(limited.truncated).toBe(true)
    expect(Date.now() - started).toBeLessThan(1_000)
  })
})
