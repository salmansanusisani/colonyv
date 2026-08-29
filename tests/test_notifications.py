"""In-app notifications: lifecycle events are recorded server-side and served
back through the API so any logged-in session can read run history; email is
gone, Slack remains optional."""

import pytest
from fastapi.testclient import TestClient

from dashboard import app as app_module


@pytest.fixture
def notif_client(monkeypatch, tmp_path):
    monkeypatch.setattr(app_module, "AUTH_USERNAME", "owner")
    monkeypatch.setattr(app_module, "AUTH_ENABLED", False)
    monkeypatch.setattr(app_module, "LOGIN_ATTEMPTS", {})
    monkeypatch.setattr(app_module, "save_settings", lambda: None)
    monkeypatch.setattr(app_module, "settings", app_module.load_settings())
    monkeypatch.setattr(app_module, "NOTIFICATIONS_LOG_PATH", tmp_path / "notifications.json")
    monkeypatch.setattr(app_module, "notification_config", {
        "slack_webhook": "",
        "on_complete": True,
        "on_error": True,
    })
    return TestClient(app_module.app)


def test_send_notification_creates_in_app_entry(notif_client):
    app_module._append_notification("success", "Pipeline complete: 1/1 rendered")
    app_module._append_notification("error", "Pipeline error: boom")
    with notif_client as c:
        r = c.get("/api/notifications")
    assert r.status_code == 200
    body = r.json()
    assert "email_to" not in body
    entries = body["notifications"]
    assert [e["level"] for e in entries] == ["error", "success"]  # newest first
    assert entries[0]["message"] == "Pipeline error: boom"
    assert entries[0]["ts"]
    assert entries[0]["id"]


def test_notification_log_persists_across_calls(notif_client):
    app_module._append_notification("info", "Run started")
    with notif_client as c:
        r1 = c.get("/api/notifications")
        r2 = c.get("/api/notifications")
    assert r1.json()["notifications"] == r2.json()["notifications"]


def test_clear_notification_history(notif_client):
    app_module._append_notification("info", "ephemeral")
    with notif_client as c:
        r = c.post("/api/notifications/clear")
        assert r.status_code == 200
        r2 = c.get("/api/notifications")
    assert r2.json()["notifications"] == []


def test_save_notifications_persists_toggles_and_webhook(notif_client):
    with notif_client as c:
        r = c.post("/api/notifications", json={
            "slack_webhook": "https://hooks.slack.com/services/abc",
            "on_complete": True,
            "on_error": False,
        })
        assert r.status_code == 200
        r2 = c.get("/api/notifications")
    body = r2.json()
    assert body["slack_webhook"] == "https://hooks.slack.com/services/abc"
    assert body["slack_configured"] is True
    assert body["on_complete"] is True
    assert body["on_error"] is False
    assert "email_to" not in body