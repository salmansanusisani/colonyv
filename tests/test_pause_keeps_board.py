"""Regression: pausing must freeze the workspace board, not wipe it.

Prior behaviour reset every agent card to "pending" when pause was pressed, so
resume showed a mix of grey and active cards instead of continuing exactly
where the run was.
"""

import pytest
from fastapi.testclient import TestClient

from dashboard import app as app_module


@pytest.fixture
def paused_client(monkeypatch):
    monkeypatch.setattr(app_module, "AUTH_USERNAME", "owner")
    monkeypatch.setattr(app_module, "AUTH_ENABLED", False)
    monkeypatch.setattr(app_module, "LOGIN_ATTEMPTS", {})
    monkeypatch.setattr(app_module, "save_settings", lambda: None)
    monkeypatch.setattr(app_module, "settings", app_module.load_settings())
    # Pipeline currently "running".
    state = app_module.pipeline_state
    state["running"] = True
    state["paused"] = False
    state["current_step"] = "script"
    state["progress"] = 55
    # A realistic frozen board: monitor done, research done, script active.
    state["agent_activity"] = {
        "monitor": {"key": "monitor", "name": "Monitor", "status": "complete", "detail": "Selected 1 stories"},
        "research": {"key": "research", "name": "Research", "status": "complete", "detail": "Collected 9 claims"},
        "script": {"key": "script", "name": "Script", "status": "active", "detail": "Writing story 1/1"},
    }
    with TestClient(app_module.app) as c:
        yield state, c
    state["running"] = False
    state["paused"] = False


def test_pause_keeps_board_state(paused_client):
    state, c = paused_client

    r = c.post("/api/pipeline/pause")
    assert r.status_code == 200
    assert state["paused"] is True

    # Cards must be untouched: monitor/research still complete, script active.
    assert state["agent_activity"]["monitor"]["status"] == "complete"
    assert state["agent_activity"]["research"]["status"] == "complete"
    assert state["agent_activity"]["script"]["status"] == "active"


def test_pause_status_endpoint_serves_same_board(paused_client):
    state, c = paused_client
    r1 = c.get("/api/status").json()["agent_activity"]
    assert r1["script"]["status"] == "active"

    r2 = c.get("/api/status").json()["agent_activity"]
    assert r2 == r1
    assert r2["monitor"]["status"] == "complete"