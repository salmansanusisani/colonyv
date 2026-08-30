"""Run History + Analytics must survive instance recycles.

Cloud Run's disk is ephemeral; every redeploy starts a fresh instance and the
output/ folder is empty again. The runs table and charts used to read only that
folder, so after any redeploy a user's history appeared to vanish. Runs and
analytics now merge the ephemeral folders with Firestore-backed run summaries,
so history is durable - and runs that predate summaries are backfilled from
their saved pipeline state.
"""

import pytest
from fastapi.testclient import TestClient

from dashboard import app as app_module


class _FakeCloud:
    """Durable side with a couple of old runs (no summary) and one summary."""

    def __init__(self):
        self.run_states = [
            {
                "run_id": "20260829_210950_4259",
                "current_step": "complete",
                "content_count": 2,
                "run_topic": "Cryptocurrency",
            },
            {
                "run_id": "20260829_233636_075d",
                "current_step": "stopped",
                "content_count": 1,
                "run_topic": "Hardware & GPUs",
            },
        ]
        self.summaries = [
            {
                "run_id": "20260830_010252_ad9a",
                "date": "20260830",
                "content": 1,
                "researched": 1,
                "scripted": 1,
                "rendered": 1,
                "video_size_mb": 33.2,
                "has_video": True,
                "topics": ["A real published story"],
                "status": "complete",
            }
        ]

    def list_run_summaries(self):
        return self.summaries

    def list_run_states(self):
        return self.run_states


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setattr(app_module, "CLOUD_STATE", _FakeCloud())
    empty = tmp_path / "empty_output"
    empty.mkdir()
    monkeypatch.setattr(app_module, "OUTPUT_DIR", empty)
    # Keep the YouTube call out of unit tests: report zero published so the
    # fallback (sum over run records) is exercised deterministically.
    monkeypatch.setattr(app_module, "_published_video_count", lambda: 0)
    return TestClient(app_module.app)


def test_runs_list_includes_backfilled_and_summarised_runs(client):
    data = client.get("/api/runs").json()
    run_ids = [r["run_id"] for r in data["runs"]]
    assert "20260830_010252_ad9a" in run_ids
    assert "20260829_210950_4259" in run_ids
    assert "20260829_233636_075d" in run_ids
    summarized = next(r for r in data["runs"] if r["run_id"] == "20260830_010252_ad9a")
    assert summarized["has_video"] is True
    assert summarized["video_size_mb"] == 33.2


def test_analytics_counts_merge_all_sources(client):
    data = client.get("/api/analytics").json()
    # 1 summarized run + 2 backfilled states
    assert data["total_runs"] == 3
    assert data["total_content"] == 4  # 1 + 2 + 1
    assert data["total_rendered"] == 2  # summary rendered + complete backfill
    dates = [r["date"] for r in data["runs"]]
    assert dates == sorted(dates)  # chronological order


def test_analytics_videos_published_prefers_live_youtube_count(monkeypatch, client):
    """When YouTube is reachable, the Published card shows the real channel
    count (the durable truth), not the guessed run-record total."""
    monkeypatch.setattr(app_module, "_published_video_count", lambda: 21)
    data = client.get("/api/analytics").json()
    assert data["total_rendered"] == 21


def test_local_folders_win_over_cloud_when_both_exist(monkeypatch, tmp_path):
    fake = _FakeCloud()
    monkeypatch.setattr(app_module, "CLOUD_STATE", fake)

    local_run = tmp_path / "20260830_010252_ad9a"
    local_run.mkdir()
    story = "20260830_010252_ad9a_s1"
    (local_run / f"{story}_monitor.json").write_text('{"title": "Fresh local title"}')
    (local_run / "vid.mp4").write_bytes(b"x" * 2_000_000)
    monkeypatch.setattr(app_module, "OUTPUT_DIR", tmp_path)

    data = TestClient(app_module.app).get("/api/runs").json()
    entry = next(r for r in data["runs"] if r["run_id"] == "20260830_010252_ad9a")
    # Local folder reports its own size (~1.9 MB) and title, not the cloud values.
    assert entry["video_size_mb"] == pytest.approx(1.9, abs=0.2)


class _FakeCloudWithPerformance(_FakeCloud):
    def load_performance_snapshots(self):
        video = {"id": "vid1", "title": "Perf video", "views": 10, "likes": 1}
        video2 = {"id": "vid1", "title": "Perf video", "views": 25, "likes": 2}
        return [
            {"at": "2026-08-29T10:00:00", "subscribers": 3, "videos": [video]},
            {"at": "2026-08-29T11:00:00", "subscribers": 4, "videos": [video2]},
        ]


def test_performance_charts_render_from_firestore_after_instance_recycle(monkeypatch, tmp_path):
    """Charts (view curves) must come back from Firestore when the local
    performance_history.json is gone with the instance."""
    monkeypatch.setattr(app_module, "CLOUD_STATE", _FakeCloudWithPerformance())
    empty = tmp_path / "empty"
    empty.mkdir()
    monkeypatch.setattr(app_module, "OUTPUT_DIR", empty)
    monkeypatch.setattr(app_module, "PERFORMANCE_LOG", empty / "performance_history.json")

    data = TestClient(app_module.app).get("/api/performance").json()
    assert data["ready"] is True
    assert data["snapshots"] == 2
    assert len(data["series"]) == 1
    assert data["series"][0]["points"][-1]["views"] == 25
    assert data["totals"]["videos"] == 1