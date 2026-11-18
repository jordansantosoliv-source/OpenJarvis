"""Cross-site request forgery and DNS-rebinding protection for LifeOS routes.

Each "attack" test reproduces a request a hostile web page could make from
the user's browser while the local server runs without an API key, and
checks both the HTTP status and that no state changed.
"""

from __future__ import annotations

from datetime import date

import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient  # noqa: E402
from tests.agents.fake_engine import FakeEngine  # noqa: E402

from openjarvis.lifeos.api import CSRF_HEADER  # noqa: E402
from openjarvis.lifeos.service import get_lifeos  # noqa: E402
from openjarvis.server.app import create_app  # noqa: E402

LOCAL = "http://127.0.0.1:8000"
EVIL = "https://evil.example"
# What a hostile page can send without a CORS preflight: no custom header,
# a "simple" content type, its own Origin, and Sec-Fetch-Site: cross-site.
SIMPLE_CROSS_SITE = {
    "Origin": EVIL,
    "Content-Type": "text/plain",
    "Sec-Fetch-Site": "cross-site",
}
GOOD = {CSRF_HEADER: "1"}


@pytest.fixture
def client():
    app = create_app(FakeEngine([{"content": "ok"}]), "fake-model")
    with TestClient(app, base_url=LOCAL) as c:
        yield c


@pytest.fixture
def lo(client):
    return get_lifeos()


# -- the attacks found in the audit -------------------------------------------


def test_cross_site_grant_is_refused(client, lo):
    before = lo.grants()
    r = client.post("/v1/lifeos/grants/memory_write", headers=SIMPLE_CROSS_SITE)
    assert r.status_code == 403
    assert lo.grants() == before


def test_cross_site_task_done_is_refused(client, lo):
    task = lo.planner.add("task", title="Não mexer")
    r = client.post(f"/v1/lifeos/tasks/{task['id']}/done", headers=SIMPLE_CROSS_SITE)
    assert r.status_code == 403
    assert lo.planner.get("task", task["id"])["status"] == "todo"


def test_cross_site_habit_log_is_refused(client, lo):
    habit = lo.planner.add("habit", title="Ler")
    r = client.post(f"/v1/lifeos/habits/{habit['id']}/log", headers=SIMPLE_CROSS_SITE)
    assert r.status_code == 403
    assert lo.planner.habit_rate(habit["id"], today=date.today())["done"] == 0


def test_cross_site_backup_is_refused(client, lo):
    backups = lo.config.folder("backups")
    before = set(backups.iterdir())
    r = client.post("/v1/lifeos/backup", headers=SIMPLE_CROSS_SITE)
    assert r.status_code == 403
    assert set(backups.iterdir()) == before


def test_cross_site_approval_is_refused(client, lo):
    args = {"action": "remember", "content": "injetado"}
    pid = lo.queue_pending(
        "lifeos_memory", args, lo.authorize(None, "lifeos_memory", args)
    )
    r = client.post(f"/v1/lifeos/approvals/{pid}/approve", headers=SIMPLE_CROSS_SITE)
    assert r.status_code == 403
    assert [p["id"] for p in lo.list_pending()] == [pid]
    assert lo.memory.search("injetado") == []


@pytest.mark.parametrize(
    "method,path,body",
    [
        ("POST", "/v1/lifeos/memory", '{"content":"x"}'),
        ("POST", "/v1/lifeos/items/task", '{"title":"x"}'),
        ("POST", "/v1/lifeos/reviews/weekly", '{"notes":""}'),
        ("POST", "/v1/lifeos/chat", '{"message":"oi"}'),
        ("PUT", "/v1/lifeos/autonomy", '{"level":4}'),
        ("DELETE", "/v1/lifeos/grants/report", None),
        ("PATCH", "/v1/lifeos/memory/1", '{"content":"x"}'),
        ("DELETE", "/v1/lifeos/memory/1", None),
        ("DELETE", "/v1/lifeos/items/task/1", None),
    ],
)
def test_every_state_changing_route_requires_header(client, lo, method, path, body):
    r = client.request(
        method, path, content=body, headers={"Content-Type": "application/json"}
    )
    assert r.status_code == 403
    assert CSRF_HEADER in r.json()["detail"]


# -- header present but browser says it is cross-site ---------------------------


def test_foreign_origin_refused_even_with_header(client, lo):
    r = client.post("/v1/lifeos/grants/memory_write", headers={**GOOD, "Origin": EVIL})
    assert r.status_code == 403
    assert "memory_write" not in lo.grants()


def test_null_origin_refused(client):
    r = client.post("/v1/lifeos/backup", headers={**GOOD, "Origin": "null"})
    assert r.status_code == 403


def test_sec_fetch_site_cross_site_refused(client):
    r = client.post(
        "/v1/lifeos/backup", headers={**GOOD, "Sec-Fetch-Site": "cross-site"}
    )
    assert r.status_code == 403


def test_other_local_port_refused(client):
    # e.g. a dev server on localhost:5173 that is in the CORS allow-list
    r = client.post(
        "/v1/lifeos/backup", headers={**GOOD, "Origin": "http://localhost:5173"}
    )
    assert r.status_code == 403


def test_cors_preflight_from_foreign_origin_is_not_allowed(client):
    r = client.options(
        "/v1/lifeos/grants/memory_write",
        headers={
            "Origin": EVIL,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": CSRF_HEADER,
        },
    )
    assert r.headers.get("access-control-allow-origin") != EVIL


# -- DNS rebinding -------------------------------------------------------------------


@pytest.mark.parametrize("path", ["/v1/lifeos/status", "/v1/lifeos/memory", "/lifeos"])
def test_rebinding_host_refused_for_reads(client, path):
    r = client.get(path, headers={"Host": "evil.example"})
    assert r.status_code == 403


def test_rebinding_host_refused_for_writes(client, lo):
    r = client.post(
        "/v1/lifeos/grants/memory_write",
        headers={**GOOD, "Host": "evil.example", "Origin": "http://evil.example"},
    )
    assert r.status_code == 403
    assert "memory_write" not in lo.grants()


def test_extra_hosts_can_be_allowed_explicitly(client, monkeypatch):
    assert (
        client.get(
            "/v1/lifeos/status", headers={"Host": "pc-jordan.lan:8000"}
        ).status_code
        == 403
    )
    monkeypatch.setenv("JARVIS_LIFEOS_ALLOWED_HOSTS", "pc-jordan.lan")
    assert (
        client.get(
            "/v1/lifeos/status", headers={"Host": "pc-jordan.lan:8000"}
        ).status_code
        == 200
    )


# -- legitimate use keeps working ------------------------------------------------------


def test_same_origin_dashboard_request_works(client, lo):
    r = client.post(
        "/v1/lifeos/grants/memory_write",
        headers={**GOOD, "Origin": LOCAL, "Sec-Fetch-Site": "same-origin"},
    )
    assert r.status_code == 200
    assert "memory_write" in lo.grants()


def test_non_browser_client_with_header_works(client, lo):
    task = lo.planner.add("task", title="Via script")
    assert (
        client.post(f"/v1/lifeos/tasks/{task['id']}/done", headers=GOOD).status_code
        == 200
    )


@pytest.mark.parametrize(
    "host", ["localhost:8000", "127.0.0.1:8000", "[::1]:8000", "localhost"]
)
def test_loopback_hosts_accepted(client, host):
    assert client.get("/v1/lifeos/status", headers={"Host": host}).status_code == 200


def test_reads_do_not_need_header(client):
    assert client.get("/v1/lifeos/status").status_code == 200
    assert client.get("/lifeos").status_code == 200


def test_dashboard_sends_the_header(client):
    page = client.get("/lifeos").text
    assert f'h["{CSRF_HEADER}"] = "1"' in page


def test_upstream_routes_are_not_affected(client):
    # The protection is scoped to LifeOS; OpenJarvis' own routes are untouched.
    assert client.get("/v1/models", headers={"Host": "evil.example"}).status_code != 403
