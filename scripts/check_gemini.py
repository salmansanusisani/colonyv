#!/usr/bin/env python3
"""Verify Gemini connectivity using an API key or Vertex AI credentials."""

from __future__ import annotations

import argparse
import os
import sys

from google import genai


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default=os.environ.get("COLONYV_GEMINI_MODEL", "gemini-3.5-flash"))
    parser.add_argument("--vertex", action="store_true", help="Use Vertex AI Application Default Credentials")
    args = parser.parse_args()

    if args.vertex:
        project = os.environ.get("GOOGLE_CLOUD_PROJECT")
        location = os.environ.get("GOOGLE_CLOUD_LOCATION", "global")
        if not project:
            print("Set GOOGLE_CLOUD_PROJECT before using --vertex.", file=sys.stderr)
            return 2
        client = genai.Client(vertexai=True, project=project, location=location)
        mode = f"Vertex AI project={project} location={location}"
    else:
        api_key = os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY")
        if not api_key:
            print("Set GOOGLE_API_KEY (or GEMINI_API_KEY), or use --vertex.", file=sys.stderr)
            return 2
        client = genai.Client(api_key=api_key)
        mode = "Gemini Developer API"

    response = client.models.generate_content(
        model=args.model,
        contents="Reply with exactly: COLONYV_GEMINI_OK",
    )
    print(f"Mode: {mode}")
    print(f"Model: {args.model}")
    print(f"Response: {response.text}")
    return 0 if "COLONYV_GEMINI_OK" in (response.text or "") else 1


if __name__ == "__main__":
    raise SystemExit(main())
