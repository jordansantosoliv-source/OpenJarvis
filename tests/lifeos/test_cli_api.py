from __future__ import annotations

import json

import pytest
from click.testing import CliRunner
from tests.agents.fake_engine import FakeEngine

from openjarvis.lifeos.cli import lifeos as lifeos_cli
from openjarvis.lifeos.service import get_lifeos, reset_default_lifeos


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_LIFEOS_HOME", str(tmp_path / "home"))
    reset_default_lifeos()
    yield tmp_path / "home"
    reset_default_lifeos()


def _cli(*args, input=None):
    result = CliRunner().invoke(
        lifeos_cli, list(args), input=input, catch_exceptions=False
    )
    return result


def test_cli_end_to_end(home):
    r = _cli("init")
    assert r.exit_code == 0, r.output
    assert (home / "config" / "lifeos.toml").exists()
    assert (home / "config" / "persona.md").exists()

    assert (
        _cli("add", "goal", "title=Passar em Cálculo", "horizon=short").exit_code == 0
    )
    r = _cli(
        "add",
        "task",
        "title=Lista 3",
        "priority=1",
        "due_date=2026-11-20",
        "project_id=",
    )
    assert r.exit_code == 0, r.output
    r = _cli("list", "task", "--json")
    tasks = json.loads(r.output)
    assert tasks[0]["title"] == "Lista 3" and tasks[0]["priority"] == 1
    assert _cli("done", str(tasks[0]["id"])).exit_code == 0

    r = _cli("add", "task", "priority=9", "title=x")
    assert r.exit_code != 0 and "prioridade" in r.output

    assert "Registrado" in _cli("memory", "add", "Prefere estudar à noite").output
    assert "estudar" in _cli("memory", "search", "estudar").output

    r = _cli(
        "plan", "Física", "Revisar", "Lista", "--start", "2026-11-18", "--every", "2"
    )
    assert "2026-11-20" in r.output

    assert "Relatório matinal" in _cli("review", "morning", "--save").output
    assert _cli("autonomy", "set", "3").exit_code == 0
    assert _cli("autonomy", "grant", "planning_write").exit_code == 0
    r = _cli("autonomy", "grant", "financial")
    assert r.exit_code != 0 and "não pode ser pré-autorizada" in r.output
    assert "Cadeia íntegra" in _cli("audit", "--verify").output

    out = home / "export.json"
    assert _cli("export", str(out)).exit_code == 0
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["memories"][0]["content"] == "Prefere estudar à noite"

    r = _cli("wipe", "--yes")
    assert json.loads(r.output)["tasks"] >= 1


def test_cli_registered_on_main_group():
    from openjarvis.cli import cli

    assert "lifeos" in cli.commands


@pytest.fixture
def client(home):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from openjarvis.server.app import create_app

    engine = FakeEngine(
        [
            {
                "content": "",
                "tool_calls": [
                    {
                        "id": "c1",
                        "name": "lifeos_planner",
                        "arguments": json.dumps(
                            {
                                "action": "add",
                                "entity": "task",
                                "data": {"title": "Comprar livro"},
                            }
                        ),
                    }
                ],
            },
            {"content": "Preparei a tarefa; aguarda sua aprovação."},
        ]
    )
    app = create_app(engine, "fake-model")
    with TestClient(
        app, base_url="http://127.0.0.1:8000", headers={"X-JARVIS-LifeOS": "1"}
    ) as c:
        yield c


def test_api_dashboard_and_crud(client):
    page = client.get("/lifeos")
    assert page.status_code == 200 and "JARVIS LifeOS" in page.text

    r = client.post(
        "/v1/lifeos/items/task", json={"title": "Ler capítulo 2", "priority": 2}
    )
    assert r.status_code == 200
    task_id = r.json()["id"]
    assert client.get("/v1/lifeos/items/task").json()[0]["title"] == "Ler capítulo 2"
    assert client.post(f"/v1/lifeos/tasks/{task_id}/done").json()["status"] == "done"
    assert client.post("/v1/lifeos/items/task", json={"title": ""}).status_code == 400

    m = client.post(
        "/v1/lifeos/memory", json={"content": "Gosta de café", "subject": "bebida"}
    ).json()
    conflict = client.post(
        "/v1/lifeos/memory", json={"content": "Gosta de chá", "subject": "bebida"}
    )
    assert conflict.status_code == 409
    assert client.get("/v1/lifeos/memory?q=café").json()[0]["id"] == m["memory"]["id"]

    assert client.put("/v1/lifeos/autonomy", json={"level": 3}).json()["level"] == 3
    assert client.put("/v1/lifeos/autonomy", json={"level": 9}).status_code == 422
    assert client.post("/v1/lifeos/grants/financial").status_code == 400
    assert (
        "Relatório matinal" in client.get("/v1/lifeos/reviews/morning").json()["text"]
    )
    assert client.get("/v1/lifeos/audit").json()["intact"] is True


def test_api_chat_queues_approval_then_executes(client):
    r = client.post("/v1/lifeos/chat", json={"message": "Anote: comprar livro"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["reply"].startswith("Preparei")
    assert len(body["pending"]) == 1
    lo = get_lifeos()
    assert lo.planner.list("task") == []
    pid = body["pending"][0]["id"]
    assert client.post(f"/v1/lifeos/approvals/{pid}/approve").json()["executed"] is True
    assert [t["title"] for t in lo.planner.list("task")] == ["Comprar livro"]
    sessions = client.get("/v1/lifeos/sessions").json()
    assert sessions[0]["session_id"] == body["session_id"]
