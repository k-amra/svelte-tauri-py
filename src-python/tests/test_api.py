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


def test_dev_origin_rejected_without_sidecar_dev(monkeypatch):
    monkeypatch.delenv("SIDECAR_DEV", raising=False)
    c = make_client()
    r = c.get("/health", headers={"Origin": "http://localhost:1420"})
    assert r.status_code == 200
    assert "access-control-allow-origin" not in r.headers


def test_dev_origin_allowed_with_sidecar_dev(monkeypatch):
    monkeypatch.setenv("SIDECAR_DEV", "1")
    c = make_client()
    r = c.get("/health", headers={"Origin": "http://localhost:1420"})
    assert r.status_code == 200
    assert r.headers["access-control-allow-origin"] == "http://localhost:1420"


def test_scripts_requires_token():
    c = make_client()
    r = c.get("/api/scripts")
    assert r.status_code == 401


def test_harambelogs_search_validates_query():
    c = make_client()
    # Missing required `q` param → 422
    r = c.get(
        "/api/harambelogs/search/channel/demonzz1/user/demonzz1",
        headers=auth_headers(),
    )
    assert r.status_code == 422

    # limit=1001 exceeds le=1000 → 422
    r = c.get(
        "/api/harambelogs/search/channel/demonzz1/user/demonzz1?q=hello&limit=1001",
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


def test_jobs_rejects_inverted_dates_with_422():
    c = make_client()
    r = c.post(
        "/api/jobs",
        headers=auth_headers(),
        json={
            "script": "chat_stats",
            "params": {
                "channel": "chan",
                "from_date": "2024-02-01T00:00:00Z",
                "to_date": "2024-01-01T00:00:00Z",
            },
        },
    )
    assert r.status_code == 422
    assert "from_date" in r.text


def test_jobs_rejects_over_max_range_with_422():
    c = make_client()
    r = c.post(
        "/api/jobs",
        headers=auth_headers(),
        json={
            "script": "chat_stats",
            "params": {
                "channel": "chan",
                "from_date": "2020-01-01T00:00:00Z",
                "to_date": "2024-09-05T00:00:00Z",
            },
        },
    )
    assert r.status_code == 422
    assert "max_range_days" in r.text


def test_job_events_ring_buffer_caps_and_cursors():
    from app.core.jobs import JobManager

    manager = JobManager()

    def push_many(params, progress):
        for i in range(600):
            progress(float(i), f"msg {i}")
        return {"ok": True}

    job = manager.submit("t", push_many, None)
    deadline = time.time() + 10
    while manager.snapshot(job.id)["status"] == "running" and time.time() < deadline:
        time.sleep(0.01)
    assert manager.snapshot(job.id)["status"] == "done"

    stored = manager._jobs[job.id]
    assert len(stored.events) == 500
    # 600 pushes + the completion push = seqs 0..600; the ring keeps 101..600.
    assert stored.events[0]["seq"] == 101

    batch, _, _ = manager.events_since(job.id, -1)
    assert len(batch) == 500 and batch[0]["seq"] == 101

    tail, _, _ = manager.events_since(job.id, 550)
    assert [e["seq"] for e in tail] == list(range(551, 601))
