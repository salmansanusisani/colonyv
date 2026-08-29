import asyncio

import pytest
from fastapi.testclient import TestClient

from dashboard import app as app_module


@pytest.fixture()
def client():
    with TestClient(app_module.app) as c:
        yield c


def _sched(client):
    r = client.get("/api/scheduler")
    assert r.status_code == 200
    return r.json()


def test_schedule_is_unarmed_on_startup(client):
    assert _sched(client)["next_run"] is None


def test_settings_save_does_not_arm_schedule(client):
    r = client.post("/api/settings", json={
        "pipeline": {"videos_per_run": 2},
        "model": {"model_id": "gemini/gemini-3.5-flash"},
        "scheduler": {"enabled": True, "interval_hours": 0.0833, "videos_per_run": 2},
    })
    assert r.status_code == 200
    assert _sched(client)["next_run"] is None


def test_scheduler_post_does_not_arm_when_unarmed(client):
    r = client.post("/api/scheduler", json={"interval_hours": 0.0833, "stories": 2})
    assert r.status_code == 200
    assert _sched(client)["next_run"] is None


def test_scheduler_post_reschedules_when_armed(client):
    app_module.scheduler_config["next_run"] = "2099-01-01T00:00:00"
    r = client.post("/api/scheduler", json={"interval_hours": 0.5, "stories": 2})
    assert r.status_code == 200
    nxt = _sched(client)["next_run"]
    assert nxt is not None
    assert nxt != "2099-01-01T00:00:00"


def test_stop_disarms_schedule(client):
    app_module.scheduler_config["next_run"] = "2099-01-01T00:00:00"
    r = client.post("/api/pipeline/stop")
    assert r.status_code == 200
    assert _sched(client)["next_run"] is None


def test_manual_run_arms_schedule(tmp_path, monkeypatch):
    monkeypatch.setattr(app_module, "OUTPUT_DIR", tmp_path)
    monkeypatch.setattr(app_module, "reset_agent_activity", lambda: None)
    monkeypatch.setattr(app_module, "persist_pipeline_state", lambda *a, **k: None)

    async def fake_director(*a, **k):
        pass

    monkeypatch.setattr(app_module, "run_production_director", fake_director)
    app_module.scheduler_config["enabled"] = True
    app_module.scheduler_config["next_run"] = None
    asyncio.run(app_module.launch_production_run(1))
    assert app_module.scheduler_config["next_run"] is not None