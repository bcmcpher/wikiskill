/** ULIDs: 48 bits of millisecond timestamp then 80 random bits, Crockford base32. */

const CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"

/** Monotonic within a millisecond is not required here; events also carry `ts`. */
export function ulid(now: number = Date.now()): string {
  const bytes = new Uint8Array(10)
  crypto.getRandomValues(bytes)

  let out = ""
  // 48-bit timestamp → 10 characters.
  let time = Math.floor(now)
  const timeChars: string[] = []
  for (let i = 0; i < 10; i++) {
    timeChars.push(CROCKFORD[time % 32])
    time = Math.floor(time / 32)
  }
  out += timeChars.reverse().join("")

  // 80 random bits → 16 characters.
  let bits = 0
  let value = 0
  for (const byte of bytes) {
    value = (value << 8) | byte
    bits += 8
    while (bits >= 5) {
      bits -= 5
      out += CROCKFORD[(value >> bits) & 31]
      value &= (1 << bits) - 1
    }
  }
  return out
}

export function isUlid(value: string): boolean {
  return /^[0-7][0-9ABCDEFGHJKMNPQRSTVWXYZ]{25}$/.test(value)
}

/** RFC 3339 in UTC with millisecond precision — what the Python reader expects. */
export function timestamp(now: number = Date.now()): string {
  return new Date(now).toISOString()
}
