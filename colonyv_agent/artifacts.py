"""Durable backup of run artifacts to Google Cloud Storage.

Cloud Run's filesystem is ephemeral: every redeploy or instance recycle wipes
the output/ folder, so a run's MP4 and its monitor/research/script JSONs would
vanish and the dashboard's "Past Pipeline Executions" rows would show
"not found" when clicked.

This module copies a finished run's files into a GCS bucket under
`runs/<run_id>/...` so they are always retrievable. When the dashboard reads a
run, it checks the local folder first (fast, current instance) and falls back
to downloading from the bucket (survives redeploys).
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

BUCKET_ENV = "COLONYV_ARTIFACT_BUCKET"
DEFAULT_BUCKET = "colonyv-run-artifacts"

# Story files we want to keep per run. Everything else (logs, previews, cost
# accounting, the render's intermediate images) is disposable.
_STORY_FILE_SPLIT = [
    (_monitor := "_monitor.json"),
    (_research := "_research.json"),
    (_script := "_script.json"),
    (_visual := "_visual_plan.json"),
    ".mp4",
]


def _get_bucket() -> str | None:
    return os.environ.get(BUCKET_ENV, DEFAULT_BUCKET)


def _has_storage() -> bool:
    try:
        from google.cloud import storage  # noqa: F401

        return True
    except Exception:
        return False


def _hidden_path(path: Path) -> bool:
    return path.name.startswith(".")


def backup_run_artifacts(run_id: str, run_dir: Path) -> dict[str, Any]:
    """Upload a finished run's MP4(s) and story JSONs to GCS.

    Best-effort and never raises: a backup failure must not break a run that
    has already published.
    """
    result = {"uploaded": 0, "skipped": 0, "error": None}
    if not run_id or not run_dir or not run_dir.exists():
        result["skipped"] = 1
        return result
    if not _has_storage():
        result["error"] = "google.cloud.storage not available"
        return result

    bucket_name = _get_bucket()
    if not bucket_name:
        result["error"] = "no artifact bucket configured"
        return result

    try:
        from google.cloud import storage

        client = storage.Client(project=os.environ.get("GOOGLE_CLOUD_PROJECT"))
        bucket = client.bucket(bucket_name)
        target = f"runs/{run_id}"
        for f in sorted(run_dir.glob("*")):
            if f.is_dir() or _hidden_path(f) or f.suffix == ".json" and f.name.endswith(("_cost.json", "cost_log.json")):
                continue
            if not _is_run_artifact(f):
                continue
            blob = bucket.blob(f"{target}/{f.name}")
            try:
                blob.upload_from_filename(str(f), timeout=120)
                result["uploaded"] += 1
            except Exception as exc:
                result["skipped"] += 1
                print(f"[artifacts] upload failed for {f.name}: {exc}", flush=True)
    except Exception as exc:
        result["error"] = str(exc)
        print(f"[artifacts] backup run {run_id} failed: {exc}", flush=True)
    return result


def _is_run_artifact(path: Path) -> bool:
    """Only the story-envelope files (what the run detail modal shows)."""
    name = path.name
    if name.endswith(".mp4"):
        return True
    for suffix in ("_monitor.json", "_research.json", "_script.json", "_visual_plan.json"):
        if name.endswith(suffix):
            return True
    return False


def download_run_artifacts(run_id: str, local_dir: Path) -> dict[str, Any]:
    """Pull a run's artifact files from GCS into local_dir (missing ones only).

    Returns {"local": [...], "remote_available": bool}. Never raises.
    """
    out = {"local": [], "remote_available": False, "error": None}
    if not run_id:
        return out
    bucket_name = _get_bucket()
    if not bucket_name or not _has_storage():
        return out
    try:
        from google.cloud import storage

        client = storage.Client(project=os.environ.get("GOOGLE_CLOUD_PROJECT"))
        bucket = client.bucket(bucket_name)
        prefix = f"runs/{run_id}/"
        blobs = list(bucket.list_blobs(prefix=prefix))
        if not blobs:
            return out
        out["remote_available"] = True
        local_dir.mkdir(parents=True, exist_ok=True)
        for blob in blobs:
            name = blob.name[len(prefix):]
            if not name or "/" in name:
                continue
            dest = local_dir / name
            if dest.exists():
                out["local"].append(str(dest))
                continue
            try:
                blob.download_to_filename(str(dest), timeout=120)
                out["local"].append(str(dest))
            except Exception as exc:
                print(f"[artifacts] download failed for {name}: {exc}", flush=True)
    except Exception as exc:
        out["error"] = str(exc)
        print(f"[artifacts] download list for {run_id} failed: {exc}", flush=True)
    return out


def list_run_artifacts(run_id: str) -> list[str]:
    """Names of artifact blobs under runs/<run_id>/ (or [] if unreachable)."""
    try:
        from google.cloud import storage

        client = storage.Client(project=os.environ.get("GOOGLE_CLOUD_PROJECT"))
        blobs = list(client.bucket(_get_bucket()).list_blobs(prefix=f"runs/{run_id}/"))
        return [b.name.rsplit("/", 1)[-1] for b in blobs if b.name.endswith(("mp4", ".json"))]
    except Exception:
        return []
