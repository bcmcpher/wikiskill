"""Python's redaction must agree with the OpenCode logger's: these are `redact.test.ts`'s cases."""

from __future__ import annotations

import pytest

from wikiskill.redact import bound, env_secrets, redact, redact_value


@pytest.mark.parametrize(
    ("text", "kind"),
    [
        ("key=sk-ant-api03-AAAABBBBCCCCDDDDEEEE rest", "api_key"),
        ("sk-AAAABBBBCCCCDDDDEEEEFFFF", "api_key"),
        ("AKIAIOSFODNN7EXAMPLE", "api_key"),
        ("ghp_AAAABBBBCCCCDDDDEEEEFFFFGGGG", "api_key"),
        ("xoxb-1234567890-abcdefghij", "api_key"),
        ("Authorization: Bearer abcdefghijklmnopqrstuvwxyz12", "token"),
        ("eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NX0.dBjftJeZ4CVPmB92K27u", "token"),
        ('password="hunter2hunter2"', "password"),
        ("postgres://user:s3cr3tpass@db.internal/app", "url_credentials"),
    ],
)
def test_a_secret_is_replaced_and_counted(text, kind):
    clean, redactions = redact(text)
    assert f"[REDACTED:{kind}]" in clean
    assert any(r["kind"] == kind for r in redactions)


def test_a_private_key_block_is_removed_whole():
    text = "-----BEGIN OPENSSH PRIVATE KEY-----\nbase64here\n-----END OPENSSH PRIVATE KEY-----"
    assert redact(text)[0] == "[REDACTED:private_key]"


def test_url_credentials_keep_the_host_readable():
    clean, _ = redact("postgres://user:s3cr3tpass@db.internal/app")
    assert "db.internal" in clean
    assert "s3cr3tpass" not in clean


def test_ordinary_text_is_left_exactly_alone():
    text = "created 4 files in /home/u/Projects/dsh and ran 12 tests"
    assert redact(text) == (text, [])


def test_environment_values_are_scrubbed_but_paths_and_short_values_are_not():
    secrets = env_secrets(
        {"API_TOKEN": "correct-horse-battery", "HOME": "/home/u", "SHORT": "abc", "DIR": "/opt/x"}
    )
    assert secrets == ["correct-horse-battery"]
    clean, redactions = redact("token correct-horse-battery twice correct-horse-battery", secrets)
    assert clean.count("[REDACTED:env_value]") == 2
    assert redactions == [{"kind": "env_value", "count": 2}]


def test_nested_arguments_are_redacted_in_place():
    value, redactions = redact_value(
        {"cmd": "curl -H 'Authorization: Bearer abcdefghijklmnopqrstuvwxyz12'", "n": 3}
    )
    assert "[REDACTED:token]" in value["cmd"]
    assert value["n"] == 3
    assert redactions == [{"kind": "token", "count": 1}]


def test_bound_cuts_bytes_without_splitting_a_character_and_keeps_the_length():
    text = "é" * 10
    limited = bound(text, 5)
    assert limited.truncated
    assert limited.length == 10
    assert limited.text == "éé"
    assert bound("short", 100).truncated is False
