# Fixtures

`opencode-1.18.31-events.json` holds **real** OpenCode bus payloads, captured on 2026-09-17 by a
throwaway plugin that dumped every `event` hook payload during `opencode run` against a local Ollama
endpoint. Nothing in it is hand-written; the only editing was picking one payload per type.

That run failed at its first tool call — `... does not support tools` — so the `session.error`
fixture is genuine too, and the file contains no `tool.execute.after` payload.

`tool-calls.json` therefore holds **constructed** `tool.execute.after` inputs and outputs, built
from the hook signature and `ToolStateCompleted` shape in the installed
`@opencode-ai/sdk` `types.gen.d.ts`, not from a live run. Replace them with a real capture when an
endpoint with working tool calling is available; the mapper contract tests will then be exercising
recorded traffic end to end.

## Re-capturing after a harness upgrade

The plugin targets OpenCode **1.18.31 or newer** and the harness is updated regularly, so these
fixtures are expected to be replaced by newer captures. Nothing asserts a hard-coded release: tests
read the version out of the fixture (`RECORDED_VERSION` in `../helpers.ts`) and check only that it is
at or above `MIN_OPENCODE_VERSION`.

To re-capture, drop a throwaway plugin into a scratch project's `.opencode/plugin/` that dumps every
hook payload:

```ts
import { appendFileSync } from "node:fs"
const OUT = "/tmp/opencode-events.jsonl"
const dump = (kind: string, data: unknown) => {
  try { appendFileSync(OUT, JSON.stringify({ _kind: kind, _at: Date.now(), data }) + "\n") } catch {}
}
export const capture = async () => ({
  event: async ({ event }: any) => dump("event", event),
  "chat.message": async (input: any) => dump("chat.message", input),
  "command.execute.before": async (input: any) => dump("command.execute.before", input),
  "tool.execute.after": async (input: any, output: any) =>
    dump("tool.execute.after", { input, output }),
})
export default capture
```

Run `opencode run` against any endpoint, keep one payload per type, and name the file after the
version it came from. Then raise `MIN_OPENCODE_VERSION` and update the first paragraph above.

Use a model that can actually call tools, or the capture will have no `tool.execute.after` payload —
which is exactly why this directory still has a constructed `tool-calls.json`.
