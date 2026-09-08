"""API-level tests with FastAPI TestClient (sync, no network port needed)."""

import time

from fastapi.testclient import TestClient

from app.main import create_app

TOKEN = "testtoken"


def make_client() -> TestClient:
    return TestClient(create_app(TOKEN))


def auth_headers():
    return {"Authorization": f"Bearer {TOKEN}"}


def test_health_no_auth():
    c = make_client()
    r = c.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_windows_tauri_origin_is_allowed():
    c = make_client()
    r = c.get("/health", headers={"Origin": "http://tauri.localhost"})
    assert r.status_code == 200
    assert r.headers["access-control-allow-origin"] == "http://tauri.localhost"


def test_scripts_requires_token():
    c = make_client()
    r = c.get("/api/scripts")
    assert r.status_code == 401


def test_harambelogs_search_validates_query():
    c = make_client()
    # Missing required `q` param → 422
    r = c.get(
        "/api/harambelogs/search/channel/xqc/user/xqc",
        headers=auth_headers(),
    )
    assert r.status_code == 422

    # limit=1001 exceeds le=1000 → 422
    r = c.get(
        "/api/harambelogs/search/channel/xqc/user/xqc?q=hello&limit=1001",
        headers=auth_headers(),
    )
    assert r.status_code == 422


def test_frozen_modules_covers_all_scripts():
    """FROZEN_MODULES must list every script module for PyInstaller."""
    import pkgutil

    import app.scripts as scripts_pkg
    from app.scripts.registry import FROZEN_MODULES

    disk_names = {
        m.name
        for m in pkgutil.iter_modules(scripts_pkg.__path__)
        if not m.name.startswith("_") and m.name != "registry"
    }
    assert set(FROZEN_MODULES) == disk_names, (
        f"FROZEN_MODULES {set(FROZEN_MODULES)} != disk scripts {disk_names}. "
        "Update FROZEN_MODULES in registry.py AND hiddenimports in api_server.spec."
    )


def test_list_and_run_example():
    c = make_client()
    r = c.get("/api/scripts", headers=auth_headers())
    assert r.status_code == 200
    names = [s["name"] for s in r.json()]
    assert "example_task" in names

    r = c.post(
        "/api/scripts/example_task/run",
        headers=auth_headers(),
        json={"input_path": "hello", "threshold": 0.5},
    )
    assert r.status_code == 200, r.text
    assert r.json()["result"]["count"] == 10


def test_jobs_lifecycle():
    c = make_client()
    r = c.post(
        "/api/jobs",
        headers=auth_headers(),
        json={"script": "example_task", "params": {"input_path": "hi"}},
    )
    assert r.status_code == 200, r.text
    job_id = r.json()["job_id"]

    last = None
    for _ in range(50):
        last = c.get(f"/api/jobs/{job_id}", headers=auth_headers())
        assert last.status_code == 200
        if last.json()["status"] == "done":
            break
        time.sleep(0.05)
    assert last is not None
    assert last.json()["status"] == "done"
    assert last.json()["result"]["count"] == 10
