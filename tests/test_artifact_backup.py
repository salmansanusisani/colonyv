"""Run artifacts are backed up to GCS so clicking a run always works.

Cloud Run's disk is ephemeral; after a redeploy the run folders vanish and the
dashboard's "Past Pipeline Executions" rows show "not found" when clicked. The
finished run's MP4(s) and story JSONs are copied to GCS and re-downloaded on
demand, so history stays clickable across redeploys.
"""

from pathlib import Path

import pytest

from colonyv_agent import artifacts


class _Blob:
    def __init__(self, name, data=b""):
        self.name = name
        self._data = data

    def upload_from_filename(self, filename, timeout=120):
        self._data = Path(filename).read_bytes()

    def download_to_filename(self, filename, timeout=120):
        Path(filename).write_bytes(self._data)


class _Bucket:
    def __init__(self):
        self.blobs = {}

    def blob(self, name):
        if name not in self.blobs:
            self.blobs[name] = _Blob(name)
        return self.blobs[name]

    def list_blobs(self, prefix=""):
        return [b for n, b in self.blobs.items() if n.startswith(prefix)]


class _Client:
    def __init__(self):
        self.bucket_obj = _Bucket()

    def bucket(self, name):
        return self.bucket_obj


@pytest.fixture(autouse=True)
def fake_storage(monkeypatch):
    client = _Client()
    monkeypatch.setattr("google.cloud.storage.Client", lambda *a, **k: client)
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "test-project")
    return client


def test_backup_run_artifacts_uploads_story_files(fake_storage, tmp_path):
    run_dir = tmp_path / "20260830_010101"
    run_dir.mkdir()
    (run_dir / "abc.mp4").write_bytes(b"MP4DATA")
    (run_dir / "abc_monitor.json").write_text('{"title": "T"}')
    (run_dir / "abc_research.json").write_text("{}")
    (run_dir / "abc_script.json").write_text("{}")
    (run_dir / "abc_visual_plan.json").write_text("{}")
    # Not part of the story envelope - must be skipped
    (run_dir / "cost_log.json").write_text("{}")
    (run_dir / "pipeline.log").write_text("log")

    result = artifacts.backup_run_artifacts("20260830_010101", run_dir)

    assert result["error"] is None
    assert result["uploaded"] == 5
    names = set(fake_storage.bucket_obj.blobs)
    assert "runs/20260830_010101/abc.mp4" in names
    assert "runs/20260830_010101/abc_monitor.json" in names
    # Disposable files are not backed up
    assert not any("cost_log" in n or "pipeline.log" in n for n in names)


def test_download_run_artifacts_restores_missing_files(fake_storage, tmp_path):
    run_dir = tmp_path / "20260830_010101"
    run_dir.mkdir()
    (run_dir / "abc.mp4").write_bytes(b"MP4DATA")
    (run_dir / "abc_monitor.json").write_text('{"title": "T"}')

    artifacts.backup_run_artifacts("20260830_010101", run_dir)

    # Simulate a fresh instance: remove the local run folder entirely.
    emptied = tmp_path / "20260830_010101"
    for f in list(emptied.glob("*")):
        f.unlink()

    res = artifacts.download_run_artifacts("20260830_010101", emptied)

    assert res["remote_available"] is True
    assert (emptied / "abc.mp4").read_bytes() == b"MP4DATA"
    assert (emptied / "abc_monitor.json").read_text() == '{"title": "T"}'


def test_backup_missing_run_is_noop(fake_storage):
    result = artifacts.backup_run_artifacts("ghost", Path("/does/not/exist"))
    assert result["skipped"] == 1
    assert result["error"] is None


def test_run_detail_restores_from_gcs_after_instance_recycle(fake_storage, monkeypatch, tmp_path):
    """Clicking a run whose local folder was wiped still shows its content."""
    from fastapi.testclient import TestClient
    from dashboard import app as app_module

    # Seed GCS with a run, then simulate a fresh instance (empty OUTPUT_DIR).
    run_dir = tmp_path / "seed"
    run_dir.mkdir()
    (run_dir / "abc.mp4").write_bytes(b"x" * 2_000_000)
    (run_dir / "abc_monitor.json").write_text('{"title": "Durable story"}')
    artifacts.backup_run_artifacts("20260830_999999", run_dir)

    fresh = tmp_path / "fresh_output"
    fresh.mkdir()
    monkeypatch.setattr(app_module, "OUTPUT_DIR", fresh)
    monkeypatch.setattr(app_module, "AGENTS_DIR", tmp_path)

    resp = TestClient(app_module.app).get("/api/run/20260830_999999")

    assert resp.status_code == 200
    data = resp.json()
    assert data["content"][0]["monitor"]["title"] == "Durable story"
    assert data["content"][0]["video_size_mb"] > 0
    # The restored copy now exists under the (fresh) output dir.
    assert (fresh / "20260830_999999" / "abc.mp4").exists()
