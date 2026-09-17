/**
 * Emit one raw event of every type this change defines, as JSONL on stdout.
 *
 * This exists so the Python side can validate what the TypeScript side actually produces against
 * `schemas/raw-event.schema.json`. Without it the two halves of the contract are only checked
 * against their own idea of the schema.
 *
 *     bun run test/emit-sample.ts
 */

import {
  DEFAULT_OPTIONS,
  detectActivation,
  detectCommandActivation,
  mapActivation,
  mapAssistantTurn,
  mapDelegation,
  mapError,
  mapSessionEnd,
  mapSessionStart,
  mapStepUsage,
  mapToolCall,
} from "../wikiskill/mapper"
import { watchedComponentFor, watches } from "../wikiskill/match"
import type { ComponentKind, RawEvent } from "../wikiskill/types"

import { NOW, collection, events, identity, tools } from "./helpers"

const config = collection()
const options = { ...DEFAULT_OPTIONS, envValues: ["correct-horse-battery"], redactEnabled: true }
const watchedName = (kind: ComponentKind, name: string) => watches(config, kind, name)
const watchedPath = (path: string) => watchedComponentFor(config, path)

const call = (fixture: any) => ({
  tool: fixture.input.tool,
  callID: fixture.input.callID,
  args: fixture.input.args,
  output: fixture.output.output,
  metadata: fixture.output.metadata,
})

const root = identity()
const child = identity({
  session_id: "ses_9c21bb3310ceqT8mzzR4d91xKW",
  parent_session_id: root.session_id,
})

const skillHint = detectActivation(call(tools.skill), watchedName, watchedPath)!
const readHint = detectActivation(call(tools.read_watched), watchedName, watchedPath)!
const commandHint = detectCommandActivation("/wikiskill-trace", watchedName)!
const hash = "sha256:" + "0".repeat(64)

const emitted: (RawEvent | null)[] = [
  mapSessionStart(events["session.created"].properties.info, root, NOW),
  mapActivation(skillHint, hash, root, "freeze the motion-QC comparison", NOW),
  mapActivation(readHint, hash, root, null, NOW),
  mapActivation(commandHint, null, root, "dsh", NOW),
  mapDelegation(call(tools.task), root, NOW),
  mapToolCall(call(tools.task), root, options, NOW),
  mapToolCall(call(tools.bash_with_secret), child, options, NOW),
  mapToolCall({ tool: "write", args: {}, output: "", error: "ENOENT" }, root, options, NOW),
  mapToolCall({ tool: "bash", args: {}, output: "y".repeat(40_000) }, root, options, NOW),
  mapAssistantTurn(
    { type: "text", text: "done", messageID: "msg_1", time: { start: NOW - 10, end: NOW } },
    root,
    options,
    true,
    NOW,
  ),
  mapStepUsage(
    {
      type: "step-finish",
      reason: "stop",
      cost: 0,
      tokens: { input: 4871, output: 233, reasoning: 0, cache: { read: 0, write: 0 } },
    },
    root,
    NOW,
  ),
  mapError(events["session.error"].properties.error.data.message, "session", root, NOW),
  mapSessionEnd("idle", root, NOW),
]

for (const event of emitted) {
  if (event) console.log(JSON.stringify(event))
}
