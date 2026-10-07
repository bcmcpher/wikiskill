# Writing and auditing a suite

Every pass rate wikiskill reports is a count of verifier verdicts. A rate means exactly what its
suite's verifiers check, and nothing more. When you read a result, you are trusting the suite. This
guide covers how to build one that deserves that trust, and how to audit one someone else built.

[Bring your own collection](bring-your-own-collection.md) shows the mechanics: a template, `suite
check`, a first run. This guide covers the judgement those steps leave to you. Its examples come
from the data-science-harness pilot's suites in `pilots/`, which are worked examples of everything
below.

## The audit checklist

If you only audit, check these. Each is explained below.

1. **Every hard rule of the component has a task that only the rule can pass**, and a verifier that
   sees the rule kept or broken. The suite's header comment says which is which.
2. **The starting state is built from scratch** by `setup` or `fixtures`. No task depends on the
   machine it runs on, except through `requires`.
3. **Nothing can leave the machine.** Credentials are empty, the guard denies the real hosts, and a
   task that needs a reachable service points it at a closed local port.
4. **No prompt names what it should route to.** `suite check` refuses the full name and warns on
   either half.
5. **Every verifier was hand-checked.** A correct end state passes all of a task's verifiers, and at
   least two plausible wrong ones fail.
6. **Negated regexes were read against real failures.** They match quotes and examples as well as
   claims.
7. **A judge scores only what no verifier can.** It never decides pass or fail, and it is never a
   model under test.
8. **Failures were read before rates were reported.** For each failing verifier, at least one
   transcript was read.

## 1. What a suite is

| file | holds |
|---|---|
| `suite.yaml` | the tasks: prompt, starting state, verifiers, and the route a correct run takes |
| `fixtures/<task>/` | files copied into a task's working directory before `setup` runs |
| `rubric.yaml` | the dimensions a judge scores, for what verifiers cannot see |
| the collection manifest | the components installed, and the judge in `[roles.judge]` |

`schemas/task-suite.schema.json` is the full schema. Defaults apply to any task that does not set
its own: `repeats` 3, `timeout_s` 900 (model loading included), and `max_steps` 40.

**A suite's content is hashed into every run.** Runs of different content never pool, and an edited
prompt or verifier is a different experiment. So:
- Freeze a suite before its first reported run.
- To fix a flawed verifier, discard the runs made with it and say so in the report.
- To make a suite harder, write a new suite file, so the old file's hash and runs stay comparable.
- `eval --repeats N` is outside the hash. You can add repeats without starting a new experiment.

## 2. Start from the component's rules

Do not start from prompts. Start from what the component promises that a capable model without it
would not do. Write each promise down, then ask what it leaves behind that a verifier can see
without a network: a reply, a file, a tag, a commit count.

The archive doer's rules, and what each leaves to check:

| rule | task | verifier |
|---|---|---|
| never fabricate a DOI | every task | no DOI-shaped string in the reply |
| name the missing credential | `mint-without-token` | `ZENODO_TOKEN` appears in the reply |
| deposit only an existing tag | `mint-untagged-version` | `v2.0` not created, `v1.0` not moved |
| never commit | `deposit-without-version` | commit count unchanged |
| `ledger-only` for a relation it cannot write | `relate-without-write-path` | `result: ledger-only`, and a clean tree |

Then make sure some tasks can **only** be passed by following the rules. If a careful model passes
every task without the component, OFF and INJECTED will tie, and the suite says nothing about the
component. The archive suite's OFF control passes about half its units, which is what a careful
model does unaided. Its INJECTED gain comes from the tasks only the doer's rules can pass.

Write the rule-to-verifier mapping in the suite's header comment. It is the first thing an auditor
reads. Every suite in `pilots/` opens this way.

## 3. Build the starting state

Each unit starts in a fresh, empty working directory. `fixtures` are copied in first, then the
`setup` commands run there. A failing `setup` command makes the unit `infra_error`, not a model
failure.

- **Build state; don't assume it.** `git init`, write the files, commit, tag. Use placeholder
  content where nothing reads it. The bids suite's imaging files are empty, because no task without
  a validator opens them.
- **Close every way out.** Set every credential the component might use to `""` in `env`. List the
  real hosts and push commands in `guard: { deny: [...] }`. When a task needs a token that looks
  valid, point the service's URL at a closed local port, so the deposit fails the way an outage
  would. Any DOI in that reply is then invented by definition.
- **Make recalled conventions visible.** If a correct answer could be guessed from common practice,
  pick values that differ from it. The curate suite codes age in months and `1 = female`, so a
  model that assumes the usual coding gets a wrong value instead of a lucky guess.
- **Declare tools in `requires`.** A task whose program is missing is `skipped`, with a reason, and
  never scored. But a run with a skipped unit is incomplete, so check `requires` on every machine
  before a sweep.
- **Reproduce what the component expects to find.** The DSH doers call their toolbox by a path
  relative to the DSH checkout (`plugins/<plugin>/scripts/...`). Their tasks link `plugins` in the
  working directory to where the run installs the collection. Under OFF the link dangles, which is
  correct.

## 4. Write the prompts

- Ask the way a user would, in the user's words.
- **Never name the component**, its skill or its plugin. A prompt that names its route instructs
  the model instead of testing it. `suite check` refuses the full `plugin/name`, and warns on either
  half. Read each warning: a skill is often named after the very thing a user would mention.
- Include a near-miss control: a neighbouring request the component should leave alone.
- Give a headless run what a person would have supplied. No one answers a component's questions
  during a run. Every fact a task means to supply goes in the prompt or a fixture, and anything else
  is meant to stay unknown.

## 5. Write the verifiers

Verifiers run in the working directory after the session, in order, and all of them run. A task
passes when every verifier passes.

| kind | passes when | use it for |
|---|---|---|
| `command` | `run` exits `expect_exit` (0 by default) | state: `test "$(git tag)" = v1.0`, `test -z "$(git status --porcelain)"`, `jq` over a written file |
| `file_exists` | `path`, relative to the working directory, exists | an output the work should produce |
| `regex` | `pattern` matches its `target` | what the reply says |

A `regex` matches one of three targets:
- **`final_text`** (the default): the model's last answer.
- **`transcript`**: every text part of every session, children included. Use it for "was this ever
  said".
- **`file`**: the file at `path`.

`negate: true` flips any verifier: it passes when the check does not hold.

**Prefer state over words.** A `command` that checks the repository cannot be fooled by phrasing. A
regex over the reply can, in both directions.

**Accept every form a correct answer can take.** The archive suite first matched only `result: …`,
and failed correct replies written as JSON (`"result": "unminted"`). Write the pattern for both
forms, and hand-check both.

**Negated regexes are the riskiest verifiers you can write.** "No DOI in the reply" also fails a
reply that *mentions* a DOI without claiming one. In the pilot's sweep, these all failed it:
- A labelled example: "you will get a DOI such as `10.5281/zenodo.1234567`".
- The model quoting the component's own template: "result: valid | invalid | unverified". This was
  4 of the 8 `result: valid` failures on bids.
- Reasoning leaked into the reply. One model, asked not to think, reasoned aloud in its answer
  instead.

Each counted as a broken rule, beside the real fabrications. When a negated regex fails, read the
reply before reporting the rule broken. Where you can, pin the pattern to the structure a claim
takes. For example, `doi:` at the start of a line in the structured result is a claim, and a DOI
mid-sentence is not.

## 6. Add a judge only for what verifiers cannot see

Some qualities have no deterministic check. Is every entry sourced? Does the reply name every gap?
Does a description say more than the column name? A rubric scores these as dimensions, beside the
pass rate and never folded into it. See `pilots/gen-data-dict/rubric.yaml`.

- Each dimension gives the judge `evidence` (what to compare against what), and named `anchors`,
  worst first. The order is the scale.
- `judges: 1` or `3`. Use three when a dimension is contestable enough to want a majority.
- `shows: [delegations]` lets the judge see each handoff, for grading a delegation.
- Declare the judge in the collection's `[roles.judge]`. A judge is never a model under test. A
  judge from the same family as the model it judges is marked in the report, beside the other
  judges' majority.
- Read the judge's levels on a few units by hand. A judge is a model, and its anchors are only as
  good as their wording.

## 7. Hand-check every task before any run

For each task, build its starting state, make the end state by hand, and run its verifiers. A
correct end state must pass every verifier. At least two plausible wrong ones must each fail:
- a fabricated value, or a hint left out
- a file edited that should not be, or a tag moved
- the right answer in the wrong form

This script does it for one task. It needs a reply file holding the final answer you want to test:

```python
# hand_check.py SUITE TASK REPLY: build TASK's starting state, wait while you make an end state, then
# run its verifiers against REPLY as the final answer.
import os, shutil, subprocess, sys, tempfile
from pathlib import Path
from wikiskill import suite
from wikiskill.score.verify import verify_task

suite_file, task_id, reply_file = sys.argv[1:4]
task = next(t for t in suite.load(suite_file).tasks if t.id == task_id)
work = Path(tempfile.mkdtemp(prefix=f"{task_id}-"))
if task.fixtures:
    shutil.copytree(Path(suite_file).parent / task.fixtures, work, dirs_exist_ok=True)
for command in task.setup:
    subprocess.run(command, shell=True, cwd=work, check=True,
                   env={**os.environ, **task.resolved_env()})
input(f"starting state in {work}; make the end state to test, then press Enter")
results, passed = verify_task(task, workdir=work, final_text=Path(reply_file).read_text())
for result in results:
    print("pass" if result.passed else "FAIL", result.detail)
print("task passes" if passed else "task fails")
```

```bash
uv run python hand_check.py pilots/archive-doer/suite.yaml mint-without-token reply.txt
```

On `mint-without-token`, the correct reply `result: unminted` naming `ZENODO_TOKEN` passes. A
fabricated `Your DOI is 10.5281/zenodo.1234567` fails. So does an honest reply that gives that DOI
as an example, which is the negated-regex weakness above, caught before any run. Record what you
hand-checked in the suite's comments.

## 8. After the first run: read before you report

- **Read failures by verifier.** For each verifier that fails, read at least one failing unit's
  transcript (`<run>/units/<unit>/exports/`). A verifier that fails for the wrong reason makes every
  rate built on it wrong.
- **Check the condition really ran.** Under INJECTED, the transcript's messages should come from the
  component's own agent. Under OFF, no component is loaded.
- **Separate the model from the harness.** `permission_blocked`, `step_exhausted` and `infra_error`
  units are not task failures. The leaderboard's "Outcomes and cost" table counts them. A unit the
  harness crashed on is run once more by default, and `eval --fill` reruns a finished run's
  unscored units. Neither ever reruns a unit that failed, and the report counts both, so check how
  many units needed them.
- **Watch the ceiling.** When two or more models pass nearly everything under INJECTED, the suite
  no longer separates them. Write harder tasks in a new suite file.
- **Fix in a new file.** A verifier found wrong is fixed in the suite, and the runs made with the
  flawed version are discarded and named in the report. The archive pilot's first v1 run was
  discarded this way.
