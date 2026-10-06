"""The meta-roles' client: one chat request for an endpoint, `opencode run` for the harness.

No test here calls a model. `request_json` is replaced for the endpoint, and a stub stands in for
`opencode`.
"""

from __future__ import annotations

import json

import pytest

from conftest import write_manifest
from wikiskill import collection as collection_mod
from wikiskill import paths, roles
from wikiskill.runner.preflight import Endpoint


@pytest.fixture
def collection(xdg, plugin_source):
    """A collection whose maintainer has an endpoint and whose proposer is harness-served."""
    write_manifest(
        xdg,
        "dsh",
        f'name = "dsh"\nsources = [{{ path = "{plugin_source}", layout = "claude-plugin", '
        'plugins = ["datalad"] }]\n'
        '[roles.maintainer]\nbase_url = "http://localhost:9/v1"\nmodel = "ollama/qwen3:1.7b"\n'
        'api_key_env = "ROLE_KEY"\n'
        '[roles.proposer]\nmodel = "opencode/big-pickle"\n',
    )
    return collection_mod.load("dsh")


def answering(monkeypatch, status=200, body=None, error=None):
    """Replace the network with one answer, and record what was sent."""
    sent = []

    def fake(url, *, payload=None, api_key=None, timeout=0):
        sent.append({"url": url, "payload": payload, "api_key": api_key, "timeout": timeout})
        if error is not None:
            raise error
        return status, body

    monkeypatch.setattr(roles, "request_json", fake)
    return sent


# --------------------------------------------------------------------------- chat


def test_chat_sends_the_model_s_last_segment_at_temperature_zero(monkeypatch):
    sent = answering(monkeypatch, body={"choices": []})
    messages = [{"role": "user", "content": "Go."}]

    status, _ = roles.chat(
        Endpoint("http://judge.invalid/v1", api_key="k"), "ollama/qwen3:1.7b", messages, timeout=7
    )

    assert status == 200
    assert sent == [
        {
            "url": "http://judge.invalid/v1/chat/completions",
            "payload": {
                "model": "qwen3:1.7b",
                "messages": messages,
                "temperature": 0,
                "stream": False,
            },
            "api_key": "k",
            "timeout": 7,
        }
    ]


def test_chat_lets_an_unreachable_endpoint_through(monkeypatch):
    answering(monkeypatch, error=OSError("refused"))
    with pytest.raises(OSError, match="refused"):
        roles.chat(Endpoint("http://judge.invalid/v1"), "m", [], timeout=1)


# --------------------------------------------------------------------------- endpoint roles


def test_an_endpoint_role_answers_with_the_first_message_content(collection, monkeypatch):
    monkeypatch.setenv("ROLE_KEY", "secret")
    sent = answering(
        monkeypatch, body={"choices": [{"message": {}}, {"message": {"content": "hi"}}]}
    )

    ask, model = roles.role_asker(collection, "maintainer", timeout_s=9)

    assert ask([{"role": "user", "content": "x"}]) == "hi"
    assert model == "ollama/qwen3:1.7b"
    assert sent[0]["api_key"] == "secret"
    assert sent[0]["timeout"] == 9


@pytest.mark.parametrize(
    "answer, expected",
    [
        ({"error": OSError("refused")}, "the maintainer endpoint is unreachable: refused"),
        ({"status": 503, "body": "busy"}, "the maintainer endpoint answered 503: busy"),
        ({"body": {"choices": [{"message": {}}]}}, "the maintainer's reply had no message content"),
    ],
)
def test_an_endpoint_role_that_cannot_answer_is_an_error(collection, monkeypatch, answer, expected):
    answering(monkeypatch, **answer)
    ask, _ = roles.endpoint_asker(collection, "maintainer")
    with pytest.raises(roles.RoleError) as caught:
        ask([{"role": "user", "content": "x"}])
    assert str(caught.value) == expected


def test_an_unconfigured_role_is_an_error(collection):
    with pytest.raises(roles.RoleError, match=r"configures no `\[roles.judge\]`$"):
        roles.role_asker(collection, "judge")


def test_a_harness_served_role_has_no_endpoint(collection):
    with pytest.raises(roles.RoleError, match=r"configures no `\[roles.proposer\]` endpoint"):
        roles.endpoint_asker(collection, "proposer")


# --------------------------------------------------------------------------- harness roles


def test_a_conversation_is_flattened_into_one_prompt_that_forbids_tools():
    prompt = roles.harness_flatten(
        [
            {"role": "system", "content": " Be brief. "},
            {"role": "user", "content": "Go."},
            {"role": "assistant", "content": "No."},
            {"role": "tool", "content": "out"},
        ]
    )

    assert prompt.startswith("Answer in text only. Do not use any tools")
    assert prompt.endswith(
        "# Your instructions\n\nBe brief.\n\n# Input\n\nGo.\n\n"
        "# Your previous reply\n\nNo.\n\n# tool\n\nout\n"
    )


def stub_opencode(tmp_path, reply):
    """Records its argv and config, then answers like `opencode run --format json`."""
    script = tmp_path / "opencode"
    seen = tmp_path / "seen.json"
    event = json.dumps({"type": "text", "part": {"type": "text", "text": reply}})
    script.write_text(
        "#!/usr/bin/env python3\n"
        "import json, os, sys\n"
        f"json.dump({{'argv': sys.argv[1:], 'config': os.environ['OPENCODE_CONFIG_CONTENT'],"
        f" 'xdg': os.environ['XDG_CONFIG_HOME'], 'deny': os.environ['WIKISKILL_GUARD_DENY']}}, open({str(seen)!r}, 'w'))\n"
        f"print({event!r})\n",
        encoding="utf-8",
    )
    script.chmod(0o755)
    return script, seen


def test_a_harness_served_role_is_asked_through_opencode_with_tools_denied(tmp_path):
    script, seen = stub_opencode(tmp_path, '{"ok": true}')
    guard = tmp_path / "guard.ts"
    guard.write_text("// guard", encoding="utf-8")
    ask = roles.harness_asker("opencode/big-pickle", executable=str(script), guard=guard)

    reply = ask([{"role": "system", "content": "Be brief."}, {"role": "user", "content": "Go."}])

    recorded = json.loads(seen.read_text())
    config = json.loads(recorded["config"])
    assert reply == '{"ok": true}'
    assert recorded["argv"][:6] == ["run", "--format", "json", "--dir", recorded["argv"][4], "-m"]
    assert recorded["argv"][6] == "opencode/big-pickle"
    assert "# Your instructions\n\nBe brief." in recorded["argv"][7]
    assert config["permission"]["edit"] == "deny"
    assert config["plugin"] == [str(guard)], "bash stays declared, and the guard refuses it all"
    assert config["mcp"] == {}
    assert json.loads(recorded["deny"]) == ["*"]
    assert not paths.config_home().is_relative_to(recorded["xdg"]), "an isolated config root"


def test_a_role_without_an_endpoint_uses_the_harness(collection):
    _, model = roles.role_asker(collection, "proposer")
    assert model == "opencode/big-pickle"


def test_a_harness_role_that_says_nothing_is_an_error(tmp_path):
    script = tmp_path / "opencode"
    script.write_text("#!/bin/sh\necho 'model not found' >&2\n", encoding="utf-8")
    script.chmod(0o755)
    with pytest.raises(roles.RoleError, match=r"gave no answer.*model not found"):
        roles.harness_asker("opencode/nope", executable=str(script))(
            [{"role": "user", "content": "x"}]
        )


def test_no_role_runs_through_the_harness_without_the_guard(tmp_path):
    with pytest.raises(roles.RoleError, match="guard plugin is missing"):
        roles.harness_asker("opencode/big-pickle", guard=tmp_path / "absent.ts")
