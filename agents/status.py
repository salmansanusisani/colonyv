#!/usr/bin/env python3
"""
Pipeline Status - check health and recent runs.

Usage:
    python3 status.py                     # Show recent runs
    python3 status.py --runs 10           # Show last 10 runs
    python3 status.py --check-deps        # Check all dependencies
"""

import argparse
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = PROJECT_ROOT / "output"
AGENTS_DIR = Path(__file__).resolve().parent


def check_deps():
    print("=== Dependency Check ===\n")
    deps = [
        ("python3", "Python", "--version"),
        ("node", "Node.js", "--version"),
        ("npx", "Remotion CLI", "--version"),
        ("chromium", "Chromium", "--version"),
    ]
    for cmd, name, flag in deps:
        try:
            result = subprocess.run([cmd, flag], capture_output=True, text=True, timeout=10)
            version = result.stdout.strip().split("\n")[0]
            print(f"  [OK] {name}: {version}")
        except FileNotFoundError:
            print(f"  [MISSING] {name}: not found")
        except Exception as e:
            print(f"  [WARN] {name}: {e}")

    print("\nPython packages:")
    python_pkgs = [
        ("google.adk", "google-adk"),
        ("google.genai", "google-genai"),
        ("feedparser", "feedparser"),
        ("jsonschema", "jsonschema"),
        ("requests", "requests"),
        ("edge_tts", "edge-tts"),
        ("pydub", "pydub"),
        ("PIL", "Pillow"),
        ("googleapiclient", "google-api-python-client"),
    ]
    for module, pkg in python_pkgs:
        try:
            __import__(module)
            print(f"  [OK] {pkg}")
        except ImportError:
            print(f"  [MISSING] {pkg}")

    print("\nAPI Keys:")
    import os
    keys = [
        ("GOOGLE_API_KEY", "Gemini Developer API"),
    ]
    for env, name in keys:
        val = os.environ.get(env, "")
        if val:
            print(f"  [OK] {name}: {val[:8]}...")
        else:
            print(f"  [MISSING] {name}: not set")

    # Check client_secret.json
    secret_path = AGENTS_DIR / "publisher" / "client_secret.json"
    if secret_path.exists():
        print(f"  [OK] YouTube client_secret.json")
    else:
        print(f"  [MISSING] YouTube client_secret.json (upload will use sandbox)")


def show_runs(limit: int):
    print(f"=== Recent Pipeline Runs (last {limit}) ===\n")

    if not OUTPUT_DIR.exists():
        print("  No output directory found.")
        return

    runs = []
    for run_dir in sorted(OUTPUT_DIR.iterdir(), reverse=True):
        if not run_dir.is_dir():
            continue
        summary_path = run_dir / "run_summary.json"
        if summary_path.exists():
            with open(summary_path) as f:
                summary = json.load(f)
            runs.append(summary)
        else:
            # Count files manually
            files = list(run_dir.glob("*"))
            runs.append({
                "run_id": run_dir.name,
                "results": [{"title": f.stem, "mp4": str(f)} for f in run_dir.glob("*.mp4")],
            })

    for run in runs[:limit]:
        run_id = run.get("run_id", "unknown")
        results = run.get("results", [])
        ts = ""
        try:
            dt = datetime.strptime(run_id, "%Y%m%d_%H%M%S")
            ts = dt.strftime("%Y-%m-%d %H:%M")
        except ValueError:
            ts = run_id

        print(f"  Run: {run_id} ({ts})")
        for r in results:
            title = r.get("title", "Unknown")[:50]
            published = "PUBLISHED" if r.get("published") else "RENDERED"
            mp4 = r.get("mp4", "")
            size = ""
            if mp4 and Path(mp4).exists():
                size = f" ({Path(mp4).stat().st_size / 1024 / 1024:.1f} MB)"
            print(f"    [{published}] {title}{size}")
        print()


def main():
    parser = argparse.ArgumentParser(description="Pipeline status")
    parser.add_argument("--runs", type=int, default=5, help="Show last N runs")
    parser.add_argument("--check-deps", action="store_true", help="Check dependencies")
    args = parser.parse_args()

    if args.check_deps:
        check_deps()
    else:
        show_runs(args.runs)


if __name__ == "__main__":
    main()
