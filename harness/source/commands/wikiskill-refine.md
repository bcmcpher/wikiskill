---
description: >
  Propose one change to one skill or agent from what its experience wiki has learned, as a patch the
  user reviews. Takes the component, and optionally a collection. Applies nothing.
---

Propose a change to the component named in `$ARGUMENTS` with the `wikiskill-proposer` subagent, and
have wikiskill check and write its answer. **Do not edit the component, do not write the proposal
yourself, and do not answer for the proposer.** wikiskill holds the proposal to the evidence it was
shown before anything is written, and that check is the point.

1. Resolve the arguments. The first is the component, for example `datalad/datalad-doer`.
   `--collection` names its collection. With none given, use the collection whose watch list
   names the component, or ask.
2. Prepare the prompt:

   ```
   wikiskill refine <component> --collection <name> --prepare
   ```

   If it says `no_action` because the wiki holds no pattern, report that and stop: the component
   needs `/wikiskill-review` first. Otherwise it prints a prompt id and the paths of
   `instructions.md` and `prompt.md` in the prompt's directory.
3. Delegate to the `wikiskill-proposer` subagent. Give it both paths and tell it this: follow
   `instructions.md`, read the component, its patterns and every piece of evidence in `prompt.md`,
   and reply with the JSON object only. Do not paste the files into the delegation yourself, and do
   not summarise them.
4. Write the subagent's reply, unchanged, to `reply.json` in the prompt's directory, then check it:

   ```
   wikiskill refine <component> --collection <name> --prompt <id> --reply-file <dir>/reply.json
   ```

5. If it prints problems, send them to the same subagent, ask for the whole JSON object again, and
   repeat step 4. Do this at most twice. If the reply still fails, report the last problems.
6. Report what it printed: the proposal id and the path of its `preview.md`, or `no_action` and the
   reason. Then stop. Nothing has been applied. Testing the proposal is the user's call: `wikiskill
   eval --proposal <id>`, then `wikiskill proposal replay` and `wikiskill proposal decide`.
