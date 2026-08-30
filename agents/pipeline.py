#!/usr/bin/env python3
"""
Pipeline Orchestrator - runs Monitor → Research → Script → Producer → Publisher.

Usage:
    python3 pipeline.py                    # Full pipeline, 1 story
    python3 pipeline.py --stories 3        # Process 3 stories
    python3 pipeline.py --sandbox          # Sandbox mode (no YouTube upload)
    python3 pipeline.py --skip-publish     # Skip YouTube upload
"""

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
# Load environment variables from .env if present
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

PROJECT_ROOT = Path(__file__).resolve().parent.parent
AGENTS_DIR = Path(__file__).resolve().parent

GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")


def get_python_exec() -> str:
    venv_py = PROJECT_ROOT / ".venv" / "bin" / "python3"
    if venv_py.exists():
        return str(venv_py)
    return sys.executable


def log(step: str, msg: str):
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] [{step}] {msg}", flush=True)


def run_monitor(top: int = 5) -> list[dict]:
    log("MONITOR", f"Scanning RSS feeds (top {top})...")
    py_exec = get_python_exec()
    result = subprocess.run(
        [py_exec, "monitor/monitor.py", "--top", str(top)],
        capture_output=True, text=True,
        cwd=str(AGENTS_DIR), timeout=120,
        env={**os.environ, "GROQ_API_KEY": GROQ_API_KEY}
    )
    if result.returncode != 0:
        log("MONITOR", f"Failed: {result.stderr[-200:]}")
        return []

    # Parse MonitorOutput from stdout — find JSON array after "=== Top" header
    output = result.stdout
    try:
        header_idx = output.rfind("=== Top")
        if header_idx == -1:
            header_idx = 0
        start = output.index("[", header_idx)
        depth = 0
        for i, ch in enumerate(output[start:]):
            if ch == "[": depth += 1
            elif ch == "]": depth -= 1
            if depth == 0:
                stories = json.loads(output[start:start+i+1])
                log("MONITOR", f"Found {len(stories)} stories")
                return stories
    except (ValueError, json.JSONDecodeError):
        pass

    log("MONITOR", "No valid stories found in output")
    return []


def run_research(story: dict, output_dir: Path) -> dict | None:
    story_id = story.get("story_id", "unknown")
    title = story.get("title", "Unknown")[:50]
    log("RESEARCH", f"Researching: {title}...")

    story_path = output_dir / f"{story_id}_monitor.json"
    tmp_path = story_path.with_suffix(".json.tmp")
    with open(tmp_path, "w") as f:
        json.dump(story, f, indent=2)
    os.replace(tmp_path, story_path)

    py_exec = get_python_exec()
    result = subprocess.run(
        [py_exec, "research/research.py", "--story-json", str(story_path)],
        capture_output=True, text=True,
        cwd=str(AGENTS_DIR), timeout=180,
        env={**os.environ, "GROQ_API_KEY": GROQ_API_KEY}
    )

    if result.returncode != 0:
        log("RESEARCH", f"Failed: {result.stderr[-200:]}")
        return None

    # Parse ResearchOutput from stdout
    output = result.stdout
    for line in output.split("\n"):
        line = line.strip()
        if line.startswith("{"):
            try:
                # Find the JSON object
                start = output.index(line)
                depth = 0
                for i, ch in enumerate(output[start:]):
                    if ch == "{": depth += 1
                    elif ch == "}": depth -= 1
                    if depth == 0:
                        research = json.loads(output[start:start+i+1])
                        research["story_id"] = story_id
                        log("RESEARCH", f"OK: {len(research.get('claims', []))} claims, confidence={research.get('confidence')}")
                        return research
            except (json.JSONDecodeError, ValueError):
                continue

    log("RESEARCH", "Failed to parse research output")
    return None


def run_scriptwriter(research: dict, output_dir: Path) -> dict | None:
    story_id = research.get("story_id", "unknown")
    log("SCRIPT", f"Writing script for: {research.get('summary', '')[:50]}...")

    research_path = output_dir / f"{story_id}_research.json"
    with open(research_path, "w") as f:
        json.dump(research, f, indent=2)

    py_exec = get_python_exec()
    result = subprocess.run(
        [py_exec, "scriptwriter/scriptwriter.py", "--research-json", str(research_path)],
        capture_output=True, text=True,
        cwd=str(AGENTS_DIR), timeout=120,
        env={**os.environ, "GROQ_API_KEY": GROQ_API_KEY}
    )

    if result.returncode != 0:
        log("SCRIPT", f"Failed: {result.stderr[-200:]}")
        return None

    # Parse ScriptOutput from stdout
    output = result.stdout
    for line in output.split("\n"):
        line = line.strip()
        if line.startswith("{"):
            try:
                start = output.index(line)
                depth = 0
                for i, ch in enumerate(output[start:]):
                    if ch == "{": depth += 1
                    elif ch == "}": depth -= 1
                    if depth == 0:
                        script = json.loads(output[start:start+i+1])
                        log("SCRIPT", f"OK: {len(script.get('suggested_visual_beats', []))} beats, {script.get('estimated_duration', 0)}s")
                        return script
            except (json.JSONDecodeError, ValueError):
                continue

    log("SCRIPT", "Failed to parse script output")
    return None


def run_producer(script: dict, output_dir: Path) -> str | None:
    story_id = script.get("story_id", "unknown")
    log("PRODUCER", f"Rendering video for: {script.get('hook', '')[:50]}...")

    # Save script for producer
    script_path = output_dir / f"{story_id}_script.json"
    with open(script_path, "w") as f:
        json.dump(script, f, indent=2)

    # Run build_video.py. The producer directs the visuals inline; handing it the
    # research report lets the Art Director choose a semantic accent and write
    # accurate illustration briefs.
    cmd = [
        get_python_exec(), str(PROJECT_ROOT / "producer" / "build_video.py"),
        str(script_path),
        "--output", str(output_dir / f"{story_id}.mp4"),
        "--illustrations", os.getenv("COLONYV_ILLUSTRATION_BUDGET", "4"),
    ]
    research_path = output_dir / f"{story_id}_research.json"
    if research_path.exists():
        cmd += ["--research-json", str(research_path)]

    result = subprocess.run(
        cmd, capture_output=True, text=True,
        cwd=str(PROJECT_ROOT), timeout=int(os.getenv("PRODUCER_TIMEOUT", "1800")),
        env={**os.environ, "GROQ_API_KEY": GROQ_API_KEY},
    )

    if result.returncode != 0:
        log("PRODUCER", f"Failed: {result.stderr[-200:]}")
        return None

    # Check the known output path
    expected = Path(output_dir) / f"{story_id}.mp4"
    if expected.exists():
        log("PRODUCER", f"OK: {expected.name} ({expected.stat().st_size / 1024 / 1024:.1f} MB)")
        return str(expected)

    # Fallback: find any MP4
    for f in output_dir.glob("*.mp4"):
        log("PRODUCER", f"OK: {f.name} ({f.stat().st_size / 1024 / 1024:.1f} MB)")
        return str(f)

    log("PRODUCER", "No MP4 found in output")
    return None


def run_publisher(mp4_path: str, script: dict) -> str | None:
    import os as _os
    from colonyv_agent import publishing

    _topic = _os.environ.get("COLONY_TOPIC_PROMPT", "")
    title = publishing.build_title(script)
    description = publishing.build_description(script, topic=_topic)
    tags = publishing.build_keyword_tags(topic=_topic)

    log("PUBLISHER", f"Uploading: {Path(mp4_path).name}")

    py_exec = get_python_exec()
    cmd = [
        py_exec, "publisher/youtube.py", "upload", mp4_path,
        "--title", title,
        "--description", description,
        "--tags", ",".join(tags),
    ]

    result = subprocess.run(
        cmd, capture_output=True, text=True,
        cwd=str(AGENTS_DIR), timeout=120
    )

    if result.returncode != 0:
        log("PUBLISHER", f"Failed: {result.stderr[-200:]}")
        return None

    # Parse video ID from stdout
    for line in result.stdout.split("\n"):
        if "Video ID:" in line:
            video_id = line.split("Video ID:")[-1].strip()
            log("PUBLISHER", f"Upload complete! Video: https://youtube.com/watch?v={video_id}")
            return video_id

    log("PUBLISHER", "Upload complete (no video ID captured)")
    return None


def main():
    parser = argparse.ArgumentParser(description="Content Ops Pipeline")
    parser.add_argument("--stories", type=int, default=1, help="Number of stories to process")
    parser.add_argument("--skip-publish", action="store_true", help="Skip YouTube upload")
    parser.add_argument(
        "--sandbox",
        action="store_true",
        help="Sandbox mode: run the full pipeline end to end but never upload to YouTube",
    )
    args = parser.parse_args()

    # --sandbox is the documented way for evaluators to exercise the whole
    # pipeline safely. It previously appeared in the README and this module's
    # docstring without ever being defined, so the documented command failed.
    skip_publish = args.skip_publish or args.sandbox

    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir = PROJECT_ROOT / "output" / run_id
    output_dir.mkdir(parents=True, exist_ok=True)

    log("PIPELINE", f"=== Starting pipeline run {run_id} ===")
    log("PIPELINE", f"Output dir: {output_dir}")
    log("PIPELINE", f"Processing {args.stories} stories")
    if args.sandbox:
        log("PIPELINE", "Sandbox mode: rendering only, no YouTube upload")

    # Step 1: Monitor
    stories = run_monitor(top=args.stories * 3)  # Fetch extra for dedup
    if not stories:
        log("PIPELINE", "No stories found. Exiting.")
        return

    # Process stories
    results = []
    for i, story in enumerate(stories[:args.stories]):
        story_id = story.get("story_id", f"story_{i}")
        log("PIPELINE", f"\n--- Story {i+1}/{min(args.stories, len(stories))}: {story.get('title', 'Unknown')[:60]} ---")

        pipeline_state = {"research": None, "script": None, "error": None}
        success = False

        for attempt in range(3):
            if attempt > 0:
                log("PIPELINE", f"  Retry {attempt}/1...")
                time.sleep(10)

            # Step 2: Research
            research = run_research(story, output_dir)
            if not research:
                log("PIPELINE", "  Research failed, retrying...")
                continue

            # Step 3: Script
            script = run_scriptwriter(research, output_dir)
            if not script:
                log("PIPELINE", "  Script failed, retrying...")
                continue

            script["story_id"] = story_id
            success = True
            break

        if not success:
            log("PIPELINE", "  Skipping story (research/script failed)")
            continue

        # Step 4: Producer
        mp4_path = run_producer(script, output_dir)
        if not mp4_path:
            log("PIPELINE", "  Skipping story (render failed)")
            continue

        # Step 5: Publisher
        video_id = None
        if not skip_publish:
            video_id = run_publisher(mp4_path, script)
        else:
            reason = "--sandbox" if args.sandbox else "--skip-publish"
            log("PUBLISHER", f"Skipped ({reason})")

        results.append({
            "story_id": story_id,
            "title": story.get("title", ""),
            "mp4": mp4_path,
            "video_id": video_id,
            "published": video_id is not None,
        })

    # Summary
    log("PIPELINE", f"\n=== Pipeline complete: {len(results)}/{args.stories} stories processed ===")
    for r in results:
        status = "PUBLISHED" if r["published"] else "RENDERED"
        vid = f" → youtube.com/watch?v={r['video_id']}" if r.get("video_id") else ""
        log("PIPELINE", f"  [{status}] {r['title'][:50]}{vid}")

    # Save run summary
    summary_path = output_dir / "run_summary.json"
    with open(summary_path, "w") as f:
        json.dump({
            "run_id": run_id,
            "timestamp": datetime.now().isoformat(),
            "results": results,
        }, f, indent=2)
    log("PIPELINE", f"Summary saved to {summary_path}")


if __name__ == "__main__":
    main()
