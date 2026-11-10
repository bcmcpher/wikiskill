"""Task suites: the declarative fixtures an explicit evaluation runs.

A suite is data. Adding a task changes a YAML file and nothing else, which is why the checks live
here rather than in each caller: the schema covers shape, and this module covers what a schema
cannot say — ids are unique within the suite, every task states how it will be judged, a prompt
never names what it is supposed to route to, and a verifier's pattern compiles and its path stays
inside the workdir.

Nothing here executes a task or touches a collection's source tree.
"""

from __future__ import annotations

import dataclasses
import json
import os
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator

from . import adapters, paths
from .errors import WikiskillError

#: Used when neither the task nor the suite's `defaults` says otherwise.
DEFAULT_REPEATS = 3
DEFAULT_TIMEOUT_S = 900
DEFAULT_MAX_STEPS = 40

#: Environment the runner sets to isolate a unit. A suite may not override it.
RESERVED_ENV_PREFIXES = ("XDG_", "OPENCODE_", "WIKISKILL_")

#: What a secret may not name, on either harness: every variable a runner sets or relies on to
#: isolate a unit or route it to its model. Secrets are removed last, so withholding one of these
#: would undo the isolation, and a Claude Code session would run against the real `~/.claude`.
RESERVED_SECRET_PREFIXES = (*RESERVED_ENV_PREFIXES, "CLAUDE_CODE_", "ANTHROPIC_")
RESERVED_SECRET_NAMES = frozenset(
    {"CLAUDE_CONFIG_DIR", "CLAUDECODE", "DISABLE_AUTOUPDATER", "HOME", "PATH"}
)
#: The deliberate exception. With `--base-url` a Claude Code unit authenticates with the endpoint's
#: own token, so a suite may keep a hosted Anthropic key for its grader. `eval` refuses it as a
#: secret when there is no `--base-url`, because then the session needs it.
SECRET_EXCEPTIONS = frozenset({"ANTHROPIC_API_KEY"})

SPLITS = ("train", "val", "test")
VERIFIER_KINDS = ("command", "file_exists", "regex")

_WORD = re.compile(r"[a-z0-9]+")


class SuiteError(WikiskillError):
    """A suite file is missing, unparseable, or invalid. Carries every problem found."""

    def __init__(self, path: Path | None, problems: Sequence[str]) -> None:
        self.path = path
        self.problems = list(problems)
        where = f"{path}: " if path else ""
        joined = "\n  - ".join(self.problems)
        super().__init__(f"{where}invalid task suite\n  - {joined}")


# --------------------------------------------------------------------------- schema


@lru_cache(maxsize=1)
def load_schema() -> dict[str, Any]:
    with paths.suite_schema_path().open(encoding="utf-8") as handle:
        return json.load(handle)


@lru_cache(maxsize=1)
def _validator() -> Draft202012Validator:
    schema = load_schema()
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


def schema_errors(document: Any) -> list[str]:
    """Schema complaints about a whole suite document, outermost path first."""
    problems = []
    for error in sorted(_validator().iter_errors(document), key=lambda e: list(e.absolute_path)):
        location = "/".join(str(part) for part in error.absolute_path) or "<suite>"
        problems.append(f"{location}: {error.message}")
    return problems


# --------------------------------------------------------------------------- model


@dataclass(frozen=True)
class Verifier:
    """One deterministic check. Verifiers decide pass or fail; a rubric only scores dimensions."""

    kind: str
    run: str | None = None
    expect_exit: int = 0
    path: str | None = None
    pattern: str | None = None
    target: str = "final_text"
    negate: bool = False
    #: command: `json` when stdout is a structured result rather than something to ignore.
    result: str | None = None
    #: command, with a result: ``(field, accepted values)`` pairs, in the order the suite gave them.
    pass_when: tuple[tuple[str, tuple[Any, ...]], ...] = ()
    #: command, with a result: the numeric field a report averages.
    score: str | None = None

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> Verifier:
        return cls(
            kind=raw["kind"],
            run=raw.get("run"),
            expect_exit=int(raw.get("expect_exit", 0)),
            path=raw.get("path"),
            pattern=raw.get("pattern"),
            target=raw.get("target", "final_text"),
            negate=bool(raw.get("negate", False)),
            result=raw.get("result"),
            pass_when=tuple(
                (name, tuple(values)) for name, values in (raw.get("pass_when") or {}).items()
            ),
            score=raw.get("score"),
        )


@dataclass(frozen=True)
class Route:
    """What a correct run activates. Empty when the task is judged only by verifiers or a rubric."""

    skill: str | None = None
    agent: str | None = None
    command: str | None = None
    agents: tuple[str, ...] = ()

    def __bool__(self) -> bool:
        return bool(self.skill or self.agent or self.command or self.agents)

    def names(self) -> list[str]:
        """Every component this route names, in a stable order."""
        found = [n for n in (self.skill, self.agent, self.command) if n]
        found.extend(self.agents)
        return found

    @property
    def primary(self) -> str | None:
        """The component whose activation `route@1` is measured against."""
        return self.skill or self.command or self.agent

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> Route:
        return cls(
            skill=raw.get("skill"),
            agent=raw.get("agent"),
            command=raw.get("command"),
            agents=tuple(raw.get("agents", ())),
        )


@dataclass(frozen=True)
class Task:
    """One evaluation task, with the suite's defaults already folded in."""

    id: str
    prompt: str
    split: str
    expect: Route = field(default_factory=Route)
    verifiers: tuple[Verifier, ...] = ()
    rubric: str | None = None
    fixtures: str | None = None
    requires: tuple[str, ...] = ()
    guard_deny: tuple[str, ...] = ()
    #: Environment set in the unit's harness process, its setup and its command verifiers, as sorted
    #: ``(name, value)`` pairs, unexpanded. Use `resolved_env` for the values a process sees.
    env: tuple[tuple[str, str], ...] = ()
    #: Host variables only command verifiers receive: the suite default's joined with the task's.
    secrets: tuple[str, ...] = ()
    #: Every secret the suite declares, on any task, set at load. Withheld from this task's session
    #: too, because a secret another task declares is still on the host this session runs on.
    suite_secrets: tuple[str, ...] = ()
    #: Shell commands that build the workdir's starting state before the session.
    setup: tuple[str, ...] = ()
    followups: tuple[str, ...] = ()
    repeats: int = DEFAULT_REPEATS
    timeout_s: int = DEFAULT_TIMEOUT_S
    max_steps: int = DEFAULT_MAX_STEPS

    def resolved_env(self) -> dict[str, str]:
        """`env` with `~` and `$VAR` expanded against the host, so `PATH: "~/venv/bin:$PATH"` works.

        Expanded here rather than at load, so `run.json` records what the suite said and never the
        value of a variable it pulled in.
        """
        return {name: os.path.expandvars(os.path.expanduser(value)) for name, value in self.env}

    def secret_env(self) -> dict[str, str]:
        """Each declared secret that is set on the host, with its value. Read when needed, never
        stored, so the value reaches a verifier and a redaction list and nothing else."""
        return {name: os.environ[name] for name in self.secrets if name in os.environ}

    @property
    def withheld(self) -> tuple[str, ...]:
        """What this task's harness, setup and `requires` check may not see: its own secrets and
        every other secret the suite declares."""
        return tuple(dict.fromkeys([*self.secrets, *self.suite_secrets]))

    def withheld_values(self) -> tuple[str, ...]:
        """The host value of each withheld name that is set, longest first: what no record of
        this task may show. A verifier gets only `secret_env`, but a session could still read
        another task's value from the host, so every one is redacted."""
        return host_values(self.withheld)

    @property
    def judged(self) -> bool:
        """Whether anything at all decides this task's outcome."""
        return bool(self.expect) or bool(self.verifiers) or self.rubric is not None


@dataclass(frozen=True)
class Suite:
    """A loaded, validated suite."""

    name: str
    tasks: tuple[Task, ...]
    description: str | None = None
    path: Path | None = None
    #: Things worth a reader's judgement that are not reasons to refuse the suite.
    warnings: tuple[str, ...] = ()

    @property
    def root(self) -> Path:
        """Directory that `fixtures` and `rubric` paths are relative to."""
        return self.path.parent if self.path else Path.cwd()

    def task(self, task_id: str) -> Task:
        for task in self.tasks:
            if task.id == task_id:
                return task
        raise KeyError(task_id)

    def split(self, name: str) -> list[Task]:
        return [t for t in self.tasks if t.split == name]

    @property
    def secrets(self) -> tuple[str, ...]:
        """Every secret any task declares: what a process tied to no one task must not see."""
        return declared_secrets(self.tasks)


def host_values(names: Iterable[str]) -> tuple[str, ...]:
    """The host value of each of ``names`` that is set, each once, longest first, so a value that
    contains another is redacted whole."""
    values = {os.environ[name] for name in names if os.environ.get(name)}
    return tuple(sorted(values, key=len, reverse=True))


def declared_secrets(tasks: Iterable[Task]) -> tuple[str, ...]:
    """Every secret these tasks declare, each once, in the order first declared."""
    return tuple(dict.fromkeys(name for task in tasks for name in task.secrets))


# --------------------------------------------------------------------------- leak check


def _words(text: str) -> list[str]:
    """Lowercase alphanumeric words. `dataset-release` and `dataset release` read the same."""
    return _WORD.findall(text.lower())


def _mentions(prompt_words: Sequence[str], term: str) -> bool:
    """Whether the prompt contains ``term`` as a whole run of words."""
    needle = _words(term)
    if not needle:
        return False
    span = len(needle)
    return any(
        list(prompt_words[i : i + span]) == needle for i in range(len(prompt_words) - span + 1)
    )


def leak_terms(name: str) -> list[str]:
    """The identifiers a prompt must not contain for an expected route ``name``.

    A component is named `<plugin>/<component>`, and a prompt that says either half is worth
    noticing. The full slug is first so the report names the most specific match.
    """
    parts = [part for part in name.split("/") if part]
    terms = [name] if len(parts) > 1 else []
    terms.extend(reversed(parts))
    return list(dict.fromkeys(terms))


def prompt_leaks(task: Task) -> tuple[list[str], list[str]]:
    """Expected-route identifiers this task's prompt names: ``(certain, suspected)``.

    The qualified slug is certain. Nobody writes `disseminate/reporting-checklist` in a prompt by
    accident, so it is an error.

    A bare half is only suspected, because a component is often named after the thing it is about
    and a plugin is often an ordinary word. Five tasks in data-science-harness's own routing suite
    say "this project", meaning the study, and collide with its `project/` plugin; one asks for a
    "reporting checklist", which is what a journal calls the artefact and what the skill is named
    after. Failing those is how a check gets switched off, so they are warnings that `suite check`
    prints and a reader judges.
    """
    prompt_words = _words(task.prompt)
    certain: list[str] = []
    suspected: list[str] = []
    for name in task.expect.names():
        qualified = "/" in name
        for index, term in enumerate(leak_terms(name)):
            if not _mentions(prompt_words, term):
                continue
            into = certain if qualified and index == 0 else suspected
            if term not in into:
                into.append(term)
    return certain, [term for term in suspected if term not in certain]


# --------------------------------------------------------------------------- verifier checks


def _path_problem(raw: str) -> str | None:
    """Why a verifier path is not usable, or `None` when it is.

    A verifier runs in the task's own workdir, which is the only thing a run may touch. A path that
    is absolute or climbs out of it would reach the machine running the suite, so it is refused when
    the suite is read rather than when the check finally runs, hours into a matrix.
    """
    if raw.startswith("~") or Path(raw).is_absolute():
        return "must be relative to the task's workdir"
    if ".." in Path(raw).parts:
        return "must not climb out of the task's workdir with `..`"
    return None


def verifier_problems(task: Task) -> list[str]:
    """What the schema cannot say about a task's verifiers.

    The schema's `oneOf` covers which fields each kind requires. It cannot compile a regular
    expression, it cannot see that `target: file` needs a `path` naming the file, and it only
    *describes* the rule that a path stays inside the workdir.
    """
    problems: list[str] = []
    for index, verifier in enumerate(task.verifiers):
        where = f"verifier {index}"
        if verifier.kind not in VERIFIER_KINDS:
            expected = ", ".join(VERIFIER_KINDS)
            problems.append(f"{where}: unknown kind {verifier.kind!r}, expected one of {expected}")
            continue
        if verifier.kind == "regex":
            try:
                re.compile(verifier.pattern or "")
            except re.error as exc:
                problems.append(
                    f"{where}: {verifier.pattern!r} is not a valid regular expression: {exc}"
                )
            if verifier.target == "file" and not verifier.path:
                problems.append(
                    f"{where}: `target: file` needs a `path` saying which file to match against"
                )
        if verifier.path is not None:
            trouble = _path_problem(verifier.path)
            if trouble:
                problems.append(f"{where}: path {verifier.path!r} {trouble}")
        problems += [f"{where}: {problem}" for problem in _result_problems(verifier)]
    return problems


def verifier_warnings(task: Task) -> list[str]:
    """What looks wrong in a task's verifiers but may be meant.

    YAML reads a bare `yes`, `no`, `on` or `off` as a boolean, so `pass_when: {usable: [yes]}`
    accepts `true` and never the string `"yes"` a grader prints. A grader may print a real boolean,
    so this is a warning for a reader to judge, not a refusal.
    """
    warnings = []
    for index, verifier in enumerate(task.verifiers):
        for name, accepted in verifier.pass_when:
            flags = [json.dumps(value) for value in accepted if isinstance(value, bool)]
            if flags:
                warnings.append(
                    f"verifier {index}: `pass_when` field `{name}` accepts the boolean "
                    f"{', '.join(flags)}. YAML reads a bare yes, no, on or off as a boolean; "
                    "quote the value if the grader prints a string"
                )
    return warnings


def _result_problems(verifier: Verifier) -> list[str]:
    """`result`, `pass_when` and `score` only mean something on a command that prints a result.

    The schema gives each field its shape; which kind may carry them, and that the other two need
    `result: json`, is said here so the complaint names the field rather than a failed `oneOf`.
    """
    declared = [
        name
        for name, value in (
            ("result", verifier.result),
            ("pass_when", verifier.pass_when),
            ("score", verifier.score),
        )
        if value
    ]
    if not declared:
        return []
    named = ", ".join(f"`{name}`" for name in declared)
    one = len(declared) == 1
    if verifier.kind != "command":
        return [f"{named} {'applies' if one else 'apply'} only to a command verifier"]
    if verifier.result is None:
        need = "needs" if one else "need"
        return [f"{named} {need} `result: json`, or there is no result to read from"]
    return []


def _reserved_secret(name: str) -> bool:
    if name in SECRET_EXCEPTIONS:
        return False
    return name in RESERVED_SECRET_NAMES or name.startswith(RESERVED_SECRET_PREFIXES)


def _refers_to(value: str, name: str) -> bool:
    """Whether ``value`` expands ``$name`` or ``${name}``, as `Task.resolved_env` would."""
    return re.search(rf"\$(?:{name}(?![A-Za-z0-9_])|\{{{name}\}})", value) is not None


def env_problems(task: Task) -> list[str]:
    """What is wrong with a task's `env` and `secrets`: a name the runner owns, or a secret the
    task's own `env` would hand to the session anyway, by name or by expanding it. Any secret the
    suite declares counts, not only the task's own, since every one is withheld from every
    session."""
    problems: list[str] = []
    reserved = sorted(name for name, _ in task.env if name.startswith(RESERVED_ENV_PREFIXES))
    if reserved:
        problems.append(f"sets {', '.join(reserved)}, which the runner owns to isolate the run")
    reserved = sorted(name for name in task.secrets if _reserved_secret(name))
    if reserved:
        problems.append(
            f"declares {', '.join(reserved)} as a secret, a reserved name the runner owns to "
            "isolate the run or route it to its model"
        )
    setting = {name for name, _ in task.env}
    clashing = sorted(set(task.secrets) & setting)
    if clashing:
        problems.append(
            f"declares {', '.join(clashing)} as a secret and also sets it in `env`, which would "
            "give it to the session"
        )
    others = sorted((set(task.withheld) - set(task.secrets)) & setting)
    if others:
        problems.append(
            f"sets {', '.join(others)} in `env`, which another task declares as a secret: every "
            "session runs without it"
        )
    for name, value in task.env:
        for secret in task.withheld:
            if _refers_to(value, secret):
                problems.append(
                    f"sets `env` {name} from the secret {secret}, which would give its value to "
                    "the session"
                )
    return problems


# --------------------------------------------------------------------------- loading


def _as_task(raw: dict[str, Any], defaults: dict[str, Any]) -> Task:
    guard = raw.get("guard") or defaults.get("guard") or {}
    return Task(
        id=raw["id"],
        prompt=raw["prompt"],
        split=raw["split"],
        expect=Route.from_dict(raw.get("expect") or {}),
        verifiers=tuple(Verifier.from_dict(v) for v in raw.get("verifiers", ())),
        rubric=raw.get("rubric"),
        fixtures=raw.get("fixtures"),
        requires=tuple(raw.get("requires") or defaults.get("requires") or ()),
        guard_deny=tuple(guard.get("deny", ())),
        env=tuple(sorted({**(defaults.get("env") or {}), **(raw.get("env") or {})}.items())),
        # Joined rather than replaced: withholding more is never harmful, so a task adding its own
        # secret cannot release one the suite declared for every task.
        secrets=tuple(
            dict.fromkeys([*(defaults.get("secrets") or ()), *(raw.get("secrets") or ())])
        ),
        setup=tuple(raw.get("setup") or defaults.get("setup") or ()),
        followups=tuple(raw.get("followups", ())),
        repeats=int(raw.get("repeats", defaults.get("repeats", DEFAULT_REPEATS))),
        timeout_s=int(raw.get("timeout_s", defaults.get("timeout_s", DEFAULT_TIMEOUT_S))),
        max_steps=int(raw.get("max_steps", defaults.get("max_steps", DEFAULT_MAX_STEPS))),
    )


def parse(
    document: Any,
    *,
    path: Path | None = None,
    collection: Any = None,
    split: str | None = None,
) -> Suite:
    """Validate a already-parsed suite document and build a `Suite`.

    Raises `SuiteError` carrying *every* problem: a contributor fixing a suite should see the whole
    list, not one complaint per run.

    A fixture in another project's format is translated first, then held to exactly these checks.
    That is the point of translating rather than special-casing: a data-science-harness fixture is
    read where it lives and still has to prove its ids are unique and its prompts do not name their
    own expected route.
    """
    if adapters.is_dsh_document(document):
        try:
            document = adapters.to_suite_document(
                document,
                collection=collection,
                split=split or adapters.DEFAULT_SPLIT,
            )
        except adapters.AdapterError as exc:
            raise SuiteError(path, [str(exc)]) from exc

    problems = schema_errors(document)
    if problems:
        raise SuiteError(path, problems)

    defaults = document.get("defaults") or {}
    tasks = [_as_task(raw, defaults) for raw in document["tasks"]]
    # Every task's session runs on the same host, so a secret one task declares is withheld from
    # all of them; only its own task's verifiers receive it.
    everyone = declared_secrets(tasks)
    if everyone:
        tasks = [dataclasses.replace(task, suite_secrets=everyone) for task in tasks]

    warnings: list[str] = []
    seen: dict[str, int] = {}
    for index, task in enumerate(tasks):
        first = seen.setdefault(task.id, index)
        if first != index:
            problems.append(
                f"tasks/{index}: duplicate task id {task.id!r}, already used at tasks/{first}"
            )
        if not task.judged:
            problems.append(
                f"tasks/{index}: task {task.id!r} declares no expected outcome: it needs an "
                "`expect` route, a verifier, or a rubric"
            )
        for problem in verifier_problems(task) + env_problems(task):
            problems.append(f"tasks/{index}: task {task.id!r} {problem}")
        for warning in verifier_warnings(task):
            warnings.append(f"tasks/{index}: task {task.id!r} {warning}")
        certain, suspected = prompt_leaks(task)
        for term in certain:
            problems.append(
                f"tasks/{index}: task {task.id!r} names {term!r} in its prompt, which is its "
                "expected route: the prompt would instruct the route instead of testing it"
            )
        for term in suspected:
            warnings.append(
                f"tasks/{index}: task {task.id!r} says {term!r} in its prompt, part of the name of "
                "its expected route. Check whether it is the route being named or the subject "
                "being described"
            )
    if problems:
        raise SuiteError(path, problems)

    return Suite(
        name=document["suite"],
        tasks=tuple(tasks),
        description=document.get("description"),
        path=path,
        warnings=tuple(warnings),
    )


def load(path: str | Path, *, collection: Any = None, split: str | None = None) -> Suite:
    """Read and validate a suite file. YAML and JSON are both accepted.

    A data-science-harness `bench/tasks` fixture is recognised and translated on the way in, so it
    is read where it lives and nothing is copied or rewritten.
    """
    file_path = Path(path).expanduser()
    try:
        text = file_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise SuiteError(file_path, [f"cannot read suite file: {exc.strerror or exc}"]) from exc
    try:
        document = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise SuiteError(file_path, [f"not valid YAML: {exc}"]) from exc
    if not isinstance(document, dict):
        raise SuiteError(file_path, ["expected a mapping at the top level"])
    return parse(document, path=file_path.resolve(), collection=collection, split=split)


def check(paths_in: Iterable[str | Path]) -> list[tuple[Path, list[str]]]:
    """Validate several suite files. Returns ``(path, problems)`` for the ones that failed."""
    failures = []
    for raw in paths_in:
        try:
            load(raw)
        except SuiteError as exc:
            failures.append((exc.path or Path(raw), exc.problems))
    return failures
