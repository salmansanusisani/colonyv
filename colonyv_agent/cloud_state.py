"""Firestore-backed run state for Cloud Run deployments.

Local development can continue using the existing filesystem path. Cloud code
calls this adapter only when GOOGLE_CLOUD_PROJECT is configured.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any


class FirestoreState:
    def __init__(self, collection: str = "colonyv_runs"):
        from google.cloud import firestore

        self.client = firestore.Client(project=os.environ.get("GOOGLE_CLOUD_PROJECT"))
        self.collection = self.client.collection(collection)

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


def get_cloud_state() -> FirestoreState | None:
    if not os.environ.get("GOOGLE_CLOUD_PROJECT"):
        return None
    return FirestoreState()
