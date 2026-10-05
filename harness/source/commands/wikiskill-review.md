---
description: >
  Review what one skill or agent did, in evaluations and in real use, and record the lessons as
  wiki patterns. Takes the component, and optionally a collection.
---

Review the component named in `$ARGUMENTS` with the `wikiskill-maintainer` subagent, and have
wikiskill apply its answer. **Do not write wiki files yourself, and do not answer for the
maintainer.** wikiskill checks the maintainer's reply against the evidence it was shown before
anything is written, and that check is the point.

1. Resolve the arguments. The first is the component, for example `datalad/datalad-doer`.
   `--collection` names its collection. With none given, use the collection whose watch list
   names the component, or ask.
2. Take a sample:

   ```
   wikiskill sample <component> --collection <name>
   ```

   If it says there is nothing new to review, report that and stop. Otherwise it prints a sample id
   and the paths of `instructions.md` and `prompt.md` in the sample's directory.
3. Delegate to the `wikiskill-maintainer` subagent. Give it both paths and tell it this: follow
   `instructions.md`, review the evidence in `prompt.md`, and reply with the JSON object only. Do not
   paste the files into the delegation yourself, and do not summarise them.
4. Write the subagent's reply, unchanged, to `reply.json` in the sample's directory, then apply it:

   ```
   wikiskill review <component> --collection <name> --sample <id> --reply-file <dir>/reply.json
   ```

5. If it prints problems, send them to the same subagent, ask for the whole JSON object again, and
   repeat step 4. Do this at most twice. If the reply still fails, report the last problems; the
   failure is already recorded in the wiki's `log.md`.
6. Report what it printed: the patterns created, updated and retired, and the wiki's path. Then
   stop. Do not edit the component itself: changing a skill is `wikiskill refine`'s job, and only
   when the user asks.
