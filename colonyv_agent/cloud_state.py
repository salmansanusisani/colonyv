"""Firestore-backed run state for Cloud Run deployments.

Local development can continue using the existing filesystem path. Cloud code
calls this adapter only when GOOGLE_CLOUD_PROJECT is configured.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any

from google.cloud import firestore


class FirestoreState:
    def __init__(self, collection: str = "colonyv_runs"):
        self.client = firestore.Client(project=os.environ.get("GOOGLE_CLOUD_PROJECT"))
        self.collection = self.client.collection(collection)
        # Compact per-run summaries: the durable record the dashboard's Run
        # History and Analytics read back after the ephemeral Cloud Run disk
        # (which holds the full output/ folder) is recycled by a redeploy.
        self.summaries = self.client.collection("colonyv_run_summaries")
        # Performance snapshots (view counts over time). Stored as one document
        # per snapshot so growth never trips a per-document size limit.
        self.performance = self.client.collection("colonyv_performance")

    def save_run(self, run_id: str, state: dict[str, Any]) -> None:
        payload = {
            **state,
            "run_id": run_id,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        self.collection.document(run_id).set(payload, merge=True)

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        snapshot = self.collection.document(run_id).get()
        return snapshot.to_dict() if snapshot.exists else None

    def save_run_summary(self, run_id: str, summary: dict[str, Any]) -> None:
        payload = {
            "run_id": run_id,
            **summary,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        self.summaries.document(run_id).set(payload, merge=True)

    def list_run_summaries(self, limit: int = 200) -> list[dict[str, Any]]:
        docs = self.summaries.order_by("run_id", direction=firestore.Query.DESCENDING).limit(limit).stream()
        return [doc.to_dict() for doc in docs]

    def list_run_states(self, limit: int = 500) -> list[dict[str, Any]]:
        """Raw saved pipeline states, used to backfill history for runs that
        predate run summaries (their summary fields are inferred from these)."""
        docs = self.collection.order_by("run_id", direction=firestore.Query.DESCENDING).limit(limit).stream()
        return [doc.to_dict() for doc in docs]

    def save_performance_snapshots(self, snapshots: list[dict[str, Any]], limit: int = 500) -> None:
        """Persist view-count snapshots so the analytics charts survive instance
        recycles. Stored one document per snapshot ('at' used as the key)."""
        for snap in snapshots[-limit:]:
            snap_id = (snap.get("at") or "").replace(":", "-").replace("/", "-")
            if not snap_id:
                continue
            self.performance.document(snap_id).set(snap, merge=True)

    def load_performance_snapshots(self) -> list[dict[str, Any]]:
        docs = self.performance.order_by("at").stream()
        snapshots = [doc.to_dict() for doc in docs]
        return [s for s in snapshots if isinstance(s, dict) and s.get("at")]

    # --- Live run + scheduler state (so the board survives instance recycles) ---
    def save_runtime_state(self, state: dict[str, Any]) -> None:
        self.client.collection("colonyv_dashboard_state").document("current").set(
            state, merge=True
        )

    def load_runtime_state(self) -> dict[str, Any] | None:
        doc = self.client.collection("colonyv_dashboard_state").document("current").get()
        return doc.to_dict() if doc.exists else None


def get_cloud_state() -> FirestoreState | None:
    if not os.environ.get("GOOGLE_CLOUD_PROJECT"):
        return None
    return FirestoreState()
