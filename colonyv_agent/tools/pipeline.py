"""ADK tools that wrap the real ColonyV agent executables.

These tools let the Editorial Director actually operate the production line:
discover stories, research them, write scripts, render video, publish to
YouTube, and analyze the performance of a run. Each tool reads/writes its
artifacts in the run's output directory so the dashboard and Firestore can
surface the same data the legacy sequential pipeline produces.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from google.adk.tools import ToolContext

from colonyv_agent import pipeline_runtime as runtime

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
AGENTS_DIR = PROJECT_ROOT / "agents"


def get_python_exec() -> str:
    venv_py = PROJECT_ROOT / ".venv" / "bin" / "python3"
    if venv_py.exists():
        return str(venv_py)
    return sys.executable


def _ensure_run(run_id: str) -> Path:
    if not runtime.output_dir:
        raise RuntimeError("Pipeline output directory is not configured")
    run_dir = runtime.output_dir / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    return run_dir


def _write(run_dir: Path, name: str, data: Any) -> None:
    with open(run_dir / name, "w") as f:
        json.dump(data, f, indent=2)


def _read(run_dir: Path, name: str) -> Any | None:
    path = run_dir / name
    if not path.exists():
        return None
    with open(path) as f:
        return json.load(f)


def _parse_json_output(output: str, expect: str = "object") -> Any | None:
    marker_char = "[" if expect == "array" else "{"
    end_char = "]" if expect == "array" else "}"

    header_idx = output.rfind("=== Top")
    start_base = header_idx if header_idx != -1 else 0

    candidates = []
    for i in range(start_base, len(output)):
        if output[i] == marker_char:
            candidates.append(i)

    best: tuple[int, Any] | None = None
    for start in candidates:
        try:
            depth = 0
            in_string = False
            escape = False
            for i, ch in enumerate(output[start:]):
                if escape:
                    escape = False
                    continue
                if ch == "\\":
                    escape = True
                    continue
                if ch == '"':
                    in_string = not in_string
                    continue
                if in_string:
                    continue
                if ch == marker_char:
                    depth += 1
                elif ch == end_char:
                    depth -= 1
                if depth == 0:
                    parsed = json.loads(output[start : start + i + 1])
                    if best is None or (i + 1) > best[0]:
                        best = (i + 1, parsed)
                    break
        except (ValueError, json.JSONDecodeError):
            continue
    return best[1] if best else None


def run_script(
    cmd: list[str], *, cwd: str, timeout: int, step_label: str
) -> subprocess.CompletedProcess:
    if runtime.is_stop_requested():
        runtime.log(f"[{step_label}] skipped (stop requested)")
        return subprocess.CompletedProcess(cmd, -15, "", "")
    runtime.log(f"[{step_label}] starting: {' '.join(cmd)}")
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        cwd=cwd,
        env=runtime.process_env(),
        start_new_session=True,
    )
    runtime.set_active_process(proc)
    stdout_lines: list[str] = []
    try:
        start = time.monotonic()
        paused_before = runtime.paused_elapsed()
        paused_during = lambda: runtime.paused_elapsed() - paused_before
        while True:
            elapsed = (time.monotonic() - start) - paused_during()
            if elapsed > timeout:
                os.killpg(proc.pid, 9) if hasattr(os, "killpg") else proc.kill()
                proc.wait()
                return subprocess.CompletedProcess(cmd, -9, "\n".join(stdout_lines), "")
            line = proc.stdout.readline() if proc.stdout else ""
            if line:
                stripped = line.strip()
                if stripped:
                    runtime.log(f"[{step_label}] {stripped}")
                    stdout_lines.append(stripped)
                continue
            ret = proc.poll()
            if ret is not None:
                if proc.stdout:
                    for line in proc.stdout:
                        stripped = line.strip()
                        if stripped:
                            runtime.log(f"[{step_label}] {stripped}")
                            stdout_lines.append(stripped)
                runtime.log(f"[{step_label}] exited {ret}")
                return subprocess.CompletedProcess(cmd, ret, "\n".join(stdout_lines), "")
    finally:
        runtime.set_active_process(None)
        proc.wait()
        if proc.stdout:
            proc.stdout.close()


def discover_stories(tool_context: ToolContext) -> dict[str, Any]:
    """Scan RSS feeds, score candidates, and hand the ranked list to the director."""
    run_id = runtime.run_id or datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir = _ensure_run(run_id)
    tool_context.state["run_id"] = run_id
    tool_context.state["run_dir"] = str(run_dir)
    tool_context.state["stories"] = []

    result = run_script(
        [get_python_exec(), str(AGENTS_DIR / "monitor" / "monitor.py"), "--top", "10"],
        cwd=str(AGENTS_DIR),
        timeout=240,
        step_label="discover",
    )
    stories = _parse_json_output(result.stdout, expect="array") or []
    if not stories:
        return {"success": False, "error": "No stories were discovered", "stories": []}

    enriched = []
    for i, story in enumerate(stories):
        enriched.append({
            "index": i,
            "story_id": story.get("story_id", ""),
            "title": story.get("title", ""),
            "relevance_score": story.get("relevance_score", 0.0),
            "novelty_score": story.get("novelty_score", 0.0),
            "urgency_score": story.get("urgency_score", 0.0),
            "recommended_format": story.get("recommended_format", ""),
        })
        _write(run_dir, f"{story.get('story_id', f'story_{i}')}_monitor.json", story)

    tool_context.state["stories"] = enriched
    runtime.activity("monitor", "complete", f"Discovered {len(enriched)} ranked stories")
    return {
        "success": True,
        "count": len(enriched),
        "run_id": run_id,
        "stories": enriched,
    }


def research_story(story_index: int, tool_context: ToolContext) -> dict[str, Any]:
    """Collect and verify evidence for a specific discovered story."""
    stories = tool_context.state.get("stories", [])
    if not stories:
        return {"success": False, "error": "You must call discover_stories() first to load the ranked list."}
    if story_index < 0 or story_index >= len(stories):
        return {
            "success": False,
            "error": f"story_index must be between 0 and {max(0, len(stories) - 1)}",
        }

    story = stories[story_index]
    run_id = tool_context.state.get("run_id") or runtime.run_id
    run_dir = _ensure_run(run_id)
    tool_context.state["story_index"] = story_index
    tool_context.state["current_story"] = story

    story_id = story["story_id"]
    monitor_json = run_dir / f"{story_id}_monitor.json"
    if not monitor_json.exists():
        _write(run_dir, f"{story_id}_monitor.json", {
            "story_id": story_id,
            "title": story["title"],
            "relevance_score": story["relevance_score"],
            "novelty_score": story["novelty_score"],
            "urgency_score": story["urgency_score"],
        })

    runtime.activity("research", "active", f"Researching: {story['title'][:60]}")
    result = run_script(
        [get_python_exec(), str(AGENTS_DIR / "research" / "research.py"),
         "--story-json", str(monitor_json)],
        cwd=str(AGENTS_DIR),
        timeout=240,
        step_label=f"research-{story_id[:8]}",
    )
    research = _parse_json_output(result.stdout, expect="object")
    if not research:
        runtime.activity("research", "failed", "Research produced no report")
        return {"success": False, "error": "Research failed", "output": result.stdout[-400:]}

    research["story_id"] = story_id
    research["story_index"] = story_index
    research["sources_fetched"] = len(research.get("sources", []) or [])
    _write(run_dir, f"{story_id}_research.json", research)
    tool_context.state["research"] = research
    runtime.activity(
        "research",
        "complete",
        f"{len(research.get('claims', []))} claims, confidence={research.get('confidence')}",
    )
    return {
        "success": True,
        "summary": research.get("summary", ""),
        "confidence": research.get("confidence", "low"),
        "verified_claims": sum(1 for c in research.get("claims", []) if c.get("verified")),
        "total_claims": len(research.get("claims", [])),
        "contradictions": len(research.get("contradictions", [])),
        "entities": len(research.get("entities", [])),
        "sources_fetched": len(research.get("sources", []) or []),
        "story_id": story_id,
    }


def write_script(tool_context: ToolContext) -> dict[str, Any]:
    """Shape the verified research into a concise, story-specific script."""
    research = tool_context.state.get("research")
    if not research:
        return {"success": False, "error": "You must call research_story() first to produce a research report."}

    run_id = tool_context.state.get("run_id") or runtime.run_id
    run_dir = _ensure_run(run_id)
    story_id = research.get("story_id", runtime.run_id or "story")
    research_json = run_dir / f"{story_id}_research.json"
    if not research_json.exists():
        _write(run_dir, f"{story_id}_research.json", research)

    runtime.activity("script", "active", f"Writing script for {story_id[:8]}")
    result = run_script(
        [get_python_exec(), str(AGENTS_DIR / "scriptwriter" / "scriptwriter.py"),
         "--research-json", str(research_json)],
        cwd=str(AGENTS_DIR),
        timeout=180,
        step_label=f"script-{story_id[:8]}",
    )
    script = _parse_json_output(result.stdout, expect="object")
    if not script:
        runtime.activity("script", "failed", "Script produced no output")
        return {"success": False, "error": "Script failed", "output": result.stdout[-400:]}

    script["story_id"] = story_id
    _write(run_dir, f"{story_id}_script.json", script)
    tool_context.state["script"] = script
    runtime.activity(
        "script",
        "complete",
        f"{len(script.get('suggested_visual_beats', []))} beats, ~{script.get('estimated_duration', 0)}s",
    )
    return {
        "success": True,
        "hook": script.get("hook", ""),
        "estimated_duration": script.get("estimated_duration", 0),
        "beats": len(script.get("suggested_visual_beats", [])),
        "accent_color": script.get("accent_color", ""),
        "story_id": story_id,
    }


def plan_scenes(tool_context: ToolContext) -> dict[str, Any]:
    """Let the ScenePlanner choose the best Remotion scene template per beat."""
    script = tool_context.state.get("script")
    if not script:
        return {"success": False, "error": "You must call write_script() first to produce a script."}

    run_id = tool_context.state.get("run_id") or runtime.run_id
    run_dir = _ensure_run(run_id)
    story_id = script.get("story_id", run_id)
    script_json = run_dir / f"{story_id}_script.json"
    if not script_json.exists():
        _write(run_dir, f"{story_id}_script.json", script)

    runtime.activity("plan", "active", f"Planning scenes for {story_id[:8]}")
    result = run_script(
        [get_python_exec(), str(AGENTS_DIR / "planner" / "planner.py"),
         "--script-json", str(script_json)],
        cwd=str(AGENTS_DIR),
        timeout=180,
        step_label=f"plan-{story_id[:8]}",
    )
    plan = _parse_json_output(result.stdout, expect="object")
    if not plan or not plan.get("scenes"):
        runtime.activity("plan", "failed", "Scene plan produced no scenes")
        return {"success": False, "error": "Scene plan failed", "output": result.stdout[-400:]}

    plan["story_id"] = story_id
    _write(run_dir, f"{story_id}_scene_plan.json", plan)
    tool_context.state["scene_plan"] = plan
    runtime.activity(
        "plan",
        "complete",
        f"{len(plan['scenes'])} scenes planned, accent={plan.get('accent_color', '')}",
    )
    return {
        "success": True,
        "scenes": len(plan["scenes"]),
        "accent_color": plan.get("accent_color", ""),
        "story_id": story_id,
    }


def request_render(tool_context: ToolContext) -> dict[str, Any]:
    """Render the scripted story into a portrait MP4 via Remotion."""
    script = tool_context.state.get("script")
    if not script:
        return {"success": False, "error": "You must call write_script() first to produce a script."}

    run_id = tool_context.state.get("run_id") or runtime.run_id
    run_dir = _ensure_run(run_id)
    story_id = script.get("story_id", run_id)
    script_json = run_dir / f"{story_id}_script.json"
    if not script_json.exists():
        _write(run_dir, f"{story_id}_script.json", script)

    output_mp4 = run_dir / f"{story_id}.mp4"
    runtime.activity("render", "active", f"Rendering video for {story_id[:8]}")
    render_cmd = [
        get_python_exec(), str(PROJECT_ROOT / "producer" / "build_video.py"),
        str(script_json), "--output", str(output_mp4),
    ]
    scene_plan = run_dir / f"{story_id}_scene_plan.json"
    if scene_plan.exists():
        render_cmd += ["--scene-plan", str(scene_plan)]
    result = run_script(
        render_cmd,
        cwd=str(PROJECT_ROOT),
        timeout=int(os.getenv("PRODUCER_TIMEOUT", "1800")),
        step_label=f"render-{story_id[:8]}",
    )

    output_exists = output_mp4.exists()
    output_size = output_mp4.stat().st_size if output_exists else 0
    if output_exists:
        tool_context.state["mp4_path"] = str(output_mp4)
        runtime.activity("render", "complete", f"Rendered {output_size / 1024 / 1024:.1f} MB")
    else:
        runtime.activity("render", "failed", f"Render exit {result.returncode}")

    return {
        "success": result.returncode == 0 and output_exists,
        "output_exists": output_exists,
        "output_size_bytes": output_size,
        "mp4_path": str(output_mp4),
        "story_id": story_id,
    }


def publish_to_youtube(tool_context: ToolContext) -> dict[str, Any]:
    """Upload the rendered MP4 to YouTube as a public video."""
    script = tool_context.state.get("script")
    mp4_path = tool_context.state.get("mp4_path")
    if not script or not mp4_path:
        return {"success": False, "error": "You must request_render() a finished MP4 before publishing."}

    if runtime.skip_publish:
        runtime.log("[publish] Publishing is disabled for this run (skip_publish).")
        return {"success": False, "skipped": True, "reason": "skip_publish is enabled", "video_id": ""}

    run_id = tool_context.state.get("run_id") or runtime.run_id
    run_dir = _ensure_run(run_id)
    story_id = script.get("story_id", run_id)

    runtime.activity("publish", "active", f"Publishing {story_id[:8]} to YouTube")
    mp4 = Path(mp4_path)
    if not mp4.exists():
        return {"success": False, "error": f"MP4 not found: {mp4_path}"}

    cmd = [
        get_python_exec(), str(AGENTS_DIR / "publisher" / "youtube.py"),
        "upload", str(mp4),
        "--title", (script.get("hook", "AI News Update") or "AI News Update")[:100],
        "--description", (script.get("body", "") or "")[:5000],
        "--tags", "ai,tech,news,agents",
        "--privacy", "public",
    ]
    result = run_script(
        cmd, cwd=str(AGENTS_DIR), timeout=120, step_label=f"publish-{story_id[:8]}"
    )

    video_id = ""
    for line in result.stdout.split("\n"):
        if "Video ID:" in line:
            video_id = line.split("Video ID:")[-1].strip()
            break

    if video_id:
        tool_context.state["video_id"] = video_id
        runtime.activity("publish", "complete", f"Published to youtube.com/watch?v={video_id}")
    else:
        runtime.activity("publish", "failed", f"Upload exit {result.returncode}")

    return {
        "success": bool(video_id),
        "video_id": video_id,
        "story_id": story_id,
    }


def analyze_performance(tool_context: ToolContext) -> dict[str, Any]:
    """Run the analyst over the completed run's artifacts."""
    run_id = tool_context.state.get("run_id") or runtime.run_id
    run_dir = _ensure_run(run_id)
    if not list(run_dir.glob("*.json")):
        return {"success": False, "error": "No run artifacts found to analyze."}

    runtime.activity("analyst", "active", "Analyzing run performance")
    result = run_script(
        [get_python_exec(), str(AGENTS_DIR / "analyst" / "analyst.py"),
         "--run-dir", str(run_dir)],
        cwd=str(AGENTS_DIR),
        timeout=120,
        step_label="analyst",
    )
    analyst_path = run_dir / "analyst_output.json"
    if not analyst_path.exists():
        data = _parse_json_output(result.stdout, expect="object")
        if data:
            _write(run_dir, "analyst_output.json", data)
    if analyst_path.exists():
        with open(analyst_path) as f:
            data = json.load(f)
        runtime.activity("analyst", "complete", "Saved learned signals")
        return {"success": True, "analyst": data}
    runtime.activity("analyst", "failed", f"Analyst exit {result.returncode}")
    return {"success": False, "error": "Analyst produced no output", "output": result.stdout[-400:]}