"""Single Gemini client used by every ColonyV AI operation."""

from __future__ import annotations

import json
import os
import re
import time
from typing import Any

from google import genai


MODEL = os.environ.get("COLONYV_GEMINI_MODEL", "gemini-3.5-flash")


def client() -> genai.Client:
    if os.environ.get("GOOGLE_GENAI_USE_VERTEXAI", "").lower() == "true" or os.environ.get("GOOGLE_CLOUD_PROJECT"):
        return genai.Client(
            vertexai=True,
            project=os.environ.get("GOOGLE_CLOUD_PROJECT"),
            location=os.environ.get("GOOGLE_CLOUD_LOCATION", "global"),
        )
    api_key = os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        raise RuntimeError("Set GOOGLE_API_KEY or configure Vertex AI with GOOGLE_CLOUD_PROJECT")
    return genai.Client(api_key=api_key)


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
