from __future__ import annotations

import httpx
import pytest
import respx

from openjarvis.lifeos.system import model_status, ollama_running, resources


def test_resources_are_real_numbers():
    r = resources()
    assert r["cpu_count"] >= 1
    assert 0 <= r["cpu_percent"] <= 100
    assert r["ram_total_gb"] > 0 and 0 < r["ram_percent"] <= 100
    assert r["server_rss_gb"] > 0


@respx.mock
def test_ollama_ps_parsed():
    respx.get("http://ollama.test:11434/api/ps").mock(
        return_value=httpx.Response(
            200,
            json={
                "models": [
                    {"name": "qwen3.5:2b", "size": 3 * 1024**3, "size_vram": 0},
                ]
            },
        )
    )
    models = ollama_running("http://ollama.test:11434")
    assert models == [
        {
            "name": "qwen3.5:2b",
            "size_gb": 3.0,
            "vram_gb": 0.0,
            "processor": "CPU",
            "expires_at": None,
        }
    ]


@respx.mock
def test_ollama_unreachable_returns_none():
    respx.get("http://ollama.test:11434/api/ps").mock(
        side_effect=httpx.ConnectError("x")
    )
    assert ollama_running("http://ollama.test:11434") is None


class _FakeOllama:
    engine_id = "ollama"
    _host = "http://ollama.test:11434"

    def health(self):
        return True


class _Wrapper:
    def __init__(self, inner):
        self._inner = inner

    def health(self):
        return self._inner.health()


@respx.mock
def test_model_status_unwraps_instrumented_engine():
    respx.get("http://ollama.test:11434/api/ps").mock(
        return_value=httpx.Response(200, json={"models": []})
    )
    info = model_status(_Wrapper(_FakeOllama()), "ollama", "qwen3.5:2b")
    assert (
        info["healthy"] is True
        and info["loaded"] == []
        and info["model"] == "qwen3.5:2b"
    )


def test_system_endpoint(tmp_path):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient
    from tests.agents.fake_engine import FakeEngine

    from openjarvis.server.app import create_app

    app = create_app(FakeEngine([{"content": "x"}]), "fake-model")
    with TestClient(app) as client:
        data = client.get("/v1/lifeos/system").json()
        assert data["resources"]["ram_total_gb"] > 0
        assert data["model"]["model"] == "fake-model"
        assert data["speech_input"] is False
        assert client.get("/v1/lifeos/files").json()[0]["name"] == "config"
        assert client.get("/v1/lifeos/files?path=memory").status_code == 403
        assert "lifeos.db" in client.post("/v1/lifeos/backup").json()["files"]
