"""Regression tests for the demo-critical fixes: the render gate must reject a
truncated MP4 before upload, and starting a run must be serialised."""

import asyncio
import types

import pytest
from fastapi.testclient import TestClient

from colonyv_agent import factory
from dashboard import app as app_module


def _story(idx=0):
    return {
        "index": idx,
        "story_id": f"story{idx}",
        "title": f"Story {idx}",
        "relevance_score": 0.9,
        "novelty_score": 0.9,
        "urgency_score": 0.9,
    }


def _wire_factory(monkeypatch, *, output_size_bytes, uploads):
    """Minimal happy path up to render, with a configurable render size."""

    def fake_discover(ctx):
        ctx.state["stories"] = [_story(0)]
        return {"success": True, "count": 1}

    monkeypatch.setattr(factory, "discover_stories", fake_discover)

    def fake_research(idx, ctx):
        ctx.state["research"] = {
            "claims": [{"text": "c1", "verified": False}],
            "contradictions": [],
            "confidence": "low",
            "sources": [{"url": "https://x"}],
        }
        return {"success": True, "total_claims": 1, "contradictions": 0,
                "sources_fetched": 1, "confidence": "low", "verified_claims": 0}

    monkeypatch.setattr(factory, "research_story", fake_research)
    monkeypatch.setattr(factory, "write_script", lambda ctx: {"success": True})
    monkeypatch.setattr(factory, "direct_visuals", lambda ctx: {
        "success": True, "shots": 4, "distinct_layouts": 3,
        "illustrations_planned": 3, "accent_role": "topic"})
    monkeypatch.setattr(factory, "request_render", lambda ctx: {
        "success": True, "output_exists": True,
        "output_size_bytes": output_size_bytes, "mp4_path": "/tmp/x.mp4"})

    def fake_publish(ctx):
        uploads.append("upload")
        return {"success": True, "video_id": "abc"}

    monkeypatch.setattr(factory, "publish_to_youtube", fake_publish)
    monkeypatch.setattr(factory, "analyze_performance", lambda ctx: {"success": True})
    monkeypatch.setattr(factory.runtime, "checkpoint", lambda *a: True)


def test_truncated_render_is_not_published(monkeypatch):
    """A file that exists but is far too small must never reach YouTube."""
    uploads: list[str] = []
    _wire_factory(monkeypatch, output_size_bytes=50_000, uploads=uploads)

    result = factory.run_factory(1)

    assert uploads == [], "a 50 KB truncated MP4 must not be uploaded"
    assert result.get("stories_produced") in (None, [])


def test_valid_render_is_published(monkeypatch):
    uploads: list[str] = []
    _wire_factory(monkeypatch, output_size_bytes=2_000_000, uploads=uploads)

    result = factory.run_factory(1)

    assert uploads == ["upload"]
    assert len(result["stories_produced"]) == 1


def test_failed_upload_is_not_reported_as_produced(monkeypatch):
    """Three failed uploads must not be reported as a finished story."""
    uploads: list[str] = []
    _wire_factory(monkeypatch, output_size_bytes=2_000_000, uploads=uploads)

    def failing_publish(ctx):
        uploads.append("attempt")
        return {"success": False, "video_id": "", "returncode": 1}

    monkeypatch.setattr(factory, "publish_to_youtube", failing_publish)

    result = factory.run_factory(1)

    assert len(uploads) == 3, "should retry three times"
    assert result.get("stories_produced") in (None, []), \
        "a story with no successful upload must not count as produced"


def test_successful_upload_records_video_id(monkeypatch):
    uploads: list[str] = []
    _wire_factory(monkeypatch, output_size_bytes=2_000_000, uploads=uploads)

    result = factory.run_factory(1)

    entry = result["stories_produced"][0]
    assert entry["video_id"] == "abc"
    assert entry["youtube_url"] == "https://youtube.com/watch?v=abc"


def test_concurrent_run_requests_start_only_one(monkeypatch):
    """A double-click must not launch two production runs."""
    monkeypatch.setattr(app_module, "AUTH_ENABLED", False)
    starts: list[int] = []

    async def fake_director(stories):
        starts.append(stories)
        await asyncio.sleep(0.3)
        app_module.pipeline_state["running"] = False

    monkeypatch.setattr(app_module, "run_production_director", fake_director)
    monkeypatch.setattr(app_module, "persist_pipeline_state", lambda *a, **k: None)
    monkeypatch.setattr(app_module, "reset_agent_activity", lambda: None)
    monkeypatch.setattr(app_module, "_production_task", None)
    # launch_production_run arms the scheduler and flips pipeline_state; restore
    # both after the test so later modules don't inherit our mutations.
    monkeypatch.setitem(app_module.scheduler_config, "next_run", None)
    monkeypatch.setitem(app_module.pipeline_state, "running", False)

    async def drive():
        results = await asyncio.gather(*[
            app_module.launch_production_run(1, source="manual") for _ in range(6)
        ])
        # let the accepted run finish so we don't leak a task
        task = app_module._production_task
        if task is not None:
            await task
        return results

    results = asyncio.run(drive())

    accepted = [r for r in results if r.get("status") == "started"]
    rejected = [r for r in results if r.get("status") == "rejected"]
    assert len(accepted) == 1, f"expected exactly one start, got {len(accepted)}"
    assert len(rejected) == 5
    assert starts == [1]


def test_new_run_waits_for_stopping_run(monkeypatch):
    """A run must not start while the previous one is still winding down."""
    monkeypatch.setattr(app_module, "persist_pipeline_state", lambda *a, **k: None)
    monkeypatch.setattr(app_module, "reset_agent_activity", lambda: None)
    monkeypatch.setitem(app_module.scheduler_config, "next_run", None)
    monkeypatch.setitem(app_module.pipeline_state, "running", False)

    async def drive():
        async def slow_previous():
            await asyncio.sleep(30)

        previous = asyncio.create_task(slow_previous())
        monkeypatch.setattr(app_module, "_production_task", previous)
        # shrink the grace period so the test stays fast
        monkeypatch.setattr(app_module.asyncio, "wait", _short_wait(app_module.asyncio.wait))
        try:
            return await app_module.launch_production_run(1, source="manual")
        finally:
            previous.cancel()

    def _short_wait(original):
        async def wait(aws, **kwargs):
            kwargs["timeout"] = 0.2
            return await original(aws, **kwargs)
        return wait

    result = asyncio.run(drive())
    assert result["status"] == "rejected"
    assert "still stopping" in result["error"]
