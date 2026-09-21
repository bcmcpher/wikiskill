"""data-science-harness `bench/` fixtures, read where they live.

DSH maintains its own routing suites and rubrics under `bench/`, and its README is explicit about
the terms: a consumer reads them in place, modifies nothing, and must not ask for new fields.
"Every expected outcome here is derived from the repository, which is what makes it checkable
rather than hand-maintained." So this module translates rather than negotiates — anything wikiskill
needs and DSH does not declare, wikiskill supplies here.

Two of those:

- **`split`.** DSH declares no train/validation/test split, and says outright that a runner needing
  one supplies it on its own side. Every task therefore lands in one split, chosen by the caller.
- **`expected_delegates_to` names plugins, not agents.** `[datalad]` means "the agent the datalad
  plugin provides". Resolved against the collection's own components when there is one, because
  that is the same repository DSH derives its ground truth from; otherwise by DSH's own naming
  convention, which is recorded as an assumption rather than hidden.

Rubrics need no translation at all: `bench/rubrics/*.yaml` is already the shape `wikiskill.rubric`
reads, which is why a task's `rubric:` can point straight at one.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover - typing only
    from ..collection import Collection

#: Where a DSH task lands when nothing says otherwise. DSH declares no splits, and inventing per
#: task would be wikiskill deciding something about someone else's fixture.
DEFAULT_SPLIT = "val"

#: How DSH names the agent a plugin provides, used only when no collection can answer better.
DOER_SUFFIX = "-doer"


class AdapterError(Exception):
    """A fixture that is recognisably DSH's but cannot be translated."""


def is_dsh_document(document: Any) -> bool:
    """Whether this is a DSH `bench/tasks` file rather than a wikiskill suite.

    Recognised by the fields DSH has and wikiskill does not: a `probe`, and tasks that state their
    expectation as `expected_skill`. Checking both keeps a wikiskill suite that happens to mention a
    probe from being rewritten.
    """
    if not isinstance(document, dict):
        return False
    tasks = document.get("tasks")
    if not isinstance(tasks, list) or not tasks:
        return False
    declares = any(
        isinstance(task, dict) and ("expected_skill" in task or "expected_delegates_to" in task)
        for task in tasks
    )
    return declares and "probe" in document


def agent_names(plugin: str, collection: Collection | None) -> list[str]:
    """The agents a plugin provides, as `<plugin>/<agent>`.

    The collection is asked first: it reads the same repository DSH derives its ground truth from,
    so it knows whether `project` delegates to `coordinator` rather than `project-doer`.
    """
    if collection is not None:
        found = [
            component.name
            for component in collection.discover()
            if component.kind == "agent" and component.plugin == plugin
        ]
        if found:
            return sorted(found)
    return [f"{plugin}/{plugin}{DOER_SUFFIX}"]


def _task(raw: Any, index: int, *, split: str, collection: Collection | None) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise AdapterError(f"tasks/{index}: must be a mapping")
    task_id = raw.get("id")
    prompt = raw.get("prompt")
    if not isinstance(task_id, str) or not task_id.strip():
        raise AdapterError(f"tasks/{index}: needs an `id`")
    if not isinstance(prompt, str) or not prompt.strip():
        raise AdapterError(f"tasks/{index}: task {task_id!r} needs a `prompt`")

    expect: dict[str, Any] = {}
    if raw.get("expected_skill"):
        expect["skill"] = str(raw["expected_skill"])
    agents: list[str] = []
    for plugin in raw.get("expected_delegates_to") or ():
        agents.extend(agent_names(str(plugin), collection))
    if agents:
        expect["agents"] = agents

    task: dict[str, Any] = {
        "id": task_id,
        "prompt": " ".join(str(prompt).split()),
        "split": split,
    }
    if expect:
        task["expect"] = expect
    if raw.get("rubric"):
        task["rubric"] = str(raw["rubric"])
    return task


def to_suite_document(
    document: Any,
    *,
    collection: Collection | None = None,
    split: str = DEFAULT_SPLIT,
    defaults: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """A DSH `bench/tasks` document as a wikiskill suite document.

    The result goes through `suite.parse` like any other, so DSH's fixtures are held to the same
    checks as a hand-written suite — including the rule that a prompt must not name its own expected
    route, which is a rule DSH states for itself and this is a chance to verify.
    """
    if not isinstance(document, dict):
        raise AdapterError("expected a mapping at the top level")
    tasks = document.get("tasks")
    if not isinstance(tasks, list) or not tasks:
        raise AdapterError("`tasks` must be a non-empty list")

    probe = str(document.get("probe") or "").strip()
    suite = str(document.get("suite") or "").strip()
    name = "-".join(part for part in (probe, suite) if part) or "dsh"

    description = f"data-science-harness {probe or 'bench'} probe"
    if suite:
        description += f", suite {suite}"
    status = document.get("status")
    if status:
        description += f" ({status})"

    built: dict[str, Any] = {
        "suite": name,
        "description": description,
        "tasks": [
            _task(raw, index, split=split, collection=collection) for index, raw in enumerate(tasks)
        ],
    }
    if defaults:
        built["defaults"] = dict(defaults)
    return built
