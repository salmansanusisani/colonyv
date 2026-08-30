"""Regression: a finished run must not leave the workspace green forever.

The board used to stay all-green until the *next* run started. The client had a
6s timer that greyed the cards, but the server kept reporting every stage as
"complete", so the next 2s poll repainted them green and they stayed that way.

The cooldown now lives server-side: the completed board is held briefly (so the
finished cycle is actually visible) and then the statuses are cleared, which the
dashboard picks up as ordinary polled state.
"""

import asyncio

import pytest

from dashboard import app as app_module


def _completed_board():
    return {
        "monitor": {"key": "monitor", "name": "Monitor", "status": "complete", "detail": "Selected 1 stories"},
        "research": {"key": "research", "name": "Research", "status": "complete", "detail": "Collected 9 claims"},
        "script": {"key": "script", "name": "Script", "status": "complete", "detail": "Script ready"},
        "direct": {"key": "direct", "name": "Art Director", "status": "complete", "detail": "5 shots"},
        "render": {"key": "render", "name": "Producer", "status": "complete", "detail": "Rendered"},
        "publish": {"key": "publish", "name": "Publisher", "status": "complete", "detail": "Published"},
    }


@pytest.fixture(autouse=True)
def _quiet(monkeypatch):
    monkeypatch.setattr(app_module, "persist_pipeline_state", lambda force=False: None)


def test_cooldown_returns_cards_to_waiting():
    state = app_module.pipeline_state
    state["running"] = False
    state["progress"] = 100
    state["agent_activity"] = _completed_board()

    asyncio.run(app_module.cool_down_agent_board(delay=0))

    statuses = {k: v["status"] for k, v in state["agent_activity"].items()}
    assert set(statuses.values()) == {"pending"}, statuses
    assert state["active_agent"] is None
    assert state["progress"] == 0


def test_cooldown_skipped_when_a_new_run_started():
    """A quick re-run must not have its fresh board wiped by the old cooldown."""
    state = app_module.pipeline_state
    state["agent_activity"] = {
        "monitor": {"key": "monitor", "name": "Monitor", "status": "complete", "detail": "done"},
        "research": {"key": "research", "name": "Research", "status": "active", "detail": "researching"},
    }
    state["running"] = True  # new run already underway

    asyncio.run(app_module.cool_down_agent_board(delay=0))

    assert state["agent_activity"]["research"]["status"] == "active"
    assert state["agent_activity"]["monitor"]["status"] == "complete"
    state["running"] = False


def test_every_completion_path_schedules_the_cooldown():
    """Guard the wiring: all three run paths must arm the cooldown."""
    import inspect

    src = inspect.getsource(app_module)
    # ADK production, async stage runner, and the legacy pipeline.
    assert src.count("schedule_board_cooldown()") >= 4  # 3 call sites + the def


def test_schedule_is_safe_without_a_running_loop():
    """Called from a sync context (tests, CLI) it must no-op, not explode."""
    app_module.schedule_board_cooldown()
