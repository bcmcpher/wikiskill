# Bring your own collection

The [quickstart](quickstart.md) evaluates wikiskill's own skill. This evaluates yours: a Claude Code
plugin marketplace, or an OpenCode skills directory. Do the quickstart first; this assumes a model
that passes preflight.

## 1. Declare the collection

```bash
wikiskill collection init my-skills --source ~/src/my-plugins/plugins
```

`init` detects the layout — a directory of plugins (`claude-plugin`), or `skills/`, `agents/` and
`commands/` at the top level (`opencode`) — lists every component it found, and writes a manifest to
`~/.config/wikiskill/collections/my-skills.toml`. Edit its `[watch]` list to the components you care
about; [`templates/collection.toml`](templates/collection.toml) shows every section a manifest can
have. Evaluation installs the *whole* collection regardless, so a near-miss neighbour is there to
be chosen wrongly.

## 2. Check it before you run anything

```bash
wikiskill collection check my-skills
```

Besides listing components, `check` reads every component the way an evaluation will, and says
three kinds of thing:

- **`frontmatter read leniently`** (`~`) — a line Claude Code accepts but YAML does not, typically
  `argument-hint: [path] — a directory`. It is read as the plain text it was meant to be. Quote the
  value to silence it.
- **`unreadable frontmatter`** (`!`) — frontmatter that cannot be read at all. This fails `check`,
  because an evaluation would stop on it.
- **`plugin paths that resolve to nothing`** (`~`) — a file cited through a plugin variable that is
  not there.

The last needs a word, because it is common. Claude Code expands two variables in a component's
text:

| Variable | Means | So a skill at `stats/skills/plan/` reaches its own `references/x.md` as |
|---|---|---|
| `${CLAUDE_PLUGIN_ROOT}` | the plugin's directory, `stats/` | `${CLAUDE_PLUGIN_ROOT}/skills/plan/references/x.md` |
| `${CLAUDE_SKILL_DIR}` | the skill's own directory, `stats/skills/plan/` | `${CLAUDE_SKILL_DIR}/references/x.md` |

A path written as if the plugin root were the skill's directory, or one that climbs out with `../`,
finds nothing in Claude Code either: the model is pointed at a file and cannot open it. wikiskill
reproduces Claude Code's meaning exactly — it mirrors each plugin into the evaluation and expands
both variables to the installed paths — so a path `check` flags is broken in both harnesses.

## 3. Write a suite

Copy [`templates/suite.yaml`](templates/suite.yaml) somewhere outside the plugin repository and fill
it in. A useful first suite is small: two or three tasks that should reach each skill you care
about, and one near-miss control that should reach nothing. Before you report anything from it, read
[writing and auditing a suite](writing-suites.md): how to tie tasks to the component's rules, and how
to hand-check every verifier.

- **Never name the skill in the prompt.** Ask the way a user would. `suite check` refuses a prompt
  containing the full `plugin/skill` name, and warns about one containing either half. Read each
  warning: a skill is often named after its subject, and only you can tell a mention of the subject
  from an instruction to use the skill.
- **A routing task** declares `expect: { skill: <name> }` and no verifiers. It is judged on the
  model's first activation, and only under ROUTED.
- **A task with an outcome** adds `verifiers` that check the workdir or the answer: `file_exists`,
  `regex` over the final text, a file or the transcript, or a `command` that exits 0. Verifiers
  decide pass or fail under every condition.
- **`requires`** lists commands the task needs. A machine without one skips the task with a reason;
  it is never scored as a failure.

```bash
wikiskill suite check my-suite.yaml
```

Freeze the suite before anyone runs it. Its content is hashed into every run, and runs of different
content are never pooled — an edited prompt is a different experiment.

## 4. Run it

Preflight first, then one task, then the rest:

```bash
wikiskill eval --suite my-suite.yaml --collection my-skills \
  --base-url http://localhost:11434/v1 --models ollama/qwen3:1.7b --preflight-only

wikiskill eval --suite my-suite.yaml --collection my-skills \
  --base-url http://localhost:11434/v1 --models ollama/qwen3:1.7b \
  --task reaches-the-skill --condition routed

wikiskill eval --suite my-suite.yaml --collection my-skills \
  --base-url http://localhost:11434/v1 --models ollama/qwen3:1.7b ollama/ministral-3:3b \
  --condition off,routed,injected
```

What each unit gets:

- a fresh OpenCode session with its own config and data directories, and none of yours
- under ROUTED and INJECTED, the whole collection, with every model pin removed so subagents run on
  the model under test
- read access to its installed skills and their plugins' files, and to nothing else outside its
  working directory; the source repository is never reachable
- no skills at all under OFF — not even OpenCode's own

## 5. Read what it says

`report.md` reports per task, model and condition, and pooled per model and condition. Three
conditions separate two different failures:

- **ROUTED below INJECTED**: the model does well when handed the skill but does not find it. The
  description is the problem — routing loss.
- **INJECTED no better than OFF**: the model finds the text but it does not help. The body is the
  problem — no content value.

Both comparisons need tasks with verifiers. A routing-only task is judged on its route, and a route
is only possible under ROUTED, so it says nothing about the other two conditions.

With one repeat on a handful of tasks, nearly every difference is inside its interval. Run more
repeats, or pool runs from other machines:

```bash
wikiskill leaderboard ~/.local/share/wikiskill/my-skills/evals/<run-a> /path/to/<run-b>
```

Only runs of the same suite content and the same component versions pool; anything else is refused,
with the two hashes that differ.
