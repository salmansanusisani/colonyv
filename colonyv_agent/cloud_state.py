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


def get_cloud_state() -> FirestoreState | None:
    if not os.environ.get("GOOGLE_CLOUD_PROJECT"):
        return None
    return FirestoreState()
