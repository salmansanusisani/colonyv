"""Single Gemini client used by every ColonyV AI operation."""

from __future__ import annotations

import json
import os
import re
import time
from typing import Any

from google import genai


MODEL = os.environ.get("COLONYV_GEMINI_MODEL", "gemini-3.5-flash")

# google-genai defaults to no timeout at all, so a stalled TLS connection hangs
# the stage forever instead of failing and retrying. The orchestrator cannot
# rescue it either, so every request gets an explicit deadline (milliseconds).
REQUEST_TIMEOUT_MS = int(os.environ.get("COLONYV_LLM_TIMEOUT_MS", "120000"))

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
    http_options = {"timeout": REQUEST_TIMEOUT_MS}
    if os.environ.get("GOOGLE_GENAI_USE_VERTEXAI", "").lower() == "true" or os.environ.get("GOOGLE_CLOUD_PROJECT"):
        _cached_client = genai.Client(
            vertexai=True,
            project=os.environ.get("GOOGLE_CLOUD_PROJECT"),
            location=os.environ.get("GOOGLE_CLOUD_LOCATION", "global"),
            http_options=http_options,
        )
    else:
        api_key = os.environ.get("GOOGLE_API_KEY")
        if not api_key:
            raise RuntimeError("Set GOOGLE_API_KEY or configure Vertex AI with GOOGLE_CLOUD_PROJECT")
        _cached_client = genai.Client(api_key=api_key, http_options=http_options)
    return _cached_client


def generate_json(
    prompt: str,
    retries: int = 3,
    temperature: float = 0.4,
) -> dict[str, Any] | list[Any] | None:
    """Generate a JSON response from Gemini.

    temperature is exposed because the agents have genuinely different needs:
    research and scriptwriting want low variance for factual stability, while
    art direction wants high variance so consecutive videos do not converge on
    the same look.
    """
    for attempt in range(retries):
        try:
            response = client().models.generate_content(
                model=MODEL,
                contents=prompt,
                config={
                    "temperature": temperature,
                    "response_mime_type": "application/json",
                },
            )
            text = (response.text or "").strip()
            text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text).strip()
            return json.loads(text)
        except Exception:
            if attempt == retries - 1:
                raise
            time.sleep(2 ** attempt)
    return None
