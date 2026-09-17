---
description: >
  Report whether wikiskill is recording a collection, and summarise what its raw log holds.
  Takes an optional collection name.
---

Check wikiskill's tracing for the collection named in `$ARGUMENTS`. With no name given, run
`wikiskill collection show` against each name in `~/.config/wikiskill/collections/` and pick the one
the user most likely means, or ask.

Follow the `wikiskill-trace` skill. Report, briefly:

1. whether the manifest resolves (`wikiskill collection check <name>`) and which entries do not
2. whether the resolved watch list has been published to the harness (`--sync`)
3. sessions, events and models recorded so far (`wikiskill log stats <name>`)
4. schema errors, if any (`wikiskill log validate <name>`)

If nothing has been recorded, say which of those four is the reason rather than guessing. Do not
edit the manifest without being asked.
