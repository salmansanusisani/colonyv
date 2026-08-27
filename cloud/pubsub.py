"""Pub/Sub helpers for the ColonyV asynchronous pipeline.

Pipeline stages are published to a single topic as messages carrying the run
identity and stage in attributes. A worker (the Cloud Run service's push
endpoint, or a local consumer) executes the stage, persists run state, and
publishes the next stage(s). Using one topic with stage attributes keeps the
subscription topology simple while each stage remains independently retryable.
"""

from __future__ import annotations

from typing import Any

from google.cloud import pubsub_v1

PIPELINE_TOPIC = "colonyv-stages"

STAGE_NAMES = ["monitor", "research", "script", "render", "publish", "analyst"]


def _publisher(project_id: str):
    return pubsub_v1.PublisherClient()


def publish_stage(
    project_id: str,
    run_id: str,
    stage: str,
    story_index: int = 0,
    attempt: int = 1,
    topic: str = PIPELINE_TOPIC,
    body: dict[str, Any] | None = None,
) -> str:
    """Publish a stage message; returns the message id."""
    topic_path = _publisher(project_id).topic_path(project_id, topic)
    data = (body or {}).get("note", "")
    attrs = {
        "run_id": str(run_id),
        "stage": stage,
        "story_index": str(int(story_index)),
        "attempt": str(int(attempt)),
    }
    future = _publisher(project_id).publish(
        topic_path, data.encode("utf-8"), **attrs
    )
    return future.result(timeout=15)


def create_topic(project_id: str, topic: str = PIPELINE_TOPIC) -> str:
    """Idempotently create the pipeline topic; returns its path."""
    client = pubsub_v1.PublisherClient()
    path = client.topic_path(project_id, topic)
    try:
        client.create_topic(request={"name": path})
    except Exception:
        pass
    return path


def publish_next(
    project_id: str,
    run_id: str,
    result: dict[str, Any],
    topic: str = PIPELINE_TOPIC,
) -> list[str]:
    """Publish the next-stage messages implied by a run_stage result."""
    ids = []
    for stage, story_index, attempt in result.get("next", []):
        ids.append(
            publish_stage(
                project_id, run_id, stage, story_index, attempt, topic=topic
            )
        )
    return ids