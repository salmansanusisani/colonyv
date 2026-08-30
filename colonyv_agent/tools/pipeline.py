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
import selectors
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
    path = run_dir / name
    tmp = path.with_suffix(path.suffix + ".tmp")
    try:
        with open(tmp, "w") as f:
            json.dump(data, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except OSError:
        try:
            if tmp.exists():
                tmp.unlink()
        except OSError:
            pass


def _read(run_dir: Path, name: str) -> Any | None:
    path = run_dir / name
    if not path.exists():
        return None
    try:
        with open(path) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError, ValueError):
        return None


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
        # Readiness-based reads. A plain readline() blocks until a newline or EOF,
        # so a child that hangs without printing (stalled Chromium launch, a
        # socket read with no deadline) never let the loop re-check the timeout
        # and the run froze forever with no error. select() lets the deadline win.
        selector = selectors.DefaultSelector()
        if proc.stdout is not None:
            selector.register(proc.stdout, selectors.EVENT_READ)
        try:
            while True:
                elapsed = (time.monotonic() - start) - paused_during()
                if elapsed > timeout:
                    runtime.log(f"[{step_label}] timed out after {timeout}s; terminating")
                    try:
                        os.killpg(proc.pid, 9) if hasattr(os, "killpg") else proc.kill()
                    except (ProcessLookupError, PermissionError):
                        proc.kill()
                    proc.wait()
                    return subprocess.CompletedProcess(cmd, -9, "\n".join(stdout_lines), "")

                line = ""
                if selector.get_map() and selector.select(timeout=0.5):
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
            selector.close()
    finally:
        runtime.unregister_process(proc)
        proc.wait()
        if proc.stdout:
            proc.stdout.close()


def discover_stories(tool_context: ToolContext) -> dict[str, Any]:
    """Scan RSS feeds, score candidates, and hand the ranked list to the director."""
    import uuid
    run_id = runtime.run_id or (
        f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:4]}"
    )
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


def direct_visuals(tool_context: ToolContext) -> dict[str, Any]:
    """Have the Art Director author this episode's visual plan.

    Replaces the legacy `plan_scenes` tool. Where the old ScenePlanner only chose
    one of six fixed Remotion templates per beat, the Art Director authors the
    palette, the illustration style contract, and a per-shot composition spec
    including a bespoke illustration prompt.
    """
    script = tool_context.state.get("script")
    if not script:
        return {"success": False, "error": "You must call write_script() first to produce a script."}

    run_id = tool_context.state.get("run_id") or runtime.run_id
    run_dir = _ensure_run(run_id)
    story_id = script.get("story_id", run_id)

    script_json = run_dir / f"{story_id}_script.json"
    if not script_json.exists():
        _write(run_dir, f"{story_id}_script.json", script)

    research = tool_context.state.get("research")
    research_json = run_dir / f"{story_id}_research.json"
    if research and not research_json.exists():
        _write(run_dir, f"{story_id}_research.json", research)

    budget = int(os.getenv("COLONYV_ILLUSTRATION_BUDGET", "4"))

    runtime.activity("direct", "active", f"Directing visuals for {story_id[:8]}")
    cmd = [
        get_python_exec(), str(AGENTS_DIR / "artdirector" / "artdirector.py"),
        "--script-json", str(script_json),
        "--illustrations", str(budget),
        "--allow-fallback",
    ]
    if research_json.exists():
        cmd += ["--research-json", str(research_json)]

    result = run_script(
        cmd, cwd=str(AGENTS_DIR), timeout=240, step_label=f"direct-{story_id[:8]}"
    )
    plan = _parse_json_output(result.stdout, expect="object")
    if not plan or not plan.get("shots"):
        runtime.activity("direct", "failed", "Art director produced no plan")
        return {"success": False, "error": "Art direction failed", "output": result.stdout[-400:]}

    plan["story_id"] = story_id
    _write(run_dir, f"{story_id}_visual_plan.json", plan)
    tool_context.state["visual_plan"] = plan

    layouts = [s.get("layout", "?") for s in plan["shots"]]
    illustrated = sum(1 for s in plan["shots"] if s.get("illustration"))
    palette = plan.get("palette", {})
    runtime.activity(
        "direct",
        "complete",
        f"{len(layouts)} shots, {len(set(layouts))} distinct layouts, "
        f"{illustrated} illustrations, accent={palette.get('accent_role')}",
    )
    return {
        "success": True,
        "concept": plan.get("concept", ""),
        "shots": len(plan["shots"]),
        "distinct_layouts": len(set(layouts)),
        "illustrations_planned": illustrated,
        "accent": palette.get("accent", ""),
        "accent_role": palette.get("accent_role", ""),
        "motion_language": plan.get("motion_language", ""),
        "story_id": story_id,
    }


def plan_scenes(tool_context: ToolContext) -> dict[str, Any]:
    """Deprecated alias for direct_visuals, kept so older callers keep working."""
    return direct_visuals(tool_context)


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
        "--illustrations", os.getenv("COLONYV_ILLUSTRATION_BUDGET", "4"),
    ]

    # Prefer the plan the Art Director stage already produced so the dashboard
    # and the render agree on the same direction.
    visual_plan = run_dir / f"{story_id}_visual_plan.json"
    if visual_plan.exists():
        render_cmd += ["--visual-plan", str(visual_plan)]

    research_json = run_dir / f"{story_id}_research.json"
    if research_json.exists():
        render_cmd += ["--research-json", str(research_json)]

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
    """Upload the rendered MP4 to YouTube.

    Privacy is decided by the publication gate, not hardcoded. A story that
    cleared verification publishes publicly; one the gate flagged uploads unlisted
    so the run still produces a reviewable artifact without putting unverified
    claims in front of an audience. The caller signals this by setting
    `publish_privacy` in state.
    """
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

    privacy = tool_context.state.get("publish_privacy") or "public"
    if privacy not in {"public", "unlisted", "private"}:
        privacy = "public"
    if privacy != "public":
        runtime.log(f"[publish] uploading as {privacy} (publication gate was not satisfied)")

    # Metadata is derived from what this run actually found (researched entities,
    # the run topic, the story format) instead of a static tag string, and the
    # description gets real paragraphs, sources and hashtags. YouTube renders the
    # first three description hashtags above the title.
    from colonyv_agent import publishing

    research = tool_context.state.get("research") or {}
    story = tool_context.state.get("current_story") or {}
    topic = os.environ.get("COLONY_TOPIC_PROMPT", "")
    hashtags = publishing.build_hashtags(
        entities=research.get("entities"),
        topic=topic,
        story_format=script.get("format") or story.get("recommended_format", ""),
    )
    description = publishing.build_description(
        script, research=research, story=story, topic=topic, hashtags=hashtags
    )
    keyword_tags = publishing.build_keyword_tags(
        entities=research.get("entities"), topic=topic
    )
    if hashtags:
        runtime.log(f"[publish] hashtags: {' '.join('#' + h for h in hashtags)}")

    cmd = [
        get_python_exec(), str(AGENTS_DIR / "publisher" / "youtube.py"),
        "upload", str(mp4),
        "--title", publishing.build_title(script),
        "--description", description,
        "--tags", ",".join(keyword_tags),
        "--privacy", privacy,
    ]
    # A 14-25 MB upload over conference wifi routinely exceeds two minutes, and
    # the resumable upload prints no progress for files under its 100 MB chunk
    # size, so the old 120s deadline killed uploads that were still working.
    upload_timeout = int(os.environ.get("COLONYV_PUBLISH_TIMEOUT", "600"))
    result = run_script(
        cmd, cwd=str(AGENTS_DIR), timeout=upload_timeout, step_label=f"publish-{story_id[:8]}"
    )

    video_id = ""
    for line in result.stdout.split("\n"):
        if "Video ID:" in line:
            video_id = line.split("Video ID:")[-1].strip()
            break

    # A non-zero exit means the publisher failed after printing the id (thumbnail
    # or playlist step, quota, rejected upload). Scraping stdout alone reported
    # those as successes.
    succeeded = bool(video_id) and result.returncode == 0

    if succeeded:
        tool_context.state["video_id"] = video_id
        suffix = "" if privacy == "public" else f" ({privacy})"
        runtime.activity(
            "publish", "complete", f"Published to youtube.com/watch?v={video_id}{suffix}"
        )
    else:
        runtime.activity("publish", "failed", f"Upload exit {result.returncode}")

    return {
        "success": succeeded,
        "video_id": video_id,
        "privacy": privacy,
        "story_id": story_id,
        "returncode": result.returncode,
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