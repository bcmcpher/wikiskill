"""Preflight against a real local HTTP server, so timeouts and disconnects take the socket path.

A mocked `request_json` would pass whatever it was told to raise. The failures preflight must
survive — a model still loading, a server stopped mid-probe — only show up as the exceptions
`urllib` actually raises, so the server here is real and misbehaves on cue.
"""

from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from wikiskill.runner import preflight
from wikiskill.runner.preflight import Endpoint

TOOL_CALL = {
    "choices": [
        {"message": {"tool_calls": [{"function": {"name": "report_colour", "arguments": "{}"}}]}}
    ]
}


class FakeOllama:
    """Serves `/v1/models`, `/v1/chat/completions`, `/api/show` and `/api/ps`, per-path behaviour."""

    def __init__(self) -> None:
        self.delay: dict[str, float] = {}
        self.drop: set[str] = set()
        self.show: dict = {"model_info": {"llama.context_length": 131072}}
        self.ps: dict = {"models": []}
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, format, *args) -> None:
                pass

            def _answer(self, body: dict) -> None:
                path = self.path
                time.sleep(fake.delay.get(path, 0))
                if path in fake.drop:
                    self.close_connection = True
                    return
                data = json.dumps(body).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self) -> None:
                self._answer(fake.ps if self.path == "/api/ps" else {"data": [{"id": "tiny:1b"}]})

            def do_POST(self) -> None:
                self.rfile.read(int(self.headers.get("Content-Length", 0)))
                self._answer(fake.show if self.path == "/api/show" else TOOL_CALL)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        # "ollama" in the URL is what marks an endpoint as Ollama, as the port 11434 would.
        self.endpoint = Endpoint(f"http://localhost:{self.server.server_port}/ollama/v1")

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()


@pytest.fixture
def server(monkeypatch):
    monkeypatch.setenv("OLLAMA_CONTEXT_LENGTH", "16384")
    fake = FakeOllama()
    yield fake
    fake.close()


@pytest.fixture(autouse=True)
def _paths_under_ollama(monkeypatch):
    """The fake serves at the root; strip the `/ollama` marker from every request path."""
    real = preflight.request_json

    def rooted(url: str, **kwargs):
        return real(url.replace("/ollama", ""), **kwargs)

    monkeypatch.setattr(preflight, "request_json", rooted)


def test_a_healthy_model_passes(server):
    result = preflight.check(server.endpoint, "tiny:1b")
    assert result.ok, result.problems
    assert result.details["context_tokens"] == 16384


def test_a_probe_slower_than_its_timeout_is_a_failed_preflight_not_a_crash(server):
    server.delay["/v1/chat/completions"] = 2
    result = preflight.check(server.endpoint, "tiny:1b", probe_timeout=1)
    assert not result.ok
    assert "within 1s" in result.problems[0]
    assert "--probe-timeout" in result.problems[0]


def test_the_probe_timeout_is_separate_from_the_listing_timeout(server):
    """A model load longer than the plain timeout passes when the probe is given room for it."""
    server.delay["/v1/chat/completions"] = 2
    result = preflight.check(server.endpoint, "tiny:1b", timeout=1, probe_timeout=5)
    assert result.ok, result.problems


def test_a_server_that_drops_the_probe_is_a_failed_preflight(server):
    server.drop.add("/v1/chat/completions")
    result = preflight.check(server.endpoint, "tiny:1b")
    assert not result.ok
    assert "did not answer the tool-call probe" in result.problems[0]


def test_a_failing_show_falls_back_to_the_served_context(server):
    server.delay["/api/show"] = 2
    context, source = preflight.ollama_context(server.endpoint, "tiny:1b", timeout=1)
    assert (context, source) == (16384, "OLLAMA_CONTEXT_LENGTH")


def test_a_smaller_trained_context_still_caps_the_served_one(server):
    server.show = {"model_info": {"llama.context_length": 8192}}
    result = preflight.check(server.endpoint, "tiny:1b")
    assert not result.ok
    assert "8192-token context" in result.problems[0]


def test_the_running_servers_context_beats_this_processs_environment(server):
    """The shell running wikiskill says 16384; the server was started without it and serves 4096."""
    server.ps = {"models": [{"name": "tiny:1b", "model": "tiny:1b", "context_length": 4096}]}
    result = preflight.check(server.endpoint, "tiny:1b")
    assert not result.ok
    assert result.details["context_source"] == "the running server"
    assert "4096-token context" in result.problems[0]


def test_another_loaded_models_context_is_not_this_ones(server):
    server.ps = {"models": [{"name": "other:7b", "model": "other:7b", "context_length": 2048}]}
    context, source = preflight.ollama_context(server.endpoint, "tiny:1b", timeout=5)
    assert (context, source) == (16384, "OLLAMA_CONTEXT_LENGTH")
