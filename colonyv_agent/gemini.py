"""Single Gemini client used by every ColonyV AI operation."""

from __future__ import annotations

import json
import os
import re
import time
from typing import Any

from google import genai


MODEL = os.environ.get("COLONYV_GEMINI_MODEL", "gemini-3.5-flash")

_cached_client = None


def client() -> genai.Client:
    """Return a process-wide singleton Gemini client.

    google-genai shares a singleton async HTTP transport; creating a fresh
    Client per call lets garbage collection close that shared transport and
    break the next request with "Cannot send a request, as the client has been
    closed." A single cached client avoids that entirely.
    """
    global _cached_client
    if _cached_client is not None:
        return _cached_client
    if os.environ.get("GOOGLE_GENAI_USE_VERTEXAI", "").lower() == "true" or os.environ.get("GOOGLE_CLOUD_PROJECT"):
        _cached_client = genai.Client(
            vertexai=True,
            project=os.environ.get("GOOGLE_CLOUD_PROJECT"),
            location=os.environ.get("GOOGLE_CLOUD_LOCATION", "global"),
        )
    else:
        api_key = os.environ.get("GOOGLE_API_KEY")
        if not api_key:
            raise RuntimeError("Set GOOGLE_API_KEY or configure Vertex AI with GOOGLE_CLOUD_PROJECT")
        _cached_client = genai.Client(api_key=api_key)
    return _cached_client


def generate_json(prompt: str, retries: int = 3) -> dict[str, Any] | list[Any] | None:
    for attempt in range(retries):
        try:
            response = client().models.generate_content(
                model=MODEL,
                contents=prompt,
                config={"temperature": 0.4, "response_mime_type": "application/json"},
            )
            text = (response.text or "").strip()
            text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text).strip()
            return json.loads(text)
        except Exception:
            if attempt == retries - 1:
                raise
            time.sleep(2 ** attempt)
    return None
