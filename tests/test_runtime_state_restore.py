"""The live board + schedule must survive an instance recycle.

Cloud Run recycles the container on every redeploy (and sometimes during
maintenance), which destroys the in-memory ``pipeline_state`` and
``scheduler_config``. That used to wipe the stopwatch, reset the board to
"Ready", and lose the armed schedule mid-run. We now persist a small runtime
state doc and restore it at startup so the operator can see exactly where a
run stopped.
"""

import pytest

from dashboard import app as app_module


class _FakeCloud:
    def __init__(self, runtime_state):
        self.runtime_state = runtime_state or {}
        self.bucket = None

    def save_runtime_state(self, state):
        self.runtime_state = state

    def load_runtime_state(self):
        return self.runtime_state


def _make_state(**overrides):
    state = {
        "running": True,
        "paused": False,
        "run_id": "20260830_123456_abcd",
        "current_step": "render",
        "progress": 42,
        "content_count": 2,
        "content_done": 1,
        "start_time": 1700000000.0,
        "paused_duration": 0.0,
        "agent_message": "Rendering story 1",
        "scheduler_enabled": True,
        "interval_hours": 6,
        "next_run": "2099-01-01T00:00:00",
    }
    state.update(overrides)
    return state


def test_restore_populates_board_after_recycle(monkeypatch):
    st = _make_state()
    monkeypatch.setattr(app_module, "CLOUD_STATE", _FakeCloud(st))
    # A fresh board, as if the instance just booted.
    pipeline_state = dict(app_module.pipeline_state)
    scheduler_config = dict(app_module.scheduler_config)
    monkeypatch.setattr(app_module, "pipeline_state", pipeline_state)
    monkeypatch.setattr(app_module, "scheduler_config", scheduler_config)

    # Simulate a mid-run recycle: force the running flag back to the durable
    # value then restore as Startup would.
    pipeline_state["running"] = False
    pipeline_state["run_id"] = None
    scheduler_config["next_run"] = None

    app_module.restore_runtime_state()

    assert scheduler_config["next_run"] == st["next_run"]
    assert scheduler_config["interval_hours"] == 6
    # The actual processing task is gone, so restore never leaves a phantom
    # "running" instance; the operator sees the interrupted board instead.
    assert pipeline_state["running"] is False
    # The restored step shows exactly where the prior instance stopped.
    assert pipeline_state["current_step"] == "render"
    assert pipeline_state["run_id"] == st["run_id"]
    assert pipeline_state["progress"] == 42


def test_restore_rolls_stale_schedule_forward(monkeypatch):
    """If the previous instance died while the schedule was already due, do NOT
    fire a stale duplicate - roll the next_run forward by the interval."""
    st = _make_state(next_run="2001-01-01T00:00:00", running=True)
    monkeypatch.setattr(app_module, "CLOUD_STATE", _FakeCloud(st))
    pipeline_state = dict(app_module.pipeline_state)
    scheduler_config = dict(app_module.scheduler_config)
    monkeypatch.setattr(app_module, "pipeline_state", pipeline_state)
    monkeypatch.setattr(app_module, "scheduler_config", scheduler_config)
    scheduler_config["enabled"] = True
    scheduler_config["interval_hours"] = 6

    app_module.restore_runtime_state()

    assert scheduler_config["next_run"] is not None
    # Rolled forward: comfortably in the future, not the stale 2001 time.
    assert scheduler_config["next_run"] > st["next_run"]
