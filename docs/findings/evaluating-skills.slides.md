## Suites: what this section covers

- **What a pass rate rests on:** the suite that defines a pass
- **How a suite is built** so that a pass means the rule was kept
- **How to audit one:** do its checks pass right answers and fail wrong ones?

::: notes
This section compares nothing between models. It is about the measuring instrument: every later
comparison is only as good as the checks behind it.
:::

## Terms: suites and checks

| term | what it means here |
|---|---|
| suite | one YAML file of tasks; its hash names the experiment |
| starting state | the files a task begins with (`fixtures`), and commands that build more (`setup`) |
| verifier | a deterministic check: a command, a file that must exist, or a regex |
| negated regex | a check that passes only if its text pattern does not appear |
| judge | a model that grades what no verifier can, on a written scale |
| guard | a deny list that refuses commands, such as calls to real hosts |

::: notes
Verifiers are command (exit status), file_exists and regex; a regex can match the final reply, the
whole transcript or a file. A rubric is the judge's written scale per dimension. `requires` names
the programs a task needs; without them the task is skipped.
:::

## A rate is only as good as its suite

- A pass rate counts verifier verdicts, nothing more
- A suite defines "worked": tasks, starting state, verifiers, an optional judge
- Any edit to the suite file is a new experiment
- Fixes and harder tasks go in a new suite file

::: notes
Reading a result means trusting the suite behind it. The suite hash covers the suite file, so
results pool only across identical suites; `--repeats` is outside the hash. The guide
docs/writing-suites.md covers how to build a suite that deserves that trust, and how to audit one
someone else built.
:::

## Building a suite: the starting point

1. **Rules first:** each hard rule gets a task only it can pass
2. **Starting state** from `setup` or `fixtures`, never the machine
3. **No exits:** empty credentials, real hosts denied
4. **Prompts** never name the component; add a near-miss

::: notes
A task that needs a reachable service points it at a closed local port, so a call fails the same way
every time. Unusual codings in fixtures (age in months, 1 = female) make a recalled convention show
up as a wrong value instead of a lucky guess. `requires` declares the programs a task needs; a task
without them is skipped, not failed.
:::

## Building a suite: the checks

5. **Verify state, not wording:** files, git, command output
6. **A judge** only for what no verifier can see
7. **Hand-check** every task before any run

::: notes
Verifier kinds are command, file_exists and regex, on the final reply, the whole transcript or a
file. Accept both prose and JSON answers. A judge never decides pass or fail and is never a model
under test. The hand check builds a task's starting state, lets you make a correct and a wrong end
state, and runs the task's verifiers on each, with no model involved.
:::

## Auditing someone else's suite

- Each hard rule has a task and a verifier
- Starting state built from scratch; nothing leaves
- Verifiers hand-checked: right passes, wrong fails
- Negated regexes read against real failures
- The judge scores only what verifiers cannot
- Failures read before any rate is reported

::: notes
The guide's eight-point audit checklist, condensed. The two not shown: no prompt names what it should
route to (`suite check` refuses the full name), and every verifier fails at least two plausible
wrong end states, not just one. A reader who only audits needs nothing else from the guide.
:::

## Where evaluation is documented

| document | covers |
|---|---|
| `quickstart.md` | a first run, end to end |
| `bring-your-own-collection.md` | template, `suite check`, first run |
| `writing-suites.md` | building and auditing a suite |
| `data.md` | every file and field a run writes |
| `findings/how-wikiskill-works.md` | conditions, scoring, the gate |

::: notes
All under docs/. The README's "New here?" paragraph points to the suite guide. writing-suites.md
includes the hand-check script.
:::
