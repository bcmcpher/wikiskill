"""Component and model names: bare, plugin-qualified, and provider-prefixed.

A claude-plugin source names a component `govern/preregister`; OpenCode reports it as `preregister`;
an evaluation result names a model `ollama/qwen3:30b-a3b` where a raw event says `qwen3:30b-a3b`.
Every comparison between those forms goes through here, so the rule is written once. A caller whose
rule differs on purpose (case-folding, say) says so where it calls.
"""

from __future__ import annotations


def bare(name: str | None) -> str:
    """The last path segment: `preregister` for `govern/preregister`, and "" for no name."""
    return name.rsplit("/", 1)[-1] if name else ""


def qualify(plugin: str | None, name: str) -> str:
    """`plugin/name`, or the bare name when there is no plugin."""
    return f"{plugin}/{name}" if plugin else name


def matches(name: str, wanted: str, *, fold_case: bool = False) -> bool:
    """Whether `name` is the component `wanted` names.

    An unqualified `wanted` matches any plugin's component of that bare name; a qualified one
    matches only itself, so `other/preregister` never answers for `govern/preregister`.
    """
    if fold_case:
        name, wanted = name.lower(), wanted.lower()
    return name == wanted or ("/" not in wanted and bare(name) == wanted)


def model_id(model: str) -> str:
    """The model without its provider: `qwen3:30b-a3b` for `ollama/qwen3:30b-a3b`.

    Only the first segment goes, so `openrouter/meta/llama-3` keeps `meta/llama-3`.
    """
    return model.split("/", 1)[1] if "/" in model else model
