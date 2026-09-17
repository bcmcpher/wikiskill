/**
 * Drive an *installed* logger through one session, without a model.
 *
 * `bun test` exercises the plugin from this source tree. This exercises the copy that
 * `wikiskill install` actually wrote, against the `runtime.json` actually published — everything the
 * smoke test covers except OpenCode itself calling the hooks. That matters here because local
 * models are slow and frequently cannot call tools at all, so an installation should be verifiable
 * without one.
 *
 *     bun run test/drive-installed.ts <harness-config-dir> <watched-skill-name> [skill-dir]
 *
 * for example:
 *
 *     bun run test/drive-installed.ts ~/.config/opencode smoke-check ~/.config/opencode/skills/smoke-check
 *
 * Then check what was recorded:
 *
 *     wikiskill log validate <collection>
 */

import { existsSync } from "node:fs"
import { join, resolve } from "node:path"

const [target, skillName, skillDir] = process.argv.slice(2)

if (!target || !skillName) {
  console.error(
    "usage: bun run test/drive-installed.ts <harness-config-dir> <watched-skill-name> [skill-dir]",
  )
  process.exit(2)
}

const entry = resolve(join(target, "plugin", "wikiskill-logger.ts"))
if (!existsSync(entry)) {
  console.error(`no installed logger at ${entry}; run \`wikiskill install\` first`)
  process.exit(1)
}

const { wikiskillLogger } = (await import(entry)) as { wikiskillLogger: () => Promise<any> }
const hooks = await wikiskillLogger()

const SESSION = `ses_driveinstalled${Date.now()}`
const MODEL = { providerID: "none", modelID: "driven-without-a-model" }

await hooks.event({
  event: {
    type: "session.created",
    properties: {
      sessionID: SESSION,
      info: {
        id: SESSION,
        version: "driven",
        directory: process.cwd(),
        title: "driven from test/drive-installed.ts",
      },
    },
  },
})

await hooks["chat.message"]({ sessionID: SESSION, model: MODEL })

// An unwatched call first, so the flush of pre-activation history is exercised too.
await hooks["tool.execute.after"](
  { tool: "bash", sessionID: SESSION, callID: "call_00", args: { command: "true" } },
  { title: "bash", output: "", metadata: {} },
)

await hooks["tool.execute.after"](
  { tool: "skill", sessionID: SESSION, callID: "call_01", args: { name: skillName } },
  {
    title: skillName,
    output: `Loaded skill ${skillName}`,
    metadata: skillDir ? { dir: resolve(skillDir) } : {},
  },
)

await hooks.event({
  event: {
    type: "message.updated",
    properties: {
      info: {
        id: "msg_driven",
        role: "assistant",
        sessionID: SESSION,
        providerID: MODEL.providerID,
        modelID: MODEL.modelID,
      },
    },
  },
})

await hooks.event({
  event: {
    type: "message.part.updated",
    properties: {
      part: {
        type: "text",
        text: "driven without a model",
        messageID: "msg_driven",
        sessionID: SESSION,
        time: { start: Date.now() - 1, end: Date.now() },
      },
    },
  },
})

await hooks.event({
  event: {
    type: "message.part.updated",
    properties: {
      part: {
        type: "step-finish",
        messageID: "msg_driven",
        sessionID: SESSION,
        reason: "stop",
        cost: 0,
        tokens: { input: 0, output: 0, reasoning: 0, cache: { read: 0, write: 0 } },
      },
    },
  },
})

await hooks.event({ event: { type: "session.idle", properties: { sessionID: SESSION } } })

console.log(`drove the logger at ${entry} through session ${SESSION}`)
console.log("now run: wikiskill log validate <collection>")
