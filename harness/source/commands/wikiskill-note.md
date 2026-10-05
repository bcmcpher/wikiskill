---
description: >
  Record a note on what a skill or agent got wrong in this session, for wikiskill to learn from.
  Takes the note, optionally prefixed with the component it is about.
---

Record the user's note with `wikiskill note`, exactly as they wrote it in `$ARGUMENTS`. This is the
one way a user flags a correction for certain, so do not rephrase, summarise, soften or add to it,
and do not try to fix the problem it describes unless asked.

1. If `$ARGUMENTS` starts with the name of a watched component followed by a colon or a dash (for
   example `preregister: the plot used the wrong axis scale`), pass that name as `--component` and
   the rest as the note. Otherwise pass all of it as the note; wikiskill attaches it to the
   component that ran most recently in this session.
2. Run it once, from this session's working directory, with the note as a single quoted argument
   after `--`:

   ```
   wikiskill note [--component <name>] -- '<note>'
   ```

   Escape any single quote in the note as `'\''`.
3. Report the one line it prints: the collection, the session and the component the note was
   attached to. Pass on any warning it gives, such as a note attached to no component or a choice
   between several open sessions. If it fails, show the error; do not retry with a guessed
   `--session`.

With no `$ARGUMENTS` at all, ask what the note should say rather than writing an empty one.
