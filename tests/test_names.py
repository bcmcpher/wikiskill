"""The one rule for bare, qualified and model names, as a table."""

from __future__ import annotations

import pytest

from wikiskill import names


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("govern/preregister", "preregister"),
        ("preregister", "preregister"),
        ("a/b/c", "c"),
        ("", ""),
        (None, ""),
        ("Govern/PreRegister", "PreRegister"),
    ],
)
def test_bare_is_the_last_segment(name, expected):
    assert names.bare(name) == expected


@pytest.mark.parametrize(
    ("plugin", "name", "expected"),
    [
        ("govern", "preregister", "govern/preregister"),
        (None, "preregister", "preregister"),
        ("", "preregister", "preregister"),
    ],
)
def test_qualify(plugin, name, expected):
    assert names.qualify(plugin, name) == expected


@pytest.mark.parametrize(
    ("name", "wanted", "fold_case", "expected"),
    [
        # exact
        ("govern/preregister", "govern/preregister", False, True),
        ("preregister", "preregister", False, True),
        # an unqualified wanted name matches any plugin's component of that bare name
        ("govern/preregister", "preregister", False, True),
        ("other/preregister", "preregister", False, True),
        # a qualified one matches only itself: never across plugins, never a bare name
        ("other/preregister", "govern/preregister", False, False),
        ("preregister", "govern/preregister", False, False),
        ("govern/release", "preregister", False, False),
        # case is significant unless folded
        ("Govern/PreRegister", "preregister", False, False),
        ("Govern/PreRegister", "preregister", True, True),
        ("govern/preregister", "GOVERN/PREREGISTER", True, True),
        ("other/preregister", "GOVERN/PREREGISTER", True, False),
    ],
)
def test_matches(name, wanted, fold_case, expected):
    assert names.matches(name, wanted, fold_case=fold_case) is expected


@pytest.mark.parametrize(
    ("model", "expected"),
    [
        ("ollama/qwen3:30b-a3b", "qwen3:30b-a3b"),
        ("qwen3:30b-a3b", "qwen3:30b-a3b"),
        # only the provider is stripped, unlike `bare`, which keeps the last segment alone
        ("openrouter/meta/llama-3", "meta/llama-3"),
    ],
)
def test_model_id_strips_the_provider(model, expected):
    assert names.model_id(model) == expected
    assert names.bare("openrouter/meta/llama-3") == "llama-3"
