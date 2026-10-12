# Evaluate and refine a skill: the whole loop

This guide follows one skill through every stage of wikiskill:

1. Install wikiskill and a model server.
2. Declare the skill's collection, so that a harness can load it.
3. Write the evaluation: the tasks, and the checks that decide pass or fail.
4. Run the evaluation and read its results.
5. Refine the skill from what the results show, and decide whether the change is better.

Each stage explains what wikiskill does, why it does it that way, and what each file holds. The
[quickstart](quickstart.md) is the fast path to a first run. [Bring your own
collection](bring-your-own-collection.md) is the short version of stages 2 to 4. [Writing and
auditing a suite](writing-suites.md) is the checklist for stage 3. This guide connects them and
fills in the background. [What wikiskill saves, and where](data.md) is the reference for every file
format.

## Key terms

This guide uses these terms with one meaning each.

| Term | Meaning |
|---|---|
| **component** | One skill, agent (subagent) or command. wikiskill names it `<plugin>/<name>`, for example `release/changelog`. |
| **collection** | The set of components under test, declared in one manifest file. |
| **manifest** | The TOML file that declares a collection: its sources, what to watch, and its meta-roles. |
| **harness** | The agent program a model runs in: OpenCode or Claude Code. |
| **suite** | A YAML file of tasks that evaluates a collection. |
| **task** | One prompt, its starting state, and the checks that decide its result. |
| **verifier** | A deterministic check that runs after a task: a shell command, a file test or a regular expression. |
| **route** | The component a correct run activates first. A task declares it with `expect`. |
| **condition** | How the collection is offered to the model: OFF, ROUTED or INJECTED. |
| **unit** | One task, on one model, under one condition, in one repeat. The smallest thing that passes or fails. |
| **run** | One `wikiskill eval` invocation, and the directory that holds its results. |
| **rubric** | A YAML file of quality dimensions that a judge model scores. It never decides pass or fail. |
| **meta-role** | A model that works on wikiskill's behalf: the judge, the maintainer or the proposer. |
| **pattern** | A page in the collection's wiki that records a recurring failure or success, with its evidence. |
| **proposal** | One suggested edit to one component, written by the proposer. wikiskill never applies it for you. |
| **source hash** | The SHA-256 of a component's main file. It identifies one version of the component. |

## The loop at a glance

```
            ┌──────────── your skill files (never written to) ─────────────┐
            │                                                              │
 manifest ──┤  wikiskill eval ──► run (results)  ──► wikiskill review ──► wiki patterns
            │        ▲                                                     │
 suite ─────┘        │                                                     ▼
                     │                                            wikiskill refine
                     │                                                     │
                     └────── wikiskill eval --proposal ◄── proposal p-NNN ◄┘
                                       │
                                       ▼
                     wikiskill proposal replay ──► you decide ──► apply on a branch
```

wikiskill keeps two rules through the whole loop:

- **It never writes into your skill's repository**, except when you ask for a proposal on a new
  branch.
- **A model never makes a final decision.** Verifiers decide pass or fail. You decide whether a
  proposal is accepted.

---

## 1. Install

### 1.1 What you need

| Tool | Version | What it does here |
|---|---|---|
| `git` | any recent | Builds each task's starting state, and holds the wiki's history. |
| [`uv`](https://docs.astral.sh/uv/) | 0.12 tested | Installs wikiskill as a command-line tool. |
| [OpenCode](https://opencode.ai) | 1.18.31 or newer | The default harness that every evaluation unit runs in. |
| [Ollama](https://ollama.com) | 0.34 tested | Serves local models. Any OpenAI-compatible endpoint also works. |

A GPU or Apple Silicon helps a great deal. OpenCode's first turn sends about 6,300 prompt tokens. A
CPU-only laptop can take more than ten minutes to read that turn, which is longer than a unit's
time budget.

### 1.2 Install wikiskill

1. Clone the repository and change into it:

   ```bash
   git clone https://github.com/bcmcpher/wikiskill.git
   cd wikiskill
   ```

2. Install the `wikiskill` command:

   ```bash
   uv tool install .
   ```

3. Confirm that it works:

   ```bash
   wikiskill --version
   ```

If you will pool results with other people, check out the same commit as them. The leaderboard
refuses runs whose suite or component files differ.

### 1.3 Serve a model with enough context

OpenCode needs at least 16k tokens of context. Ollama's default can be 4096 on a machine with little
memory. Preflight (section 4.1) refuses a model that is served with too small a context.

Set the context length **where the Ollama server runs**, not in the shell where you run wikiskill:

- **Linux with systemd:** run `sudo systemctl edit ollama`, add the lines below, then run
  `sudo systemctl restart ollama`.

  ```ini
  [Service]
  Environment="OLLAMA_CONTEXT_LENGTH=16384"
  ```

- **macOS app:** run `launchctl setenv OLLAMA_CONTEXT_LENGTH 16384`, then quit and reopen Ollama.
- **`ollama serve` by hand:** run `OLLAMA_CONTEXT_LENGTH=16384 ollama serve`.

Then pull a model that can call tools:

```bash
ollama pull qwen3:1.7b
```

A model that answers in text instead of calling a tool scores zero for reasons unrelated to any
skill. Preflight detects this and skips the model. The quickstart lists [models tried so
far](quickstart.md#3-serve-a-model-with-enough-context).

### 1.4 Optional: install the logger and the in-harness commands

Evaluation does not need this step. It adds two things to your everyday OpenCode:

- passive logging of every session that activates a watched component;
- the `/wikiskill-review` and `/wikiskill-refine` commands, used in stage 5.

```bash
wikiskill install --harness opencode --scope global --collection my-skills
```

Run it after stage 2, because it needs a collection. For Claude Code, use `--harness claude-code`.

---

## 2. Configure the skill: declare a collection

### 2.1 What a collection is

wikiskill does not evaluate a skill on its own. It evaluates a skill **among its neighbours**,
because in real use the model must pick the right skill from all of them. A collection is that set.
Its manifest says where the files are, which components to watch, and which models fill the
meta-roles.

wikiskill reads two source layouts:

```
claude-plugin layout                    opencode layout
(a Claude Code plugin marketplace)      (an OpenCode config directory)

plugins/                                my-skills/
├── release/                            ├── skills/
│   ├── skills/                         │   └── changelog/
│   │   ├── changelog/                  │       └── SKILL.md
│   │   │   ├── SKILL.md                ├── agents/
│   │   │   └── references/             │   └── release-doer.md
│   │   └── version-bump/               └── commands/
│   │       └── SKILL.md                    └── ship.md
│   ├── agents/
│   │   └── release-doer.md
│   └── commands/
└── review/
    └── skills/ ...
```

Each component's **main file** is the file the harness loads: `SKILL.md` for a skill, and the
Markdown file for an agent or a command. Its YAML frontmatter holds the `name` and the
`description`. The description is what the model reads when it decides which skill to use, so it
controls routing. The body below the frontmatter is the content the model follows.

### 2.2 Create the manifest

```bash
wikiskill collection init my-skills --source ~/src/my-plugins/plugins
```

`init` detects the layout, lists every component it finds, and writes the manifest to
`~/.config/wikiskill/collections/my-skills.toml`. It writes nothing into the source directory.

### 2.3 The manifest's structure

This is a complete manifest. [`templates/collection.toml`](templates/collection.toml) is the
annotated template, and
[`examples/collections/my-plugins.toml`](../examples/collections/my-plugins.toml)
is a worked example.

```toml
name = "my-skills"                  # must match the file name

sources = [
  { path = "~/src/my-plugins/plugins", layout = "claude-plugin" },
  # Narrow a source to some plugins:
  # { path = "...", layout = "claude-plugin", plugins = ["release"] },
]

[watch]                             # what everyday logging records
skills   = ["release/changelog", "release/version-bump"]
agents   = ["release/release-doer"]
commands = []

[targets]                           # the models `eval` runs when you pass no --models
opencode = ["ollama/qwen3:1.7b", "ollama/gemma4"]

[aliases.opencode]                  # model names a component pins, mapped per harness
haiku  = "ollama/qwen3:1.7b"
sonnet = "ollama/qwen3:30b-a3b"

[roles.judge]                       # scores rubric dimensions (section 3.9)
base_url = "http://localhost:11434/v1"
model = "gemma2:2b"
# models = ["gpt-oss:120b", "llama3.3:latest", "nemotron-3.5-lightning:latest"]  # a panel

[roles.maintainer]                  # writes wiki patterns (section 5.2)
base_url = "http://localhost:11434/v1"
model = "qwen3:30b-a3b"
context_tokens = 32768              # optional; shrinks the review prompt to fit

[roles.proposer]                    # writes proposals (section 5.3)
base_url = "http://localhost:11434/v1"
model = "qwen3:30b-a3b"

[logging]
buffer_size = 200                   # events held before an activation, then written with it
output_limit_bytes = 16384          # longer tool output is cut; its length is kept
redact = true                       # environment values and secret-shaped strings are masked
follow_up_turns = 3                 # your messages after a component runs that are logged
```

What each section does:

| Section | Needed for | Notes |
|---|---|---|
| `name`, `sources` | everything | `layout` is `claude-plugin` or `opencode`. |
| `[watch]` | logging | Evaluation ignores it and installs **every** component, so a near-miss neighbour is always present. |
| `[targets]` | convenience | `--models` on the command line overrides it. |
| `[aliases.<harness>]` | components that pin a model | An agent with `model: haiku` runs on the mapped model. Under evaluation, wikiskill removes pins so that subagents run on the model under test. |
| `[roles.judge]` | rubrics | Must never be a model under test. `collection check` refuses the manifest if it is. |
| `[roles.maintainer]` | `wikiskill review` | Not needed if you review inside the harness. |
| `[roles.proposer]` | `wikiskill refine` | Not needed if you refine inside the harness. |
| `[logging]` | logging | Defaults shown above. |

Each role takes `base_url` (an OpenAI-compatible endpoint), `model`, and optionally `api_key_env`
(the name of the environment variable that holds the key). A role with no `base_url` is asked
through `opencode run`, for a model that OpenCode serves itself.

### 2.4 Check the manifest

```bash
wikiskill collection check my-skills
```

`check` reads every component the way an evaluation will. It must end with `ok`. It reports three
kinds of problem:

| Mark | Message | What to do |
|---|---|---|
| `~` | `frontmatter read leniently` | A line Claude Code accepts but YAML does not, such as an unquoted `argument-hint: [path]`. Quote the value. |
| `!` | `unreadable frontmatter` | The evaluation would stop on this component. Fix the YAML. |
| `~` | `plugin paths that resolve to nothing` | A `${CLAUDE_PLUGIN_ROOT}` or `${CLAUDE_SKILL_DIR}` path points to a missing file. It is broken in Claude Code too. |

The two plugin variables mean:

- `${CLAUDE_PLUGIN_ROOT}` is the plugin's directory, for example `release/`.
- `${CLAUDE_SKILL_DIR}` is the skill's own directory, for example `release/skills/changelog/`.

Add `--sync` to also write `runtime.json`, the file the loggers read. Logging needs it; evaluation
does not.

### 2.5 What an evaluation does with the collection

Every unit gets a fresh OpenCode session with its own config, data, state and cache directories.
None of your own settings reach it. Project config, Claude Code discovery and MCP servers are off. A
guard plugin refuses the commands that a task denies. What the model can see depends on the
condition:

| Condition | Collection installed? | What it measures |
|---|---|---|
| **OFF** | No. Not even OpenCode's own skills. | The bare model: the baseline. |
| **ROUTED** | Yes, every component. | Whether the model finds and uses the right component by itself. |
| **INJECTED** | The component's text is put into the context, and loading it is denied. An agent is invoked directly. | The content alone, with routing removed. |

Comparing the conditions separates two different failures:

- **Routing loss** is INJECTED minus ROUTED. The content works, but the model does not find it. The
  description needs work.
- **Content value** is INJECTED minus OFF. A value near zero means the text does not help. The body
  needs work.

Under ROUTED and INJECTED, the unit can read its installed skills and their plugins' files, and
nothing else outside its working directory.

---

## 3. Write the evaluation

This is the stage that decides whether any later number means anything. A pass rate is a count of
verifier verdicts, so it means exactly what the verifiers check and nothing more.

### 3.1 How a unit is scored

Read this first: it decides what kind of task to write.

1. The runner builds the task's working directory: it copies `fixtures`, runs `setup`, then runs
   `git init` (harmless on an existing repository).
2. The model gets the `prompt` in a fresh session, under one condition.
3. The session ends: the model answers, runs out of steps (`max_steps`), or runs out of time
   (`timeout_s`).
4. Every verifier runs in the working directory, in order. All of them run, even after a failure.
5. The unit gets a verdict:
   - **A task with verifiers** passes when every verifier passes. This holds under every condition.
     The route is still recorded, as a separate metric.
   - **A task with no verifiers but an `expect` route** passes when the first component the model
     activated is the expected one. This is `route@1`. It is measured only under ROUTED, because
     the route is impossible under OFF and denied under INJECTED.
   - **A task with neither** is "not measured". It is never reported as zero.
6. Over repeats, a task passes on a model and condition when it passes in more than half of its
   repeats. A tie counts as a failure.

A unit that did not run is never a failure. Its outcome says why:

| Outcome | Meaning | Counted in the pass rate? |
|---|---|---|
| `completed` | The session ended normally. Verifiers decide. | Yes |
| `step_exhausted` | The model used up `max_steps` tool calls. | Yes |
| `permission_blocked` | The model tried something the guard denied. | Yes |
| `tool_call_as_text` | The model wrote a tool call as text instead of making it. | Yes |
| `api_error` | The model endpoint returned an error. | Yes |
| `infra_error` | Setup failed, the harness crashed, or the unit timed out. | No |
| `skipped` | A `requires` tool is missing on this machine. | No |

The report's `pass basis` column says whether each rate is based on `verifier` or `route`. The two
are never compared with each other.

### 3.2 Start from the skill's rules, not from prompts

A good suite tests what the skill adds to a capable model. Before you write any prompt:

1. List the skill's **rules**: what it tells the model to do or not to do that a model without it
   might get wrong.
2. For each rule, find **evidence a verifier can see without a network**: a file, a tag, a commit
   count, a phrase in the reply.
3. Design at least one task that **only the rule can pass**. If a careful model passes every task
   without the skill, OFF and INJECTED tie, and the suite says nothing about the skill.
4. Add **controls**: requests the skill should leave alone.

The running example in this guide is `release/changelog`, a skill that writes changelog entries for
the commits since the last release. Its rules, and what each leaves to check:

| Rule | Evidence a verifier can see | Task that tests it |
|---|---|---|
| Include only commits since the last tag | the pre-tag commit's subject is absent from `CHANGELOG.md` | `notes-since-last-tag` |
| Group entries under `### Added`, `### Changed`, `### Fixed` | those headings in `CHANGELOG.md` | `notes-since-last-tag` |
| Never create a tag or bump the version | `git tag` lists only `v1.0` | every outcome task |
| Never commit; leave the edit for review | the commit count is unchanged | every outcome task |
| Say so when nothing changed; write no empty section | reply says there is nothing new; tree is clean | `nothing-since-tag` |
| (routing) Reach the skill from a plain request | first activation is `changelog` | `asks-for-release-notes` |
| (control) Do not fire on a version bump | `CHANGELOG.md` not created | `bump-is-not-a-changelog` |

Write this mapping in the suite's header comment. It is the first thing a reviewer reads.

### 3.3 The suite file's structure

A suite is one YAML file. [`schemas/task-suite.schema.json`](../schemas/task-suite.schema.json) is
the authority. [`templates/suite.yaml`](templates/suite.yaml) is a template to copy.

**Top level:**

| Field | Required | Type | Meaning |
|---|---|---|---|
| `suite` | yes | id | The suite's name, reported with every result. Letters, digits, `.`, `_`, `-`. |
| `description` | no | string | One sentence: what the suite asks of the collection. |
| `defaults` | no | mapping | Values for every task that does not set its own (below). |
| `tasks` | yes | list | One or more tasks. |

**`defaults`** may set `repeats` (1–100, default 3), `timeout_s` (default 900), `max_steps` (default
40), `requires`, `guard`, `env` and `setup`. How a task's own value combines with the default:

| Field | Task value and default |
|---|---|
| `repeats`, `timeout_s`, `max_steps` | The task's value replaces the default. |
| `setup` | The task's list **replaces** the default list. It does not add to it. |
| `env` | Merged. The task's value wins for a name set in both. |
| `requires`, `guard` | The task's value replaces the default. |

**A task:**

| Field | Required | Type | Meaning |
|---|---|---|---|
| `id` | yes | id | Unique in the suite. Also a directory name. |
| `prompt` | yes | string | The user's message. It must not name the expected component. |
| `split` | yes | `train`, `val` or `test` | The task's role in refinement (section 3.10). |
| `expect` | no | route | The route a correct run takes (below). |
| `verifiers` | no | list | The checks that decide pass or fail (section 3.7). |
| `rubric` | no | path | A rubric file, relative to the suite file (section 3.9). |
| `fixtures` | no | path | A directory copied into the working directory first, relative to the suite file. |
| `setup` | no | list of shell commands | Run in the working directory after fixtures, before the session. |
| `env` | no | mapping | Environment variables for the harness process and the verifiers. |
| `guard` | no | `{deny: [patterns]}` | Commands the session may not run. |
| `requires` | no | list | Commands the task needs. If one is missing, the unit is `skipped`. |
| `repeats`, `timeout_s`, `max_steps` | no | integer | Override the defaults. |
| `followups` | no | list of strings | Scripted user turns. The schema accepts them; the runner does not send them yet. |

**`expect`, the route:**

| Field | Meaning |
|---|---|
| `skill` | The skill that should be activated first. A bare name (`changelog`) or `plugin/name`. |
| `agent` | The agent that should be delegated to first. |
| `agents` | Agents the run should reach at some point. Reported as `capability@k`. |
| `command` | The command that should run. |

Names compare by their last segment, without case. `release/changelog` and `Changelog` match.

### 3.4 Four kinds of task

**A routing task** has `expect` and no verifiers. It answers one question: does the model reach the
skill from a plain request? It is cheap, and it only means something under ROUTED.

```yaml
- id: asks-for-release-notes
  prompt: We're about to ship. Can you write up what's changed since the last release?
  split: val
  expect: { skill: changelog }
```

**An outcome task** has verifiers, and usually also `expect`. The verifiers decide pass or fail
under every condition, so it is the task that measures content value. The route is reported beside
it.

**A control** is a near-miss: a neighbouring request the skill should leave alone. It has no
`expect` for the skill under test, and its verifiers check that the skill's footprint is absent.
A control catches a description that is too greedy.

**A refusal task** sets up a state where the right action is to stop or to say no, such as a
missing credential or nothing to do. These tasks often show the largest content value, because a
model without the skill tends to push on and invent something.

A useful first suite has two or three routing or outcome tasks per skill, one control, and one
refusal task. Grow it after you have read the first run.

### 3.5 Build the starting state

Each unit starts in an empty directory. Build everything the task needs there.

**Order:** `fixtures` are copied, then `setup` runs, then `git init`. A failing `setup` command
makes the unit `infra_error`. It is never scored as the model's failure.

**Fixtures** are files that are easier to keep on disk than to write with shell commands. Keep them
beside the suite:

```
suites/
├── changelog.yaml
└── fixtures/
    └── changelog-repo/
        ├── CHANGELOG.md          # an existing changelog with a v1.0 section
        └── pyproject.toml        # version = "1.0.0"
```

**Setup** builds state that depends on commands, such as git history. Pass the git identity on the
command line, because the unit's environment does not have your `~/.gitconfig`:

```yaml
setup:
  - git init -q
  - git add -A && git -c user.name=t -c user.email=t@example.invalid commit -qm "Initial import"
  - git -c user.name=t -c user.email=t@example.invalid commit -q --allow-empty -m "Add legacy importer"
  - git tag v1.0
  - 'git -c user.name=t -c user.email=t@example.invalid commit -q --allow-empty -m "feat: add CSV export"'
  - 'git -c user.name=t -c user.email=t@example.invalid commit -q --allow-empty -m "fix: handle empty rows"'
```

Follow these rules for the starting state:

- **Build state; do not assume it.** Nothing may depend on the machine that runs the suite, except
  through `requires`.
- **Close every way out.** Set every credential the skill might use to `""` in `env`. List real
  hosts and publishing commands in `guard.deny`. When a task needs a token that looks valid, point
  the service's URL at a closed local port, so the call fails like an outage.
- **Make guesses visible.** If common practice could give the right answer by luck, choose values
  that differ from common practice. A model that guesses then gives a wrong value.
- **Supply what a person would.** No one answers questions during a run. Put every fact the task
  means to supply in the prompt or a fixture.
- **Reproduce the paths the skill expects.** A skill that runs `plugins/<plugin>/scripts/x.sh` by a
  relative path finds nothing in a fresh directory. Link `plugins` to where the run installs the
  collection. Under OFF the link is broken, which is correct.

`guard.deny` takes glob patterns, matched against the whole shell command. `*` matches anything
and `?` matches one character:

```yaml
guard: { deny: ["git push*", "git tag*", "curl *", "gh release*"] }
```

The runner already denies by default anything that leaves the sandbox. `guard.deny` adds the
task's own rules on top. A denied command gives the unit `permission_blocked`, which is scored.

### 3.6 Write the prompts

- **Ask the way a user would**, in a user's words and with a user's vagueness.
- **Never name the component.** A prompt that names its route instructs the model instead of
  testing it. `suite check` refuses a prompt that contains the full `plugin/name`. It warns when a
  prompt contains either half. Read each warning yourself. A skill is often named after the thing a
  user would mention, such as "changelog". The prompt in this guide says "what's changed since the
  last release" instead.
- **Give the task one clear end.** "Update the changelog" ends in a file. "Tell me about the
  changelog" ends in a reply. Choose, and write verifiers for that end.

### 3.7 Write the verifiers

Verifiers run in the unit's working directory after the session ends. There are three kinds, and
every kind accepts `negate: true`, which passes when the check does **not** hold.

**`command`** runs a shell command and passes when its exit code equals `expect_exit` (default 0).

| Field | Meaning |
|---|---|
| `run` | The command. It runs through the shell, in the working directory, with the task's `env`. |
| `expect_exit` | The exit code that counts as a pass. Default 0. |

A command has 120 seconds. Use it for anything about state: git, files, JSON.

**`file_exists`** passes when `path` exists. `path` is relative to the working directory. An
absolute path, a path that starts with `~`, or a path that contains `..` is refused when the
suite loads.

**`regex`** searches for a Python regular expression with `re.search`.

| Field | Meaning |
|---|---|
| `pattern` | The regular expression. |
| `target` | `final_text` (default): the model's last answer. `transcript`: all text of every session in the unit, subagents included. `file`: the file at `path`. |
| `path` | Required when `target` is `file`. A missing file fails the check. |

No regex flags are set. Put flags inside the pattern: `(?i)` ignores case, `(?m)` makes `^` and `$`
match at each line, and `(?s)` lets `.` match a newline.

Verifiers for common checks:

| Check | Verifier |
|---|---|
| A file was written | `{ kind: file_exists, path: CHANGELOG.md }` |
| A file was **not** written | `{ kind: file_exists, path: CHANGELOG.md, negate: true }` |
| No commit was made | `{ kind: command, run: 'test "$(git rev-list --count HEAD)" = 4' }` |
| No tag was made or moved | `{ kind: command, run: 'test "$(git tag)" = v1.0 && test "$(git rev-list -n1 v1.0)" = "$(git rev-parse HEAD~2)"' }` |
| The tree is unchanged | `{ kind: command, run: 'test -z "$(git status --porcelain)"' }` |
| Only one file changed | `{ kind: command, run: 'test "$(git status --porcelain \| wc -l)" -eq 1' }` |
| A heading is in a file | `{ kind: regex, target: file, path: CHANGELOG.md, pattern: '(?m)^### Fixed' }` |
| A JSON value is right | `{ kind: command, run: 'jq -e ''.version == "1.1.0"'' out.json' }` |
| The reply names something | `{ kind: regex, pattern: 'ZENODO_TOKEN' }` |
| It was never said | `{ kind: regex, target: transcript, pattern: '(?i)deleted', negate: true }` |

Follow these rules for verifiers:

- **Prefer state over words.** A `command` that checks the repository cannot be fooled by phrasing.
  A regex over the reply can be fooled in both directions.
- **Accept every form of a correct answer.** A pattern for `result: unminted` fails a correct reply
  written as JSON, `"result": "unminted"`. Write `result"?:\s*"?unminted` and check both forms by
  hand.
- **Treat a negated regex as risky.** "No DOI in the reply" also fails a reply that only
  *mentions* a DOI: an example, a quote of the skill's template, or reasoning leaked into the
  answer. Anchor the pattern to the form a claim takes, such as `(?m)^doi:` in a structured result.
  When a negated regex fails, read the reply before you report a broken rule.
- **Put one rule in each verifier.** The report shows which verifier failed. One verifier that
  checks three things hides which one broke.
- **Order verifiers so their index is stable.** A critical-check file (section 5.7) names a verifier
  by its 0-based position in the task.

### 3.8 A complete worked suite

```yaml
# changelog: does the changelog skill write correct entries, and stay out of the way otherwise?
#
# Rule → task → verifier
#   only commits since the last tag  → notes-since-last-tag → v2 (no "legacy importer")
#   Keep a Changelog headings        → notes-since-last-tag → v0
#   never commit, never tag          → notes-since-last-tag → v3, v4
#   say so when nothing changed      → nothing-since-tag    → v0, v1
#   control: version bump            → bump-is-not-a-changelog
#
# Hand-checked on 2026-10-12. A correct end state passes every task. Each wrong one fails:
#   notes-since-last-tag     pre-tag commit listed → v2; a commit → v3; a new tag → v4
#   nothing-since-tag        a changelog written anyway → v1; a reply claiming entries → v0
#   bump-is-not-a-changelog  CHANGELOG.md edited too → v1; no bump → v0

suite: changelog
description: Does the changelog skill write correct entries, and stay out of the way otherwise?

defaults:
  repeats: 3
  timeout_s: 600
  max_steps: 20
  guard: { deny: ["git push*", "git tag*", "gh release*"] }
  setup:
    - git init -q
    - git add -A && git -c user.name=t -c user.email=t@example.invalid commit -qm "Initial import"
    - git -c user.name=t -c user.email=t@example.invalid commit -q --allow-empty -m "Add legacy importer"
    - git tag v1.0
    - 'git -c user.name=t -c user.email=t@example.invalid commit -q --allow-empty -m "feat: add CSV export"'
    - 'git -c user.name=t -c user.email=t@example.invalid commit -q --allow-empty -m "fix: handle empty rows"'

tasks:
  - id: asks-for-release-notes
    prompt: We're about to ship. Can you write up what's changed since the last release?
    split: val
    fixtures: fixtures/changelog-repo
    expect: { skill: changelog }

  - id: notes-since-last-tag
    prompt: Add this release's entries to CHANGELOG.md. Don't commit anything; I'll review it.
    split: train
    fixtures: fixtures/changelog-repo
    expect: { skill: changelog }
    verifiers:
      - { kind: regex, target: file, path: CHANGELOG.md, pattern: '(?m)^### (Added|Fixed)' }
      - { kind: regex, target: file, path: CHANGELOG.md, pattern: '(?i)CSV export' }
      - { kind: regex, target: file, path: CHANGELOG.md, pattern: '(?i)legacy importer', negate: true }
      - { kind: command, run: 'test "$(git rev-list --count HEAD)" = 4' }
      - { kind: command, run: 'test "$(git tag)" = v1.0' }

  - id: nothing-since-tag
    prompt: Add this release's entries to CHANGELOG.md. Don't commit anything; I'll review it.
    split: train
    fixtures: fixtures/changelog-repo
    setup:                                   # replaces the default: HEAD is the tag
      - git init -q
      - git add -A && git -c user.name=t -c user.email=t@example.invalid commit -qm "Initial import"
      - git tag v1.0
    verifiers:
      - { kind: regex, pattern: '(?i)(no|nothing) (new )?(changes|commits|entries)' }
      - { kind: command, run: 'test -z "$(git status --porcelain)"' }

  - id: bump-is-not-a-changelog
    prompt: Bump the patch version in pyproject.toml.
    split: val
    fixtures: fixtures/changelog-repo
    verifiers:
      - { kind: regex, target: file, path: pyproject.toml, pattern: 'version = "1\.0\.1"' }
      - { kind: command, run: 'git diff --quiet -- CHANGELOG.md' }
```

Some notes on this suite:

- `nothing-since-tag` has no `expect`. A correct model may or may not load the skill to decide that
  there is nothing to do, and the suite does not care which.
- The control does not name the skill it should avoid. Its second verifier checks the skill's
  footprint: an untouched `CHANGELOG.md`.
- The default `setup` makes the commit count 4. The verifier `test "$(git rev-list --count HEAD)" =
  4` detects any commit the model makes.
- The two `setup` lines with `feat:` and `fix:` are in single quotes. Unquoted, YAML reads
  `-m "feat: add CSV export"` as a mapping, and `suite check` refuses it. Quote any command that
  contains `: `.
- `suite check` passes this suite with one warning: the prompt of `notes-since-last-tag` contains
  `changelog`, half of the route's name. Here the word names the file the user wants edited, not the
  skill, so the warning is accepted. Record a judgement like this in the header comment.

### 3.9 Add a rubric for what verifiers cannot see

Some qualities have no deterministic check. Is each entry worded for a user rather than a developer?
Does the reply name every gap? A rubric lets a judge model score these as separate dimensions. The
scores appear beside the pass rate and are never folded into it.

**The rubric file's structure:**

| Field | Required | Meaning |
|---|---|---|
| `id` | yes | The rubric's name. |
| `dimensions` | yes | A non-empty list of dimensions (below). |
| `judges` | no | `1` (default) or `3`. Use 3 when a dimension is contestable enough to want a majority. |
| `shows` | no | `[delegations]` lets the judge see each handoff the model made, to grade a delegation. |
| `notes` | no | A list of notes for the judge. |

**A dimension:**

| Field | Required | Meaning |
|---|---|---|
| `id` | yes | Unique in the rubric. |
| `type` | no | `scale` (default) or `binary`. |
| `evidence` | no | What the judge compares with what. |
| `anchors` | yes | A mapping of level name to description, with **at least two levels**, worst first. The order is the scale. |

```yaml
id: changelog-quality
judges: 1
dimensions:
  - id: user-facing
    evidence: Compare each new CHANGELOG.md entry with the commit subject it came from.
    anchors:
      copied: Entries repeat the commit subjects, prefixes and jargon included.
      mixed: Some entries are rewritten for a user; others are copied.
      rewritten: Every entry says what changed for a user, in plain words.
  - id: complete
    type: binary
    evidence: Compare the entries with the commits after the v1.0 tag.
    anchors:
      fail: At least one commit after v1.0 has no entry.
      pass: Every commit after v1.0 has an entry.
```

Point a task at it with `rubric: changelog-quality.yaml`, and configure `[roles.judge]` in the
manifest. Then:

- The judge never sees the expected route, and is never a model under test.
- A judge from the same model family as the judged model is marked in the report, beside the other
  judges' majority.
- Read the judge's levels on a few units yourself. A judge is a model, and its anchors are only as
  good as their wording.

### 3.10 Splits, repeats and budgets

- **`split`** gives each task a role. `train` tasks are what refinement learns from. `val` tasks
  tune decisions. `test` tasks are held out to confirm a change at the end. wikiskill records the
  split but does not yet filter evidence by it, so keep the separation yourself: do not let a
  proposal be judged only on the tasks that motivated it. The refine stage's leakage check (section
  5.3) does stop a proposal from copying any task's content.
- **`repeats`** sets how many times each task runs per model and condition. With one repeat, almost
  every difference is noise. Three is the useful minimum. `wikiskill eval --repeats N` overrides the
  suite without changing its hash, so you can add repeats later and still pool.
- **`timeout_s`** includes model loading. Start at 600 for a local model.
- **`max_steps`** caps the tool calls. A model that hits it gets `step_exhausted`, which is scored.
  Set it high enough for a correct run, plus margin.

### 3.11 Check, hand-check, then freeze

1. Validate the suite:

   ```bash
   wikiskill suite check suites/changelog.yaml
   ```

   It checks the schema, compiles every regex, refuses verifier paths outside the working directory,
   refuses prompts that name their route, and prints warnings for you to judge.

2. Hand-check each task. Build its starting state, make an end state by hand, and run its
   verifiers. [Writing and auditing a suite, §7](writing-suites.md#7-hand-check-every-task-before-any-run)
   has a short script that does this. For each task:
   - a correct end state must pass every verifier;
   - at least two plausible wrong end states must each fail. Try a fabricated value, an edit to a
     file that should stay unchanged, and the right answer in the wrong form.
3. Record what you hand-checked in the suite's header comment.
4. **Freeze the suite.** Its content is hashed into every run, and runs with different hashes never
   pool. An edited prompt or verifier is a new experiment. To make a suite harder, write a new suite
   file, so that the old runs stay comparable.

---

## 4. Run the evaluation and read the output

### 4.1 Preflight

```bash
wikiskill eval --suite suites/changelog.yaml --collection my-skills \
  --base-url http://localhost:11434/v1 --models ollama/qwen3:1.7b --preflight-only
```

Preflight checks three things for each model: the server answers, the model makes a real tool call,
and the served context is big enough. A model that fails is skipped with a reason. It is not scored
as zero. The first probe loads the model, so it can take a minute. If it times out, add
`--probe-timeout 300`.

### 4.2 Run one task first

```bash
wikiskill eval --suite suites/changelog.yaml --collection my-skills \
  --base-url http://localhost:11434/v1 --models ollama/qwen3:1.7b \
  --task notes-since-last-tag --condition routed --repeats 1
```

Open the unit's transcript and working directory (section 4.4) and confirm that the task ran the way
you meant. Fix the suite now, before the suite is frozen.

### 4.3 Run the full matrix

```bash
wikiskill eval --suite suites/changelog.yaml --collection my-skills \
  --base-url http://localhost:11434/v1 \
  --models ollama/qwen3:1.7b ollama/gemma4 \
  --condition off,routed,injected
```

The number of units is tasks × models × conditions × repeats. The example suite above, on two
models, is 4 × 2 × 3 × 3 = 72 units. Run a long matrix in a `tmux` session.

Options that change the result:

| Option | Effect |
|---|---|
| `--condition` | Any of `off`, `routed`, `injected`, comma-separated. |
| `--repeats N` | Overrides the suite's repeats. Outside the suite hash. |
| `--task ID` | Runs only this task. |
| `--thinking on\|off\|default` | Tells the model whether to reason first. Runs with different settings never pool. |
| `--max-output-tokens N` | Caps one model turn, thinking included. Default 8192. |
| `--harness opencode\|claude-code` | The harness. Default `opencode`. |
| `--workers N` | Units run in parallel. Default 1. |
| `--retries N` | Reruns a unit the harness crashed on. Default 1. Never reruns a failure. |
| `--fill RUN_ID` | Reruns a finished run's `infra_error` and `skipped` units, under its recorded settings. |
| `--no-seed-cache` | Downloads OpenCode's packages again for every unit. |

### 4.4 The run directory's structure

Results go to `~/.local/share/wikiskill/<collection>/evals/<run-id>/`:

```
<run-id>/
├── run.json             what ran: suite hash, component hashes, models, options, preflight
├── results.jsonl        one line per unit
├── report.md            the human-readable report
├── report.json          the same, as data
├── preflight/<model>/   the endpoint checks
└── units/<task>__<model>__<condition>__r<N>/
    ├── work/            the working directory the task ran in (a git repository)
    ├── exports/         OpenCode's full session transcripts
    ├── run.ndjson       the harness's event stream
    └── config/ data/ state/ cache/   the unit's isolated harness directories
```

**`run.json`** makes a run repeatable and poolable. Its key fields:

| Field | Meaning |
|---|---|
| `run_id`, `suite`, `suite_path`, `suite_hash` | Which suite, at which content. |
| `collection`, `harness`, `harness_version`, `wikiskill_version` | Where it ran. |
| `components` | `[{kind, name, source_hash}]`: the exact version of every component. |
| `models`, `conditions`, `tasks` | The matrix. |
| `proposal` | `null`, or the proposal id for a candidate run (section 5.4). |
| `preflight`, `isolation`, `options` | What each model and condition ran under. |
| `outcomes` | A count of units per outcome. |

**`results.jsonl`** has one JSON object per unit. A shortened line:

```json
{"run_id": "01K…", "suite": "changelog", "task_id": "notes-since-last-tag",
 "model": "ollama/qwen3:1.7b", "condition": "routed", "repeat": 1,
 "outcome": "completed", "duration_ms": 41210,
 "tokens": {"input": 7120, "output": 512, "reasoning": 830, "cache_read": 6300},
 "activations": [{"kind": "skill", "name": "changelog"}],
 "expected": {"primary": "changelog", "agents": []},
 "verifiers": [{"kind": "regex", "passed": true, "detail": "/(?m)^### (Added|Fixed)/ found in CHANGELOG.md"},
               {"kind": "regex", "passed": false, "detail": "/(?i)legacy importer/ found in CHANGELOG.md"}],
 "passed": false}
```

`passed` is `null` when a task has no verifiers. `rubric` holds the judges' opinions when the task
has a rubric. [data.md](data.md#evaluation-runs-evals) lists every field.

### 4.5 Read the report

`report.md` has these sections:

- **Pooled per model and condition:** passes out of units, with a 95% interval, for example
  `9/12 (75%, 47-91%)`. The interval is a Wilson interval, which stays honest for small counts and
  for 0% or 100%.
- **Per task, model and condition:** each task's result, its `route@1`, and its `pass basis`.
- **Not run:** every `infra_error` and `skipped` unit, with its reason.

Read the conditions against each other:

| Pattern | Diagnosis | Where to fix |
|---|---|---|
| ROUTED well below INJECTED | The model does not find the skill. | The `description` in the frontmatter. |
| INJECTED no better than OFF | The text does not help the model. | The body of the skill. |
| OFF already near the top | The suite does not need the skill. | The suite: add tasks only the rules can pass. |
| Control fails under ROUTED only | The skill fires where it should not. | The `description`: narrow it. |

Two rates differ only when their intervals do not overlap. Otherwise the report says "no detectable
difference", and you should not rank them.

### 4.6 Read the failures before you report a rate

1. For each failing verifier, open at least one failing unit's `exports/` and `work/`.
2. Decide whether the model broke the rule, or the verifier was wrong. A negated regex that matched
   an example is a verifier fault.
3. Confirm that each condition ran as intended. Under INJECTED, the component's own instructions
   should drive the transcript. Under OFF, no component loads.
4. Count the harness outcomes separately. `permission_blocked`, `step_exhausted` and `infra_error`
   are not task failures; check how many units needed `--retries` or `--fill`.
5. If a verifier is wrong, fix it in a **new** suite file, discard the runs made with the old one,
   and say so in your report.

### 4.7 Pool and compare runs

- **Pool runs** of the same suite and component versions, from any machine:

  ```bash
  wikiskill leaderboard ~/.local/share/wikiskill/my-skills/evals/<run-a> /path/to/<run-b>
  ```

  It refuses runs whose hashes differ, and marks with `≈` every model whose interval overlaps the
  leader's. To share a run, send its `run.json` and `results.jsonl` only.
- **Rebuild a report** from a finished run's files without running anything: `wikiskill report
  <run-id> --collection my-skills`, or pass the run directory. Add `--models-file
  examples/models.toml` to group models by family and size.

---

## 5. Refine the skill from the results

### 5.1 How refinement works

Refinement is a gated loop. Each step is started by you, and each step's output is checked before
anything is written.

```
review    evidence ──► maintainer model ──► wiki patterns        (validated against the evidence)
refine    patterns ──► proposer model   ──► proposal p-NNN       (validated, never applied)
eval      proposal ──► candidate run                             (from a copy of the source)
replay    baseline run + candidate run  ──► recommendation       (per model, per task)
decide    you ──► accept | reject | withdraw                     (recorded in skill-impact.md)
apply     you ──► a branch in your repository                    (opt-in)
```

All of it is stored in the collection's wiki, `~/.local/share/wikiskill/<collection>/wiki/`, which
is a git repository. Every change is a commit, so its history is the audit trail.

You can run review and refine in two ways:

- **From the shell**, with `[roles.maintainer]` and `[roles.proposer]` in the manifest. wikiskill
  calls those models directly.
- **Inside the harness**, with `/wikiskill-review` and `/wikiskill-refine` (installed in section
  1.4). The harness's own subagents answer, and wikiskill validates their replies. No role
  configuration is needed.

### 5.2 Review: turn evidence into patterns

```bash
wikiskill review release/changelog --collection my-skills
```

**What the maintainer sees.** wikiskill builds a digest from the component's evidence:

- `E1`, `E2`, … are evaluation units; `S1`, `S2`, … are live sessions from the logger.
- Each item shows the task, the model, the outcome, which verifiers failed, the tools used in order,
  and the final reply.
- Items are ranked by their strongest signal. From strongest: a note you wrote with `wikiskill
  note`, a file you edited after the component wrote it, the component run again soon after, a
  verifier failure, what you said next, an unscored unit, and a clean pass last.
- A sample holds at most 5 items with a signal and 3 clean ones. Only evidence that no earlier review
  saw is eligible, so each review looks at what is new.
- The prompt is capped in size, and shrinks to fit a maintainer with `context_tokens` below 64k.

Useful options: `--model <m>` reviews only one model's evidence, so a later proposal can target that
model. `--run <id>` limits it to one run. `--resample` includes evidence earlier reviews saw.
`--dry-run` prints the prompt and stops.

**What it writes.** Each pattern is one page, `wiki/patterns/<slug>.md`:

```markdown
---
slug: changelog-includes-pre-tag-commits
title: Includes commits from before the last tag
component: release/changelog
cause: The skill says "since the last release" but never says how to find the last tag.
trigger: A repository whose history continues past an older tag.
status: active
evidence: [{run_id: 01K…, task_id: notes-since-last-tag, condition: injected, repeat: 2, model: ollama/qwen3:1.7b}]
models: [ollama/qwen3:1.7b]
harnesses: [opencode]
source_hashes: [sha256:9b1e…]
universal: false
created: 2026-10-12
updated: 2026-10-12
maintainer: qwen3:30b-a3b
---

## Observation
…

## Suggestion
…

## Updates
…
```

The scope fields (`models`, `harnesses`, `source_hashes`, `universal`) are computed from the cited
evidence, not from the maintainer's claims. A pattern seen on one model is scoped to that model.

The wiki also keeps `index.md` (the active patterns), `log.md` (one entry per review, failed ones
included), and `components/<name>.md` (each component's patterns and history).

**Inside the harness**, run `/wikiskill-review release/changelog`. It calls `wikiskill sample` to
save the prompt, delegates to the `wikiskill-maintainer` subagent, and applies the reply with
`wikiskill review … --sample <id> --reply-file <path>`. The validation is the same.

**Live corrections** feed the same review. During everyday use, record what a skill got wrong:

```bash
wikiskill note "listed the v0.9 commits again" --component changelog
```

A note is the strongest signal a review ranks.

### 5.3 Refine: propose one patch

```bash
wikiskill refine release/changelog --collection my-skills
```

If the wiki holds no active pattern for the component, refine answers `no_action`. Review first.

**What the proposer sees:** the component's full text, its active patterns, the evidence behind
them, and every earlier decision on the component from `skill-impact.md`, rejected proposals
included. It answers with `no_action` or a small set of exact find-and-replace edits.

**What wikiskill checks before it writes anything:**

- The reply is about the one component it was asked about.
- It cites that component's patterns and the evidence labels it was shown, and no others.
- **Leakage:** the added text carries no evaluation content. Task ids, verifier literals of 8 or more
  characters, rubric anchor text, and long user notes from any suite that evaluated the component
  are refused. A skill that has memorised its test is not a better skill. `--allow-leak` accepts a
  match you judge harmless, and records that you did.
- Model-specific advice is marked as such, and rests on patterns scoped to those models.
- The patch applies to your source repository, checked with `git apply --check`, which writes
  nothing.

**The proposal's structure,** `wiki/proposals/p-NNN/`:

| File | Holds |
|---|---|
| `preview.md` | The edit and its reasons, for you to read first. |
| `patch.diff` | The edit as a diff. |
| `rendered/<file>` | The edited file in full. |
| `proposal.json` | The proposer's raw reply. |
| `meta.json` | `component`, `source_path`, `source_hash` (the version it was made from), `candidate_hash` (the version it makes), `description_changed`, `patterns`, `evidence`, `models`, `reason`, `status`. |

`status` moves from `proposed` to `replayed`, then to `accepted`, `rejected` or `withdrawn`.

**Inside the harness**, run `/wikiskill-refine release/changelog`. It runs `wikiskill refine …
--prepare`, delegates to the `wikiskill-proposer` subagent, and validates the reply with `--prompt
<id> --reply-file <path>`.

### 5.4 Evaluate the candidate

The gate compares two ordinary runs of the **same suite** on the **same models and conditions**:

1. **Baseline:** a run of the component at the proposal's `source_hash`. If the skill has not
   changed since your last run, that run is the baseline. Otherwise, run the suite again.
2. **Candidate:** the same suite with the proposal applied:

   ```bash
   wikiskill eval --suite suites/changelog.yaml --collection my-skills \
     --base-url http://localhost:11434/v1 --models ollama/qwen3:1.7b ollama/gemma4 \
     --condition off,routed,injected --proposal p-001
   ```

   The candidate runs from a copy of your source in the run directory, `candidate-source/`. Your
   repository is never written.

Use the same `--repeats` and `--thinking` for both runs.

### 5.5 Replay: get a recommendation

```bash
wikiskill proposal replay p-001 <baseline-run-id> <candidate-run-id>
```

Replay runs nothing. It checks that the two runs are what they claim, then compares them for each
model and each task:

- **Motivating cases** are the tasks behind the patterns the proposal cites. They should improve.
- **The regression bank** is every other task in the suite. It should not get worse.
- **Every task that fell** is listed by itself, never folded into an average.
- **Tolerance:** by default, a fall of more than 1/3 in one task's pass rate on one model stops the
  recommendation. With three repeats, one repeat in three is the noise floor. Change it with
  `--tolerance`.
- **Trigger theft:** with a collection graph (`wikiskill graph build`), a description edit is also
  checked against neighbouring components' routing tasks. A new description must not steal their
  routes.

Replay **recommends acceptance** only when a motivating case improved on some model and no task fell
past the tolerance on any model. It writes `replay.md` and `replay.json` into the proposal
directory. Read them with `wikiskill proposal show p-001`.

### 5.6 Decide and apply

Only you reach a final state:

```bash
wikiskill proposal decide p-001 accept --note "fixes pre-tag leakage on both models; no regressions"
```

The decision is `accept`, `reject` or `withdraw`. Each decision is added to `wiki/skill-impact.md`.
A rejected or withdrawn proposal keeps its full content there, and the next proposer for this
component sees it.

To put an accepted proposal into your repository:

```bash
wikiskill proposal apply p-001             # prints how to apply it; writes nothing
wikiskill proposal apply p-001 --branch    # commits it on a new branch wikiskill/<component>/p-001
```

`--branch` returns you to your branch afterwards. Review and merge the new branch yourself.

`wikiskill proposal list` shows every proposal with its state and recommendation.

### 5.7 Compare many versions

Each version of a component is its source hash, so every run already records which version it
tested.

**Two versions,** in text and in results:

```bash
wikiskill diff release/changelog --list --collection my-skills       # every known version
wikiskill diff release/changelog p-001^ p-001 --collection my-skills # before and after a proposal
wikiskill diff release/changelog run:<run-id> current --collection my-skills
```

A version is `current`, a hash prefix of 7 or more hex digits, a proposal (`p-001` is its candidate,
`p-001^` the version it was made from), or `run:<run-id>`.

**Many versions across models:**

```bash
wikiskill leaderboard <run-id>... --collection my-skills \
  --by-version release/changelog --critical critical.yaml
```

For each model, the version board gives every version's pass rate with its interval, and the best
version. Overall, it ranks by the mean over the models that ran every version, each model weighted
equally. Its rules:

- A version that regresses **any** model is never named best overall.
- A version that fails a **critical check** even once is never named best at all.
- OFF does not load the component, so one OFF run per model serves every version.

A critical-check file is a YAML list. Each entry names a task (or `*` for every task) and a verifier
by its 0-based index:

```yaml
- { task: notes-since-last-tag, verifier: 3 }   # never commit
- { task: "*", verifier: 0 }
```

The board ranks and never decides. A winner still goes through `proposal replay` and `proposal
decide`.

---

## Further reading

- [Quickstart](quickstart.md): a first run on a local model, and a troubleshooting table.
- [Writing and auditing a suite](writing-suites.md): the audit checklist and the hand-check script.
- [What wikiskill saves, and where](data.md): every file format and location.
- [How wikiskill works](findings/how-wikiskill-works.md): the method, conditions and statistics.
- [`schemas/task-suite.schema.json`](../schemas/task-suite.schema.json): the suite format's
  authority.
