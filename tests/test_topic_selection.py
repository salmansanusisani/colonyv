"""Topic selection: the dashboard arms multiple categories and each run picks
one of them uniformly at random."""

import pytest
from fastapi.testclient import TestClient

from dashboard import app as app_module


def test_pick_run_topic_draws_from_selected_pool(monkeypatch):
    pool = ["AI & Machine Learning", "Cryptocurrency", "Big Tech & Startups", "Hardware & GPUs"]
    monkeypatch.setattr(
        app_module, "settings",
        {"content": {"selected_topics": list(pool), "active_topic": "", "custom_topics": list(pool)}},
    )
    for _ in range(100):
        assert app_module.pick_run_topic() in pool


def test_pick_run_topic_all_categories_eventually_drawn(monkeypatch):
    pool = ["A", "B", "C", "D"]
    monkeypatch.setattr(
        app_module, "settings",
        {"content": {"selected_topics": ["A", "B", "C", "D"], "active_topic": "", "custom_topics": ["A", "B", "C", "D"]}},
    )
    seen = {app_module.pick_run_topic() for _ in range(200)}
    assert set(pool) == set(seen)


def test_pick_run_topic_falls_back_to_active_topic(monkeypatch):
    monkeypatch.setattr(
        app_module, "settings",
        {"content": {"selected_topics": [], "active_topic": "Only Topic", "custom_topics": ["Other"]}},
    )
    assert app_module.pick_run_topic() == "Only Topic"


def test_pick_run_topic_falls_back_to_first_custom(monkeypatch):
    monkeypatch.setattr(
        app_module, "settings",
        {"content": {"selected_topics": [], "active_topic": "", "custom_topics": ["First Custom", "Second"]}},
    )
    assert app_module.pick_run_topic() == "First Custom"


def test_pick_run_topic_empty_pool_returns_empty(monkeypatch):
    monkeypatch.setattr(
        app_module, "settings",
        {"content": {"selected_topics": [], "active_topic": "", "custom_topics": []}},
    )
    assert app_module.pick_run_topic() == ""


def test_api_saves_selected_topics_and_syncs_active(monkeypatch):
    monkeypatch.setattr(app_module, "AUTH_USERNAME", "owner")
    monkeypatch.setattr(app_module, "AUTH_ENABLED", False)
    monkeypatch.setattr(app_module, "LOGIN_ATTEMPTS", {})
    monkeypatch.setattr(app_module, "save_settings", lambda: None)
    monkeypatch.setattr(app_module, "settings", app_module.load_settings())

    with TestClient(app_module.app) as c:
        r = c.post("/api/settings", json={
            "content": {
                "custom_topics": ["Alpha", "Beta", "Gamma"],
                "selected_topics": ["Alpha", "Gamma"],
                "active_topic": "Beta",
                "brand_voice": "engaging_news",
            }
        })
    assert r.status_code == 200
    body = r.json()
    content = body.get("content", {})
    assert content["selected_topics"] == ["Alpha", "Gamma"]
    assert content["active_topic"] == "Alpha"  # first selected wins