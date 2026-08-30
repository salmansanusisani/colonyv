"""Schedules must be computed and shown in the operator's local timezone
(Africa/Lagos, WAT) and must queue behind a currently-running run rather than
firing a duplicate or showing a stale past timestamp."""

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from dashboard import app as app_module


def test_next_run_epoch_ms_treats_naive_as_lagos():
    """A naive stored Lagos time must be interpreted as WAT (UTC+1), not UTC."""
    naive = "2026-08-30T12:00:00"
    dt = datetime.fromisoformat(naive).replace(tzinfo=ZoneInfo("Africa/Lagos"))
    ms = app_module._next_run_epoch_ms(naive)
    assert ms == pytest.approx(dt.timestamp() * 1000.0, abs=0.01)


def test_next_run_epoch_ms_honors_explicit_offset():
    """An explicitly-offset stored time is respected (not re-anchored to WAT)."""
    naive = "2026-08-30T12:00:00"
    dt = datetime.fromisoformat(naive + "+02:00")  # e.g. Cairo, not WAT
    ms = app_module._next_run_epoch_ms(naive + "+02:00")
    assert ms == pytest.approx(dt.timestamp() * 1000.0, abs=0.01)


def test_schedule_next_returns_lagos_aware_iso():
    nxt = app_module._schedule_next(6)
    dt = datetime.fromisoformat(nxt)
    assert dt.tzinfo is not None
    assert dt.utcoffset().total_seconds() == 3600  # WAT == UTC+1


def test_schedule_state_pending_when_run_past_due(monkeypatch):
    sc = dict(app_module.scheduler_config)
    sc["enabled"] = True
    sc["next_run"] = "2001-01-01T00:00:00"  # long overdue
    monkeypatch.setattr(app_module, "scheduler_config", sc)
    ps = dict(app_module.pipeline_state)
    ps["running"] = True
    monkeypatch.setattr(app_module, "pipeline_state", ps)
    assert app_module._schedule_state() == "pending"


def test_schedule_state_armed_when_future(monkeypatch):
    sc = dict(app_module.scheduler_config)
    sc["enabled"] = True
    sc["next_run"] = "2099-01-01T00:00:00"
    monkeypatch.setattr(app_module, "scheduler_config", sc)
    ps = dict(app_module.pipeline_state)
    ps["running"] = True
    monkeypatch.setattr(app_module, "pipeline_state", ps)
    assert app_module._schedule_state() == "armed"


def test_schedule_state_disabled_when_no_next_run(monkeypatch):
    sc = dict(app_module.scheduler_config)
    sc["enabled"] = True
    sc["next_run"] = None
    monkeypatch.setattr(app_module, "scheduler_config", sc)
    assert app_module._schedule_state() == "disabled"
