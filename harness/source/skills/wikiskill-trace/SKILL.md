---
name: wikiskill-trace
description: >
  Check whether wikiskill is recording a collection's sessions, and explain what the raw log holds.
  Use when the user asks whether logging is on, why a session was not logged, what wikiskill has
  captured so far, or asks to set up tracing for a set of skills.
---

# Is wikiskill recording this collection?

wikiskill logs a session **only** once it activates a watched skill, agent or command. A session
that never touches one writes nothing — that is the design, not a fault. Work through these in
order and stop at the first that explains what the user is seeing.

## 1. Does the collection resolve?

```bash
wikiskill collection check <name>
```

This lists every discovered component, marks the watched ones with `*`, and exits non-zero when a
watch-list entry matches nothing. An unresolved entry is the most common reason nothing is logged:
the watch list names `preregister` but the source tree calls it `govern/preregister`.

It never writes to the collection's source directory. If the user is worried about that, `git -C
<source> status` after running it is the check.

## 2. Does the harness know about the watch list?

The logger reads resolved JSON, not the TOML manifest. After editing a manifest:

```bash
wikiskill collection check <name> --sync
```

`wikiskill install --harness opencode --scope global` does this too. Without it, the plugin is
still running the previous watch list (it re-reads the file within a few seconds of a change, so no
restart is needed — but the file has to be republished).

## 3. Is anything arriving?

```bash
wikiskill log stats <name>
wikiskill log tail <name> -n 20
```

`stats` reports sessions, events by type, and **which models** produced them. Take seriously the
line about sessions that touched a watched component's source file without recording an activation:
that means the model consumed the skill text some way the logger did not recognise, and the watch
list or the detection needs looking at.

## 4. Is the log well-formed?

```bash
wikiskill log validate <name>
```

Exits non-zero on any schema error, and names the file, line and field. A refusal naming a
`schema_version` means the log was written by a newer wikiskill than the one reading it — upgrade
rather than delete the log; the raw layer is immutable and worth keeping.

## 5. Did the logger itself fail?

Logging is fail-open: it never interrupts a session, so failures are silent by design. They are
recorded here when the directory is writable at all:

```bash
cat "$(wikiskill collection show <name> --json | python3 -c 'import json,sys;print(json.load(sys.stdin)["error_log"])')"
```

## What the log does and does not contain

- Every event carries harness, harness version, provider, model and session identity, so the same
  skill can be compared across models and harnesses.
- An activation carries a `source_hash` — the SHA-256 of the component's file as it was at that
  moment. Two sessions with different hashes ran different versions of the skill.
- A delegation chain is one file: a child session's events are written into its root's log.
- Environment values and secret-shaped strings are replaced with `[REDACTED:<kind>]`; tool outputs
  above the configured bound are truncated, with the original length kept.
- No model call is ever made to produce a log. Nothing here is classified or summarised at write
  time.
