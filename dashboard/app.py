#!/usr/bin/env python3
"""
Content Ops Dashboard - FastAPI backend.

Provides:
- Pipeline control (start/stop/status)
- Live log streaming via WebSocket
- Analytics from past runs
- YouTube channel analytics
- Scheduler for automated runs
- Cost tracking
"""

import asyncio
import json
import os
import signal
import subprocess
import sys
import threading
import time
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

try:
    from colonyv_agent.cloud_state import get_cloud_state
except ImportError:
    get_cloud_state = lambda: None

PROJECT_ROOT = Path(__file__).resolve().parent.parent
# Load environment variables from .env if present
try:
    from dotenv import load_dotenv
    load_dotenv(dotenv_path=Path(__file__).resolve().parent.parent / ".env")
except ImportError:
    pass
AGENTS_DIR = PROJECT_ROOT / "agents"
OUTPUT_DIR = PROJECT_ROOT / "output"
DASHBOARD_DIR = Path(__file__).resolve().parent
CONFIG_DIR = PROJECT_ROOT / "config"
SETTINGS_PATH = CONFIG_DIR / "settings.json"

DEFAULT_SETTINGS = {
    "pipeline": {
        "videos_per_run": 1,
        "skip_publish": False,
        "max_duration_seconds": 60,
    },
    "model": {
        "provider": "gemini",
        "model_id": os.environ.get("COLONY_MODEL_ID", "gemini/gemini-3.5-flash"),
        "api_keys": {},
    },
    "content": {
        "categories": ["ai", "tech", "crypto"],
        "active_topic": "AI & Machine Learning",
        "custom_topics": ["AI & Machine Learning", "Cryptocurrency", "Big Tech & Startups", "Hardware & GPUs"],
        "topic_prompt": "",
        "brand_voice": "engaging_news",
    },
    "scheduler": {
        "enabled": True,
        "interval_hours": 6,
        "videos_per_run": 1,
    },
    "notifications": {
        "slack_webhook": "",
        "email_to": "",
        "on_complete": True,
        "on_error": True,
    },
}

MODEL_PROVIDER_CATALOG = {
    "gemini": {
        "label": "Google Gemini",
        "key_env": "GEMINI_API_KEY",
        "models": [
            "gemini/gemini-3.5-flash",
            "gemini/gemini-2.5-flash",
            "gemini/gemini-2.5-pro",
        ],
    },
}


def load_settings() -> dict:
    settings = json.loads(json.dumps(DEFAULT_SETTINGS))
    if SETTINGS_PATH.exists():
        try:
            with open(SETTINGS_PATH) as f:
                saved = json.load(f)
            for section, values in saved.items():
                if isinstance(values, dict) and section in settings:
                    settings[section].update(values)
        except (OSError, json.JSONDecodeError):
            pass
    # Public publishing is the only dashboard mode; discard the old privacy setting.
    settings["pipeline"].pop("youtube_privacy", None)
    # Vertex AI authenticates via application credentials; no API keys stored.
    settings["model"].pop("api_key", None)
    settings["model"].setdefault("api_keys", {})
    settings["model"]["api_keys"] = {"gemini": settings["model"].get("api_keys", {}).get("gemini", "")}
    settings["model"]["api_keys"] = {}
    settings["model"]["provider"] = "gemini"
    settings["model"]["model_id"] = os.environ.get("COLONY_MODEL_ID", "gemini/gemini-3.5-flash")
    return settings


settings = load_settings()
APP_STARTED_AT = time.time()
CLOUD_STATE = None


_last_persist_ts: float = 0.0


def persist_pipeline_state(force: bool = False) -> None:
    """Persist run state to Firestore, throttled so streaming logs do not
    saturate the executor with a synchronous write per line."""
    global _last_persist_ts
    if not CLOUD_STATE or not pipeline_state.get("run_id"):
        return
    now = time.monotonic()
    if not force and (now - _last_persist_ts) < 0.5:
        return
    _last_persist_ts = now
    try:
        CLOUD_STATE.save_run(
            pipeline_state["run_id"],
            {
                key: value
                for key, value in pipeline_state.items()
                if key != "current_process"
            },
        )
    except Exception as exc:
        print(f"[cloud-state] Firestore persistence failed: {exc}", flush=True)


def save_settings() -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    with open(SETTINGS_PATH, "w") as f:
        json.dump(settings, f, indent=2)

app = FastAPI(title="COLONY — Autonomous Media Orchestrator")
app.mount("/static", StaticFiles(directory=str(DASHBOARD_DIR / "static")), name="static")
templates = Jinja2Templates(directory=str(DASHBOARD_DIR / "templates"))

# --- Global state ---
pipeline_state = {
    "running": False,
    "paused": False,
    "run_id": None,
    "current_step": None,
    "progress": 0,
    "logs": [],
    "content_count": 0,
    "content_done": 0,
    "start_time": None,
    "paused_duration": 0.0,
    "pause_start": None,
    "current_process": None,
    "active_agent": None,
    "agent_message": "Waiting for a run",
    "agent_activity": {},
}

AGENT_DEFINITIONS = [
    ("monitor", "Discovery Agent", "Find and rank the most valuable stories"),
    ("research", "Research Agent", "Gather evidence and test claims"),
    ("script", "Scriptwriter Agent", "Shape evidence into a concise story"),
    ("plan", "Scene Planner", "Choose the best scene template per beat"),
    ("render", "Visual Producer", "Build narration, scenes, and motion"),
    ("publish", "Publisher Agent", "Deliver the finished video to YouTube"),
    ("analyst", "Analyst Agent", "Learn signals from the completed run"),
]


def reset_agent_activity() -> None:
    pipeline_state["active_agent"] = None
    pipeline_state["agent_message"] = "Waiting for a run"
    pipeline_state["agent_activity"] = {
        key: {
            "key": key,
            "name": name,
            "description": description,
            "status": "pending",
            "detail": "Waiting",
            "started_at": None,
            "finished_at": None,
        }
        for key, name, description in AGENT_DEFINITIONS
    }


def set_agent_activity(key: str, status: str, detail: str) -> None:
    if key not in pipeline_state["agent_activity"]:
        return
    now = datetime.now().isoformat()
    activity = pipeline_state["agent_activity"][key]
    activity.update({"status": status, "detail": detail})
    if status == "active" and not activity.get("started_at"):
        activity["started_at"] = now
    if status in {"complete", "failed", "skipped"}:
        activity["finished_at"] = now
    if status == "active":
        pipeline_state["active_agent"] = key
        pipeline_state["agent_message"] = detail
    persist_pipeline_state()


reset_agent_activity()

log_subscribers: list[WebSocket] = []
app_loop: asyncio.AbstractEventLoop | None = None


def get_python_exec() -> str:
    venv_py = PROJECT_ROOT / ".venv" / "bin" / "python3"
    if venv_py.exists():
        return str(venv_py)
    return sys.executable


def log(msg: str):
    ts = datetime.now().strftime("%H:%M:%S")
    entry = f"[{ts}] {msg}"
    pipeline_state["logs"].append(entry)
    if len(pipeline_state["logs"]) > 500:
        pipeline_state["logs"] = pipeline_state["logs"][-500:]
    print(entry, flush=True)
    persist_pipeline_state()
    run_id = pipeline_state.get("run_id")
    if run_id:
        try:
            run_dir = OUTPUT_DIR / run_id
            run_dir.mkdir(parents=True, exist_ok=True)
            with open(run_dir / "pipeline.log", "a") as f:
                f.write(entry + "\n")
        except OSError:
            pass
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(broadcast_log(entry))
    except RuntimeError:
        if app_loop and app_loop.is_running():
            asyncio.run_coroutine_threadsafe(broadcast_log(entry), app_loop)


async def broadcast_log(msg: str):
    dead = []
    for ws in log_subscribers:
        try:
            await ws.send_text(msg)
        except Exception:
            dead.append(ws)
    for ws in dead:
        log_subscribers.remove(ws)


# --- API Routes ---

@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    template = templates.get_template("dashboard.html")
    return HTMLResponse(content=template.render(request=request))


@app.get("/healthz")
async def healthz():
    return {"status": "ok", "service": "colonyv"}


@app.get("/icon_logo.png", include_in_schema=False)
async def icon_logo():
    return FileResponse(PROJECT_ROOT / "icon_logo.png", media_type="image/png")


@app.get("/api/status")
async def api_status():
    start = pipeline_state.get("start_time")
    paused = pipeline_state.get("paused")
    p_start = pipeline_state.get("pause_start")
    p_dur = pipeline_state.get("paused_duration", 0.0)
    
    if start:
        if paused and p_start:
            elapsed = p_start - start - p_dur
        else:
            elapsed = time.time() - start - p_dur
    else:
        elapsed = 0.0

    return {
        "running": pipeline_state["running"],
        "paused": pipeline_state["paused"],
        "run_id": pipeline_state["run_id"],
        "current_step": pipeline_state["current_step"],
        "progress": pipeline_state["progress"],
        "content_count": pipeline_state["content_count"],
        "content_done": pipeline_state["content_done"],
        "elapsed": max(0.0, elapsed),
        "uptime": time.time() - APP_STARTED_AT,
        "next_run": scheduler_config.get("next_run") if "scheduler_config" in globals() else None,
        "active_agent": pipeline_state["active_agent"],
        "agent_message": pipeline_state["agent_message"],
        "agent_activity": pipeline_state["agent_activity"],
        "logs": pipeline_state["logs"][-30:],
    }


@app.post("/api/agent/invoke")
async def api_agent_invoke(request: Request):
    body = await request.json()
    message = str(body.get("message", "")).strip()
    if not message:
        return JSONResponse({"error": "message is required"}, 400)
    from colonyv_agent.invoke import invoke_editorial_director

    result = await invoke_editorial_director(message)
    if CLOUD_STATE:
        CLOUD_STATE.save_run(
            f"agent-{result['session_id']}",
            {"type": "adk_invocation", "message": message, **result},
        )
    return result


@app.post("/api/agent/run")
async def launch_production_run(stories: int, *, source: str = "manual") -> dict[str, Any]:
    """Start a full autonomous production run through the ADK Production Director."""
    skip_publish = False

    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir = OUTPUT_DIR / run_id
    output_dir.mkdir(parents=True, exist_ok=True)

    pipeline_state.update({
        "running": True,
        "paused": False,
        "run_id": run_id,
        "current_step": "agent-orchestrated",
        "progress": 0,
        "logs": [],
        "content_count": stories,
        "content_done": 0,
        "start_time": time.time(),
        "paused_duration": 0.0,
        "pause_start": None,
        "stage_state": {},
    })
    reset_agent_activity()
    persist_pipeline_state()

    model_id = settings["model"].get("model_id", "gemini/gemini-3.5-flash")
    model_env = {
        **os.environ,
        "COLONY_MODEL_ID": model_id,
        "COLONYV_GEMINI_MODEL": model_id.removeprefix("gemini/"),
        "COLONY_MAX_DURATION_SECONDS": str(settings["pipeline"].get("max_duration_seconds", 60)),
        "COLONY_TOPIC_PROMPT": settings["content"].get("active_topic", ""),
    }
    if os.environ.get("GOOGLE_CLOUD_PROJECT"):
        model_env["GOOGLE_GENAI_USE_VERTEXAI"] = "true"
    model_env.pop("GOOGLE_API_KEY", None)
    model_env.pop("GEMINI_API_KEY", None)

    from colonyv_agent import pipeline_runtime

    pipeline_runtime.configure(
        logger=log,
        activity=set_agent_activity,
        env=model_env,
        out_dir=OUTPUT_DIR,
        run=run_id,
        skip=skip_publish,
    )

    if bool(settings["pipeline"].get("async_stages", False)):
        pipeline_state["stage_state"] = {"stories_target": stories, "run_id": run_id}
        pipeline_state["current_step"] = "async-scheduled"
        persist_pipeline_state(force=True)
        from cloud import pubsub as ps

        ps.publish_stage(
            settings.get("cloud", {}).get("project_id") or os.environ.get("GOOGLE_CLOUD_PROJECT", ""),
            run_id,
            "monitor",
        )
        log("Async pipeline scheduled: monitor stage published")
        return {"status": "started", "mode": "adk-async", "run_id": run_id}

    asyncio.create_task(run_production_director(stories))

    return {"status": "started", "mode": "adk-production", "run_id": run_id}


async def api_agent_run(request: Request):
    """Start a full autonomous production run through the ADK Production Director."""
    global app_loop
    app_loop = asyncio.get_running_loop()

    if pipeline_state["running"]:
        return JSONResponse({"error": "Pipeline already running"}, 409)

    await request.json()
    stories = int(settings["pipeline"].get("videos_per_run", 1))

    return await launch_production_run(stories, source="manual")


async def run_production_director(stories: int):
    from colonyv_agent.factory import run_factory_async

    try:
        result = await run_factory_async(stories)
        from colonyv_agent import pipeline_runtime as rt
        if rt.is_stop_requested():
            log("ADK production stopped by operator.")
            pipeline_state["current_step"] = "stopped"
        elif result.get("error"):
            log(f"ADK production failed: {result['error']}")
        else:
            produced = result.get("stories_produced", [])
            log(f"ADK production completed with {len(produced)} finished story(ies).")
        if CLOUD_STATE:
            CLOUD_STATE.save_run(
                pipeline_state["run_id"],
                {
                    **pipeline_state,
                    "type": "adk_production_run",
                    "factory_result": result,
                },
            )
        if not rt.is_stop_requested():
            pipeline_state["progress"] = 100
            pipeline_state["current_step"] = "complete"
    except Exception as e:
        log(f"ADK production error: {e}")
        if notification_config.get("on_error"):
            await send_notification(f"ADK production error: {e}")
    finally:
        pipeline_state["running"] = False
        pipeline_state["start_time"] = None
        persist_pipeline_state(force=True)
        
        if scheduler_config.get("enabled") and scheduler_config.get("next_run"):
            try:
                dt = datetime.fromisoformat(scheduler_config["next_run"])
                log(f"Agent entering standby. Next scheduled run at {dt.strftime('%I:%M %p on %b %d')}.")
            except Exception:
                log("Agent entering standby until next scheduled run.")


async def handle_stage_message(run_id: str, stage: str, story_index: int, attempt: int) -> None:
    """Execute one async pipeline stage and publish the next one(s)."""
    from colonyv_agent import pipeline_runtime, stages

    if runtime_state_run_id(run_id) != run_id:
        pipeline_runtime.configure(
            logger=log,
            activity=set_agent_activity,
            env=dict(os.environ),
            out_dir=OUTPUT_DIR,
            run=run_id,
            skip=bool(settings["pipeline"].get("skip_publish", True)),
        )

    state = dict(pipeline_state.get("stage_state") or {})
    state.setdefault("run_id", run_id)
    state.setdefault("stories_target", int(settings["pipeline"].get("videos_per_run", 1)))

    log(f"[async] running stage {stage} (story={story_index}, attempt={attempt})")
    result = await asyncio.get_running_loop().run_in_executor(
        None, lambda: stages.run_stage(state, stage, story_index, attempt)
    )

    pipeline_state["stage_state"] = result["state"]
    pipeline_state["current_step"] = f"stage:{stage}"
    pipeline_state["agent_message"] = f"Async stage {stage}"
    log(
        f"[async] stage {stage} -> {result['decision']} "
        f"next={[(s, i, a) for s, i, a in result.get('next', [])]}"
    )

    project_id = settings.get("cloud", {}).get("project_id") or os.environ.get("GOOGLE_CLOUD_PROJECT", "")
    from cloud import pubsub as ps

    if result.get("next"):
        ps.publish_next(project_id, run_id, result)
    else:
        pipeline_state["progress"] = 100
        pipeline_state["current_step"] = "complete"
        pipeline_state["running"] = False
        pipeline_state["start_time"] = None
        log(f"[async] run {run_id} completed ({result.get('decision')})")
    persist_pipeline_state(force=True)


def runtime_state_run_id(run_id: str) -> str:
    from colonyv_agent import pipeline_runtime as pr

    return pr.run_id or run_id


@app.post("/api/pubsub/run-stage")
async def api_pubsub_run_stage(request: Request):
    """Pub/Sub push webhook: executes one pipeline stage message."""
    try:
        payload = await request.json()
        message = payload.get("message", {})
        attrs = message.get("attributes", {})
        run_id = attrs.get("run_id", "")
        stage = attrs.get("stage", "")
        story_index = int(attrs.get("story_index", 0))
        attempt = int(attrs.get("attempt", 1))
        if not run_id or stage not in {"monitor", "research", "script", "plan", "render", "publish", "analyst"}:
            return JSONResponse({"error": "invalid message"}, 400)
        asyncio.create_task(handle_stage_message(run_id, stage, story_index, attempt))
        return JSONResponse({"ok": True, "ack": True})
    except Exception as e:
        log(f"[pubsub] handler error: {e}")
        return JSONResponse({"error": str(e)}, 500)


@app.get("/api/runs")
async def api_runs(limit: int = 20):
    runs = []
    if OUTPUT_DIR.exists():
        for run_dir in sorted(OUTPUT_DIR.iterdir(), reverse=True):
            if not run_dir.is_dir():
                continue
            summary_path = run_dir / "run_summary.json"
            strands_path = run_dir / "strands_result.json"

            files = list(run_dir.glob("*"))
            mp4s = [f for f in files if f.suffix == ".mp4"]
            monitors = [f for f in files if f.name.endswith("_monitor.json")]
            scripts = [f for f in files if f.name.endswith("_script.json")]
            researches = [f for f in files if f.name.endswith("_research.json")]

            total_size = sum(f.stat().st_size for f in mp4s)

            runs.append({
                "run_id": run_dir.name,
                "timestamp": run_dir.name,
                "content": len(monitors),
                "researched": len(researches),
                "scripted": len(scripts),
                "rendered": len(mp4s),
                "video_size_mb": round(total_size / 1024 / 1024, 1),
                "has_video": len(mp4s) > 0,
            })

    return {"runs": runs[:limit]}


@app.get("/api/run/{run_id}")
async def api_run_detail(run_id: str):
    import re
    if not re.match(r"^\d{8}_\d{6}$", run_id):
        return JSONResponse({"error": "invalid run_id format"}, 400)
    run_dir = OUTPUT_DIR / run_id
    if not run_dir.exists():
        return JSONResponse({"error": "not found"}, 404)

    stories = []
    for monitor_file in sorted(run_dir.glob("*_monitor.json")):
        sid = monitor_file.stem.replace("_monitor", "")
        story = {"story_id": sid}

        for suffix in ["_monitor", "_research", "_script"]:
            f = run_dir / f"{sid}{suffix}.json"
            if f.exists():
                with open(f) as fh:
                    story[suffix.replace("_", "")] = json.load(fh)

        video = run_dir / f"{sid}.mp4"
        story["rendered"] = video.exists()
        story["video_size_mb"] = (
            round(video.stat().st_size / 1024 / 1024, 1) if video.exists() else 0
        )
        stories.append(story)

    return {"run_id": run_id, "content": stories}


@app.post("/api/pipeline/start")
async def api_pipeline_start(request: Request):
    if pipeline_state["running"]:
        return JSONResponse({"error": "Pipeline already running"}, 409)

    body = await request.json()
    stories = int(settings["pipeline"].get("videos_per_run", 1))
    skip_publish = bool(settings["pipeline"].get("skip_publish", True))

    pipeline_state.update({
        "running": True,
        "paused": False,
        "run_id": datetime.now().strftime("%Y%m%d_%H%M%S"),
        "current_step": "starting",
        "progress": 0,
        "logs": [],
        "content_count": stories,
        "content_done": 0,
        "start_time": time.time(),
    })
    reset_agent_activity()
    persist_pipeline_state()

    asyncio.create_task(run_pipeline(stories, skip_publish))

    return {"status": "started", "run_id": pipeline_state["run_id"]}


@app.post("/api/pipeline/pause")
async def api_pipeline_pause():
    if not pipeline_state["running"]:
        return JSONResponse({"error": "Pipeline is not running"}, 409)
    pipeline_state["paused"] = True
    pipeline_state["pause_start"] = time.time()
    from colonyv_agent import pipeline_runtime
    pipeline_runtime.set_paused(True)
    proc = pipeline_state.get("current_process")
    if proc is not None and proc.poll() is None:
        try:
            os.killpg(proc.pid, signal.SIGSTOP)
        except ProcessLookupError:
            pass
    log("Pipeline paused. Current work is frozen; click Resume to continue.")
    return {"status": "paused"}


@app.post("/api/pipeline/resume")
async def api_pipeline_resume():
    if not pipeline_state["running"]:
        return JSONResponse({"error": "Pipeline is not running"}, 409)
    pipeline_state["paused"] = False
    if pipeline_state.get("pause_start"):
        pipeline_state["paused_duration"] += (time.time() - pipeline_state["pause_start"])
        pipeline_state["pause_start"] = None
    from colonyv_agent import pipeline_runtime
    pipeline_runtime.set_paused(False)
    proc = pipeline_state.get("current_process")
    if proc is not None and proc.poll() is None:
        try:
            os.killpg(proc.pid, signal.SIGCONT)
        except ProcessLookupError:
            pass
    log("Pipeline resumed.")
    return {"status": "resumed"}


@app.post("/api/pipeline/stop")
async def api_pipeline_stop():
    pipeline_state["paused"] = False
    pipeline_state["running"] = False
    pipeline_state["current_step"] = "stopped"
    from colonyv_agent import pipeline_runtime
    pipeline_runtime.request_stop()
    proc = pipeline_state.get("current_process")
    if proc is not None and proc.poll() is None:
        try:
            os.killpg(proc.pid, signal.SIGCONT)
            os.killpg(proc.pid, signal.SIGTERM)
        except ProcessLookupError:
            proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                proc.kill()
    return {"status": "stopped"}


@app.get("/api/settings")
async def api_settings_get():
    visible = json.loads(json.dumps(settings))
    visible["model"].pop("api_keys", {})
    return visible


@app.post("/api/settings")
async def api_settings_set(request: Request):
    body = await request.json()
    for section in ("pipeline", "content"):
        values = body.get(section)
        if isinstance(values, dict):
            settings[section].update(values)
    model_values = body.get("model")
    if isinstance(model_values, dict):
        settings["model"]["provider"] = "gemini"
        if model_values.get("model_id"):
            settings["model"]["model_id"] = model_values["model_id"]
    scheduler_values = body.get("scheduler")
    if isinstance(scheduler_values, dict):
        settings["scheduler"].update(scheduler_values)
        scheduler_config["enabled"] = bool(scheduler_values.get("enabled", scheduler_config["enabled"]))
        if scheduler_values.get("interval_hours"):
            scheduler_config["interval_hours"] = int(scheduler_values["interval_hours"])
        if scheduler_values.get("videos_per_run"):
            scheduler_config["stories"] = int(scheduler_values["videos_per_run"])
        scheduler_config["next_run"] = (
            datetime.now() + timedelta(hours=scheduler_config["interval_hours"])
        ).isoformat()
    settings["model"].setdefault("api_keys", {}).pop("gemini", None)
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    save_settings()
    return await api_settings_get()


@app.get("/api/models")
async def api_models(provider: str = ""):
    """Return a provider's model catalog, optionally enriched from its API."""
    provider = provider.strip().lower()
    if provider not in MODEL_PROVIDER_CATALOG:
        return JSONResponse({"error": "Unknown provider"}, 400)

    catalog = MODEL_PROVIDER_CATALOG[provider]
    models = list(catalog["models"])
    key = settings["model"].get("api_keys", {}).get(provider, "")
    try:
        import requests
        if provider == "gemini" and key:
            response = requests.get(
                "https://generativelanguage.googleapis.com/v1beta/models",
                params={"key": key}, timeout=10,
            )
            response.raise_for_status()
            discovered = [
                str(item.get("name", "")).removeprefix("models/")
                for item in response.json().get("models", [])
                if item.get("name") and "generateContent" in item.get("supportedGenerationMethods", [])
            ]
            if discovered:
                models = [item if item.startswith("gemini/") else f"gemini/{item}" for item in discovered]
    except Exception as exc:
        return {"provider": provider, "label": catalog["label"], "models": models, "source": "built-in", "warning": str(exc)}

    return {"provider": provider, "label": catalog["label"], "models": sorted(set(models)), "source": "api" if key else "built-in"}


@app.get("/api/analytics")
async def api_analytics():
    runs = []
    if OUTPUT_DIR.exists():
        for run_dir in sorted(OUTPUT_DIR.iterdir()):
            if not run_dir.is_dir():
                continue
            monitors = list(run_dir.glob("*_monitor.json"))
            mp4s = list(run_dir.glob("*.mp4"))
            total_size = sum(f.stat().st_size for f in mp4s)

            topics = []
            for mf in monitors:
                try:
                    with open(mf) as f:
                        d = json.load(f)
                    topics.append(d.get("title", "")[:50])
                except Exception:
                    pass

            runs.append({
                "date": run_dir.name[:8],
                "content": len(monitors),
                "rendered": len(mp4s),
                "size_mb": round(total_size / 1024 / 1024, 1),
                "topics": topics,
            })

    total_content = sum(r["content"] for r in runs)
    total_rendered = sum(r["rendered"] for r in runs)
    total_size = sum(r["size_mb"] for r in runs)

    return {
        "total_runs": len(runs),
        "total_content": total_content,
        "total_rendered": total_rendered,
        "total_size_mb": total_size,
        "runs": runs[-30:],
    }


YOUTUBE_SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.readonly",
    "https://www.googleapis.com/auth/yt-analytics.readonly",
]


def _youtube_data():
    token_path = AGENTS_DIR / "publisher" / "youtube_token.json"
    if not token_path.exists():
        return {
            "connected": False,
            "message": "YouTube not authenticated. Upload client_secret.json and click Connect with Google.",
        }

    try:
        from google.oauth2.credentials import Credentials
        from google.auth.transport.requests import Request
        from googleapiclient.discovery import build

        with open(token_path) as f:
            token_data = json.load(f)

        creds = Credentials.from_authorized_user_info(token_data)

        if not creds.valid:
            if creds.expired and creds.refresh_token:
                creds.refresh(Request())
                with open(token_path, "w") as f:
                    f.write(creds.to_json())
            else:
                return {
                    "connected": False,
                    "message": "OAuth token expired. Please click Connect with Google again.",
                }

        youtube = build("youtube", "v3", credentials=creds)

        # Channel stats
        channel = {}
        stats = {}
        try:
            channel_resp = youtube.channels().list(
                part="statistics,snippet", mine=True
            ).execute()
            channel = channel_resp["items"][0] if channel_resp.get("items") else {}
            stats = channel.get("statistics", {})
        except Exception as ce:
            log(f"Channel stats restricted or unavailable: {ce}")

        # Recent videos
        videos = []
        try:
            videos_resp = youtube.search().list(
                part="snippet", forMine=True, type="video", order="date", maxResults=10
            ).execute()
            for item in videos_resp.get("items", []):
                vid = item["id"].get("videoId", "")
                snippet = item.get("snippet", {})
                if vid:
                    videos.append({
                        "id": vid,
                        "title": snippet.get("title", "Untitled"),
                        "published": snippet.get("publishedAt", "")[:10],
                        "thumbnail": snippet.get("thumbnails", {}).get("default", {}).get("url", ""),
                    })

            # Get stats for each video
            if videos:
                vid_ids = [v["id"] for v in videos if v["id"]]
                if vid_ids:
                    stats_resp = youtube.videos().list(
                        part="statistics", id=",".join(vid_ids)
                    ).execute()
                    for vs in stats_resp.get("items", []):
                        vid_id = vs.get("id")
                        for v in videos:
                            if v["id"] == vid_id:
                                v["views"] = int(vs.get("statistics", {}).get("viewCount", 0))
                                v["likes"] = int(vs.get("statistics", {}).get("likeCount", 0))
                                v["comments"] = int(vs.get("statistics", {}).get("commentCount", 0))
        except Exception as ve:
            log(f"Video stats retrieval warning: {ve}")

        channel_name = channel.get("snippet", {}).get("title") or "Authenticated Channel"
        return {
            "connected": True,
            "setup": {"status": "connected", "label": "YouTube account connected"},
            "channel": {
                "name": channel_name,
                "subscribers": int(stats.get("subscriberCount", 0)),
                "total_views": int(stats.get("viewCount", 0)),
                "total_videos": int(stats.get("videoCount", 0)),
            },
            "videos": videos,
        }

    except Exception as e:
        err_str = str(e)
        if "insufficient" in err_str.lower() or "403" in err_str:
            return {
                "connected": False,
                "setup": {"status": "needs_reauthorization", "label": "Reconnect YouTube account"},
                "message": "YouTube token missing read permissions. Please go to Setup & Settings and click 'Connect with Google' to grant channel reading permissions.",
            }
        return {"connected": False, "setup": {"status": "error", "label": "YouTube connection needs attention"}, "error": str(e)}


@app.get("/api/youtube")
async def api_youtube():
    try:
        return await asyncio.wait_for(asyncio.to_thread(_youtube_data), timeout=25)
    except asyncio.TimeoutError:
        return {
            "connected": False,
            "setup": {"status": "timeout", "label": "YouTube took too long to respond"},
            "error": "YouTube request timed out. The rest of ColonyV is still available.",
        }


@app.post("/api/youtube/upload-secret")
async def api_youtube_upload_secret(request: Request):
    """Upload client_secret.json for YouTube OAuth."""
    body = await request.json()
    secret_data = body.get("client_secret")
    if not secret_data:
        return JSONResponse({"error": "No client_secret provided"}, 400)

    secret_path = AGENTS_DIR / "publisher" / "client_secret.json"
    try:
        parsed = json.loads(secret_data) if isinstance(secret_data, str) else secret_data
        with open(secret_path, "w") as f:
            json.dump(parsed, f, indent=2)
        return {"status": "ok", "message": "client_secret.json saved"}
    except json.JSONDecodeError:
        return JSONResponse({"error": "Invalid JSON"}, 400)


@app.post("/api/youtube/auth")
async def api_youtube_auth():
    """Trigger YouTube OAuth flow (returns auth URL)."""
    secret_path = AGENTS_DIR / "publisher" / "client_secret.json"
    if not secret_path.exists():
        return JSONResponse({"error": "No client_secret.json found. Upload it first."}, 400)

    # Remove old token with outdated scopes if present
    token_path = AGENTS_DIR / "publisher" / "youtube_token.json"
    if token_path.exists():
        token_path.unlink()

    try:
        from google_auth_oauthlib.flow import InstalledAppFlow

        flow = InstalledAppFlow.from_client_secrets_file(str(secret_path), YOUTUBE_SCOPES)
        flow.redirect_uri = "http://localhost:8000/api/youtube/callback"

        auth_url, state = flow.authorization_url(
            access_type="offline",
            prompt="consent",
            include_granted_scopes="true",
        )

        app.state.oauth_flow = flow
        app.state.oauth_state = state

        return {"auth_url": auth_url, "state": state}

    except Exception as e:
        return JSONResponse({"error": str(e)}, 400)


@app.get("/api/youtube/callback")
async def api_youtube_callback(code: str = None, state: str = None):
    """OAuth callback from Google."""
    if not code:
        return HTMLResponse("<h1>Auth failed - no code received</h1>")

    try:
        from google_auth_oauthlib.flow import InstalledAppFlow

        secret_path = AGENTS_DIR / "publisher" / "client_secret.json"
        flow = getattr(app.state, "oauth_flow", None)

        if not flow:
            if not secret_path.exists():
                return HTMLResponse("<h1>Auth session expired and client_secret.json is missing.</h1>")
            flow = InstalledAppFlow.from_client_secrets_file(str(secret_path), YOUTUBE_SCOPES)
            flow.redirect_uri = "http://localhost:8000/api/youtube/callback"

        flow.fetch_token(code=code)
        creds = flow.credentials

        token_path = AGENTS_DIR / "publisher" / "youtube_token.json"
        token_path.parent.mkdir(parents=True, exist_ok=True)
        with open(token_path, "w") as f:
            f.write(creds.to_json())

        return HTMLResponse("""
            <!DOCTYPE html>
            <html>
            <head>
                <title>YouTube Authorized</title>
                <style>
                    body { background: #07090e; color: #ffffff; font-family: -apple-system, BlinkMacSystemFont, sans-serif; display: flex; align-items: center; justify-content: center; height: 100vh; margin: 0; text-align: center; }
                    .card { background: #0f172a; padding: 40px; border-radius: 20px; border: 1px solid rgba(255,255,255,0.1); box-shadow: 0 20px 40px rgba(0,0,0,0.5); }
                    h1 { color: #34c759; margin-bottom: 12px; font-size: 24px; }
                    p { color: #94a3b8; font-size: 14px; margin-bottom: 0; }
                </style>
            </head>
            <body>
                <div class="card">
                    <h1>YouTube Connected Successfully!</h1>
                    <p>Closing window and updating dashboard...</p>
                </div>
                <script>
                    if (window.opener) {
                        try { window.opener.postMessage('youtube_auth_complete', '*'); } catch(e){}
                    }
                    setTimeout(() => window.close(), 1500);
                </script>
            </body>
            </html>
        """)

    except Exception as e:
        return HTMLResponse(f"<h1>Auth error: {e}</h1>")


@app.delete("/api/youtube/disconnect")
async def api_youtube_disconnect():
    """Remove YouTube token."""
    token_path = AGENTS_DIR / "publisher" / "youtube_token.json"
    if token_path.exists():
        token_path.unlink()
    return {"status": "disconnected"}


@app.websocket("/ws/logs")
async def ws_logs(websocket: WebSocket):
    await websocket.accept()
    log_subscribers.append(websocket)
    try:
        # Send recent logs
        for entry in pipeline_state["logs"][-50:]:
            await websocket.send_text(entry)
        # Keep connection open for live updates
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        if websocket in log_subscribers:
            log_subscribers.remove(websocket)


# --- Pipeline runner ---

def _terminate_process(proc: subprocess.Popen) -> tuple[str, str]:
    proc.terminate()
    try:
        stdout, stderr = proc.communicate(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
        stdout, stderr = proc.communicate()
    return stdout or "", stderr or ""


def run_cancellable_subprocess(
    cmd: list[str],
    *,
    cwd: str | None = None,
    env: dict | None = None,
    timeout: int = 300,
    step_label: str = "",
) -> subprocess.CompletedProcess:
    label = step_label or " ".join(str(x).split("/")[-1] for x in cmd[:2])
    log(f"[{label}] starting: {' '.join(str(x) for x in cmd)}")

    final_env = dict(env or os.environ)
    pythonpath = final_env.get("PYTHONPATH", "")
    paths = [p for p in pythonpath.split(":") if p] + [str(PROJECT_ROOT)]
    final_env["PYTHONPATH"] = ":".join(dict.fromkeys(paths))

    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        cwd=cwd,
        env=final_env,
        start_new_session=True,
    )
    pipeline_state["current_process"] = proc
    start = time.time()
    paused_at = None
    paused_seconds = 0.0
    stdout_lines = []
    try:
        import selectors
        sel = selectors.DefaultSelector()
        if proc.stdout:
            sel.register(proc.stdout, selectors.EVENT_READ)

        while True:
            if not pipeline_state["running"]:
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                except ProcessLookupError:
                    proc.kill()
                stdout_text = "\n".join(stdout_lines)
                return subprocess.CompletedProcess(cmd, -15, stdout_text, "")

            if pipeline_state["paused"]:
                if paused_at is None:
                    paused_at = time.time()
                time.sleep(0.25)
                continue
            if paused_at is not None:
                paused_seconds += time.time() - paused_at
                paused_at = None

            elapsed = time.time() - start - paused_seconds
            if elapsed > timeout:
                log(f"[{label}] TIMEOUT after {timeout}s of active work; terminating")
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                except ProcessLookupError:
                    proc.kill()
                proc.wait()
                stdout_text = "\n".join(stdout_lines)
                return subprocess.CompletedProcess(cmd, -9, stdout_text, "")

            events = sel.select(timeout=0.5)
            for key, _ in events:
                line = key.fileobj.readline()
                if line:
                    stripped = line.strip()
                    if stripped:
                        log(f"[{label}] {stripped}")
                        stdout_lines.append(stripped)
                else:
                    # EOF — process closed its stdout
                    pass

            ret = proc.poll()
            if ret is not None:
                # Drain remaining output
                if proc.stdout:
                    for line in proc.stdout:
                        stripped = line.strip()
                        if stripped:
                            log(f"[{label}] {stripped}")
                            stdout_lines.append(stripped)
                sel.close()
                stdout_text = "\n".join(stdout_lines)
                elapsed = round(time.time() - start, 1)
                log(f"[{label}] exited with code {ret} ({elapsed}s)")
                return subprocess.CompletedProcess(cmd, ret, stdout_text, "")

    finally:
        sel.close()
        pipeline_state["current_process"] = None


async def run_pipeline(stories: int, skip_publish: bool):
    try:
        log(f"Pipeline started: {stories} stories")

        output_dir = OUTPUT_DIR / pipeline_state["run_id"]
        output_dir.mkdir(parents=True, exist_ok=True)

        # Step 1: Monitor
        pipeline_state["current_step"] = "monitor"
        pipeline_state["progress"] = 10
        set_agent_activity("monitor", "active", "Scanning RSS feeds and ranking candidates")
        log("Step 1/5: Scanning RSS feeds...")

        py_exec = get_python_exec()
        provider = "gemini"
        model_env = {
            **os.environ,
            "COLONY_MODEL_ID": settings["model"].get("model_id", "gemini/gemini-3.5-flash"),
            "COLONYV_GEMINI_MODEL": settings["model"].get("model_id", "gemini/gemini-3.5-flash").removeprefix("gemini/"),
            "COLONY_MAX_DURATION_SECONDS": str(settings["pipeline"].get("max_duration_seconds", 60)),
            "COLONY_TOPIC_PROMPT": settings["content"].get("active_topic", ""),
        }
        if os.environ.get("GOOGLE_CLOUD_PROJECT"):
            model_env["GOOGLE_GENAI_USE_VERTEXAI"] = "true"
        model_env.pop("GOOGLE_API_KEY", None)
        model_env.pop("GEMINI_API_KEY", None)
        result = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: run_cancellable_subprocess(
                [py_exec, str(AGENTS_DIR / "monitor" / "monitor.py"), "--top", str(stories * 3)],
                cwd=str(AGENTS_DIR), timeout=300,
                env=model_env,
                step_label="monitor",
            ),
        )

        if not pipeline_state["running"]:
            log("Pipeline stopped by user")
            return

        stories_list = parse_json_from_output(result.stdout, "array")
        if not stories_list:
            set_agent_activity("monitor", "failed", "No valid stories were returned")
            err = (result.stderr or result.stdout or "")[-400:]
            if err:
                log(f"Monitor output: {err}")
            log("No stories found")
            return

        stories_list = stories_list[:stories]
        set_agent_activity("monitor", "complete", f"Selected {len(stories_list)} stories for production")
        log(f"Found {len(stories_list)} stories")
        pipeline_state["progress"] = 20

        # Process each story
        for i, story in enumerate(stories_list):
            if not pipeline_state["running"]:
                log("Pipeline stopped by user")
                break

            story_id = story.get("story_id", f"story_{i}")
            log(f"Story {i+1}/{len(stories_list)}: {story.get('title', '')[:50]}")

            # Save monitor data
            with open(output_dir / f"{story_id}_monitor.json", "w") as f:
                json.dump(story, f, indent=2)

            # Step 2: Research
            pipeline_state["current_step"] = f"research ({i+1}/{len(stories_list)})"
            pipeline_state["progress"] = 30 + (i * 15)
            set_agent_activity("research", "active", f"Collecting evidence for story {i + 1}/{len(stories_list)}")
            log("  Researching...")

            py_exec = get_python_exec()
            result = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: run_cancellable_subprocess(
                    [py_exec, str(AGENTS_DIR / "research" / "research.py"),
                     "--story-json", str(output_dir / f"{story_id}_monitor.json")],
                    cwd=str(AGENTS_DIR), timeout=300,
                    env=model_env,
                    step_label=f"research-{story_id[:8]}",
                ),
            )

            if not pipeline_state["running"]:
                log("Pipeline stopped by user")
                break

            research = parse_json_from_output(result.stdout, "object")
            if not research:
                set_agent_activity("research", "failed", "Research output could not be parsed")
                log(f"  Research failed (returncode={result.returncode}), skipping")
                log(f"  Last output: {result.stdout[-200:] if result.stdout else 'empty'}")
                continue

            # Check for rate limit errors in response
            if "error" in research:
                err_msg = str(research.get("error", {}).get("message", ""))
                if "rate" in err_msg.lower() or "limit" in err_msg.lower():
                    log(f"  Research rate-limited, retrying in 30s...")
                    await asyncio.sleep(30)
                    result2 = await asyncio.get_event_loop().run_in_executor(
                        None,
                        lambda: run_cancellable_subprocess(
                            [py_exec, str(AGENTS_DIR / "research" / "research.py"),
                             "--story-json", str(output_dir / f"{story_id}_monitor.json")],
                            cwd=str(AGENTS_DIR), timeout=300,
                            env=model_env,
                            step_label=f"research-{story_id[:8]}-retry",
                        ),
                    )
                    research = parse_json_from_output(result2.stdout, "object")
                    if not research or "error" in research:
                        set_agent_activity("research", "failed", "Research retry failed")
                        log(f"  Research failed after retry, skipping")
                        continue
                else:
                    log(f"  Research error: {err_msg[:100]}, skipping")
                    set_agent_activity("research", "failed", err_msg[:120] or "Research returned an error")
                    continue

            research["story_id"] = story_id

            with open(output_dir / f"{story_id}_research.json", "w") as f:
                json.dump(research, f, indent=2)
            log(f"  Research: {len(research.get('claims', []))} claims")
            set_agent_activity("research", "complete", f"Collected {len(research.get('claims', []))} claims")

            # Step 3: Script
            pipeline_state["current_step"] = f"script ({i+1}/{len(stories_list)})"
            pipeline_state["progress"] = 50 + (i * 10)
            set_agent_activity("script", "active", f"Writing story {i + 1}/{len(stories_list)}")
            log("  Writing script...")

            with open(output_dir / f"{story_id}_research.json", "w") as f:
                json.dump(research, f, indent=2)

            py_exec = get_python_exec()
            result = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: run_cancellable_subprocess(
                    [py_exec, str(AGENTS_DIR / "scriptwriter" / "scriptwriter.py"),
                     "--research-json", str(output_dir / f"{story_id}_research.json")],
                    cwd=str(AGENTS_DIR), timeout=300,
                    env=model_env,
                    step_label=f"script-{story_id[:8]}",
                ),
            )

            if not pipeline_state["running"]:
                log("Pipeline stopped by user")
                break

            script = parse_json_from_output(result.stdout, "object")
            if not script:
                set_agent_activity("script", "failed", "Script output could not be parsed")
                log(f"  Script failed (returncode={result.returncode}), skipping")
                log(f"  Last output: {result.stdout[-200:] if result.stdout else 'empty'}")
                continue

            # Check for rate limit errors in response
            if "error" in script:
                err_msg = str(script.get("error", {}).get("message", ""))
                if "rate" in err_msg.lower() or "limit" in err_msg.lower():
                    log(f"  Script rate-limited, retrying in 30s...")
                    await asyncio.sleep(30)
                    result2 = await asyncio.get_event_loop().run_in_executor(
                        None,
                        lambda: run_cancellable_subprocess(
                            [py_exec, str(AGENTS_DIR / "scriptwriter" / "scriptwriter.py"),
                             "--research-json", str(output_dir / f"{story_id}_research.json")],
                            cwd=str(AGENTS_DIR), timeout=300,
                            env=model_env,
                            step_label=f"script-{story_id[:8]}-retry",
                        ),
                    )
                    script = parse_json_from_output(result2.stdout, "object")
                    if not script or "error" in script:
                        set_agent_activity("script", "failed", "Script retry failed")
                        log(f"  Script failed after retry, skipping")
                        continue
                else:
                    log(f"  Script error: {err_msg[:100]}, skipping")
                    set_agent_activity("script", "failed", err_msg[:120] or "Script returned an error")
                    continue

            script["story_id"] = story_id

            with open(output_dir / f"{story_id}_script.json", "w") as f:
                json.dump(script, f, indent=2)
            log(f"  Script: {len(script.get('suggested_visual_beats', []))} beats, {script.get('estimated_duration', 0)}s")
            set_agent_activity("script", "complete", f"Created {len(script.get('suggested_visual_beats', []))} visual beats")

            # Step 4: Producer
            pipeline_state["current_step"] = f"render ({i+1}/{len(stories_list)})"
            pipeline_state["progress"] = 70 + (i * 10)
            set_agent_activity("render", "active", f"Rendering video for story {i + 1}/{len(stories_list)}")
            log("  Rendering video...")

            py_exec = get_python_exec()
            result = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: run_cancellable_subprocess(
                    [py_exec, str(PROJECT_ROOT / "producer" / "build_video.py"),
                     str(output_dir / f"{story_id}_script.json"),
                     "--output", str(output_dir / f"{story_id}.mp4")],
                    cwd=str(PROJECT_ROOT), timeout=1800,
                    env=model_env,
                    step_label=f"render-{story_id[:8]}",
                ),
            )

            if not pipeline_state["running"]:
                log("Pipeline stopped by user")
                break

            video_path = output_dir / f"{story_id}.mp4"
            if video_path.exists():
                size_mb = round(video_path.stat().st_size / 1024 / 1024, 1)
                log(f"  Rendered: {video_path.name} ({size_mb} MB)")
                set_agent_activity("render", "complete", f"Rendered {size_mb} MB MP4")
            else:
                log(f"  Render failed (returncode={result.returncode})")
                log(f"  Last output: {result.stdout[-300:] if result.stdout else 'empty'}")
                set_agent_activity("render", "failed", f"Render failed with code {result.returncode}")

            # Step 5: Publisher
            if not skip_publish and video_path.exists():
                pipeline_state["current_step"] = f"publish ({i+1}/{len(stories_list)})"
                pipeline_state["progress"] = 90
                set_agent_activity("publish", "active", f"Publishing story {i + 1}/{len(stories_list)} to YouTube")
                log("  Publishing to YouTube...")

                py_exec = get_python_exec()
                cmd = [
                    py_exec, str(AGENTS_DIR / "publisher" / "youtube.py"),
                    "upload", str(video_path),
                    "--title", script.get("hook", "AI News")[:100],
                    "--description", script.get("body", "")[:5000],
                    "--tags", "ai,tech,news",
                    "--privacy", "public",
                ]


                result = await asyncio.get_event_loop().run_in_executor(
                    None,
                    lambda: run_cancellable_subprocess(
                        cmd, cwd=str(AGENTS_DIR), timeout=120,
                        step_label=f"publish-{story_id[:8]}",
                    ),
                )
                if not pipeline_state["running"]:
                    log("Pipeline stopped by user")
                    break
                if result.returncode == 0:
                    log("  Published!")
                    set_agent_activity("publish", "complete", "Published publicly to YouTube")
                else:
                    log(f"  Publish failed (returncode={result.returncode})")
                    log(f"  Last output: {result.stdout[-200:] if result.stdout else 'empty'}")
                    set_agent_activity("publish", "failed", "YouTube publishing failed")

            pipeline_state["content_done"] = i + 1

        if not pipeline_state["running"]:
            log("Pipeline stopped by user")
            pipeline_state["current_step"] = "stopped"
        else:
            pipeline_state["progress"] = 100
            pipeline_state["current_step"] = "complete"
            log(f"Pipeline complete: {pipeline_state['content_done']}/{len(stories_list)} stories")

            # Send notification
            if notification_config.get("on_complete"):
                await send_notification(f"Pipeline complete: {pipeline_state['content_done']}/{len(stories_list)} pieces of content rendered")

            # Track cost (rough estimate: 3 LLM calls per story — monitor scoring, research, script)
            llm_calls = len(stories_list) * 3
            cost_path = PROJECT_ROOT / "output" / "cost_log.json"
            cost_data = {"total_llm_calls": 0, "estimated_cost_usd": 0, "runs": []}
            if cost_path.exists():
                try:
                    with open(cost_path) as f:
                        cost_data = json.load(f)
                except Exception:
                    pass
            cost_data["total_llm_calls"] += llm_calls
            cost_data["estimated_cost_usd"] += llm_calls * 0.001  # rough Groq estimate
            cost_data["runs"].append({
                "run_id": pipeline_state["run_id"],
                "llm_calls": llm_calls,
                "cost_usd": llm_calls * 0.001,
                "timestamp": datetime.now().isoformat(),
            })
            with open(cost_path, "w") as f:
                json.dump(cost_data, f, indent=2)

            # Run analyst for learning loop
            try:
                set_agent_activity("analyst", "active", "Analyzing completed run and learning signals")
                py_exec = get_python_exec()
                analyst_result = await asyncio.get_event_loop().run_in_executor(
                    None,
                    lambda: run_cancellable_subprocess(
                        [py_exec, str(AGENTS_DIR / "analyst" / "analyst.py"),
                         "--run-dir", str(output_dir)],
                        cwd=str(AGENTS_DIR), timeout=120,
                        env=model_env,
                        step_label="analyst",
                    ),
                )
                if analyst_result.returncode == 0:
                    analyst_path = output_dir / "analyst_output.json"
                    if analyst_path.exists():
                        log("Analyst: learned signals saved")
                        set_agent_activity("analyst", "complete", "Saved learned signals")
            except Exception as e:
                log(f"Analyst skipped: {e}")
                set_agent_activity("analyst", "failed", "Analyst could not complete")

    except Exception as e:
        log(f"Pipeline error: {e}")
        if notification_config.get("on_error"):
            await send_notification(f"Pipeline error: {e}")
    finally:
        pipeline_state["running"] = False
        pipeline_state["start_time"] = None


def parse_json_from_output(output: str, expect: str = "object"):
    # Find the "=== Top" header first (monitor) or last JSON block
    marker_char = "[" if expect == "array" else "{"
    end_char = "]" if expect == "array" else "}"

    # Strategy 1: Find "=== Top" header, parse JSON after it
    header_idx = output.rfind("=== Top")
    if header_idx != -1:
        try:
            start = output.index(marker_char, header_idx)
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
                    return json.loads(output[start:start + i + 1])
        except (ValueError, json.JSONDecodeError):
            pass

    # Strategy 2: Try all candidate start positions
    # For arrays: last to first (monitor outputs array LAST)
    # For objects: first to last (outer object wraps inner ones)
    candidates = []
    for i in range(len(output)):
        if output[i] == marker_char:
            candidates.append(i)

    if expect == "array":
        candidates = reversed(candidates)

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
                    return json.loads(output[start:start + i + 1])
        except (ValueError, json.JSONDecodeError):
            continue

    return None


# --- Scheduler ---

scheduler_config = {
    "enabled": True,
    "interval_hours": settings["scheduler"].get("interval_hours", 6),
    "stories": settings["scheduler"].get("videos_per_run", settings["pipeline"].get("videos_per_run", 1)),

    "last_run": None,
    "next_run": None,
}
scheduler_config["next_run"] = (datetime.now() + timedelta(hours=scheduler_config["interval_hours"])).isoformat()


@app.get("/api/scheduler")
async def api_scheduler_get():
    return scheduler_config


@app.post("/api/scheduler")
async def api_scheduler_set(request: Request):
    body = await request.json()
    scheduler_config.update({
        "enabled": True,
        "interval_hours": body.get("interval_hours", 6),
        "stories": body.get("stories", settings["pipeline"].get("videos_per_run", 1)),
    })
    scheduler_config["next_run"] = (
        datetime.now() + timedelta(hours=scheduler_config["interval_hours"])
    ).isoformat()
    settings["scheduler"].update({
        "enabled": True,
        "interval_hours": scheduler_config["interval_hours"],
        "videos_per_run": scheduler_config["stories"],
    })
    save_settings()
    return scheduler_config


# --- Notifications ---

notification_config = {
    "slack_webhook": settings["notifications"].get("slack_webhook") or os.environ.get("SLACK_WEBHOOK_URL", ""),
    "email_to": settings["notifications"].get("email_to") or os.environ.get("NOTIFY_EMAIL", ""),
    "on_complete": settings["notifications"].get("on_complete", True),
    "on_error": settings["notifications"].get("on_error", True),
}


@app.get("/api/notifications")
async def api_notifications_get():
    return {
        "slack_webhook": notification_config["slack_webhook"] or "",
        "email_to": notification_config["email_to"] or "",
        "slack_configured": bool(notification_config["slack_webhook"]),
        "email_configured": bool(notification_config["email_to"]),
        "on_complete": notification_config["on_complete"],
        "on_error": notification_config["on_error"],
    }


@app.post("/api/notifications")
async def api_notifications_set(request: Request):
    body = await request.json() or {}
    # Never silently wipe a configured endpoint: empty values keep the
    # previously saved value unless an explicit "clear_webhook"/"clear_email"
    # flag is provided.
    for key in ("slack_webhook", "email_to"):
        value = body.get(key)
        if value:
            notification_config[key] = str(value).strip()
    for key in ("on_complete", "on_error"):
        if key in body:
            notification_config[key] = bool(body[key])
    if body.get("clear_webhook"):
        notification_config["slack_webhook"] = ""
    if body.get("clear_email"):
        notification_config["email_to"] = ""
    settings["notifications"].update({
        key: notification_config[key]
        for key in ("slack_webhook", "email_to", "on_complete", "on_error")
        if key in notification_config
    })
    save_settings()
    return {"status": "ok"}


@app.post("/api/notifications/test")
async def api_notifications_test():
    sent = []
    if notification_config["slack_webhook"]:
        try:
            import requests
            resp = requests.post(
                notification_config["slack_webhook"],
                json={"text": "Content Ops Dashboard: Test notification"},
                timeout=10,
            )
            sent.append("slack")
        except Exception as e:
            return {"error": f"Slack failed: {e}"}

    if notification_config["email_to"]:
        sent.append("email (configured but not sent in test)")

    return {"sent": sent}


async def send_notification(message: str):
    if notification_config["slack_webhook"]:
        try:
            import requests
            requests.post(
                notification_config["slack_webhook"],
                json={"text": f"Content Ops: {message}"},
                timeout=10,
            )
        except Exception:
            pass


# --- Feedback Loop ---

@app.get("/api/feedback")
async def api_feedback():
    """Get performance feedback from YouTube metrics."""
    feedback_path = PROJECT_ROOT / "output" / "feedback_signals.json"
    if feedback_path.exists():
        with open(feedback_path) as f:
            return json.load(f)
    return {"signals": [], "last_updated": None}


@app.post("/api/feedback/generate")
async def api_feedback_generate():
    """Generate feedback signals from YouTube metrics + past runs."""
    try:
        # Load past analyst outputs
        signals = []
        for run_dir in sorted(OUTPUT_DIR.iterdir()):
            if not run_dir.is_dir():
                continue
            analyst_file = run_dir / "analyst_output.json"
            if analyst_file.exists():
                with open(analyst_file) as f:
                    data = json.load(f)
                signals.extend(data.get("learned_signals", []))

        feedback = {
            "signals": signals[-20:],
            "last_updated": datetime.now().isoformat(),
            "total_signals": len(signals),
        }

        feedback_path = PROJECT_ROOT / "output" / "feedback_signals.json"
        with open(feedback_path, "w") as f:
            json.dump(feedback, f, indent=2)

        return feedback
    except Exception as e:
        return {"error": str(e)}


# --- Cost tracking ---

cost_log = {"total_llm_calls": 0, "estimated_cost_usd": 0, "runs": []}

@app.get("/api/costs")
async def api_costs():
    cost_path = PROJECT_ROOT / "output" / "cost_log.json"
    if cost_path.exists():
        with open(cost_path) as f:
            return json.load(f)
    return cost_log


# --- RSS Feeds config ---

FEEDS_PATH = PROJECT_ROOT / "agents" / "monitor" / "feeds.json"

DEFAULT_FEEDS = [
    {"url": "https://techcrunch.com/category/artificial-intelligence/feed/", "category": "ai"},
    {"url": "https://www.theverge.com/rss/ai-artificial-intelligence/index.xml", "category": "ai"},
    {"url": "https://feeds.arstechnica.com/arstechnica/technology-lab", "category": "tech"},
    {"url": "https://www.wired.com/feed/rss", "category": "tech"},
    {"url": "https://cointelegraph.com/rss", "category": "crypto"},
    {"url": "https://www.coindesk.com/arc/outboundfeeds/rss/", "category": "crypto"},
    {"url": "https://hnrss.org/best?q=AI+OR+LLM+OR+GPT+OR+crypto+OR+blockchain&count=15", "category": "tech"},
]


async def _scheduled_launch() -> None:
    if pipeline_state["running"]:
        return
    stories = int(
        scheduler_config.get("stories")
        or settings["pipeline"].get("videos_per_run", 1)
    )
    log(f"[scheduler] automated run triggered (every ~{scheduler_config.get('interval_hours', 6)}h)")
    await launch_production_run(stories, source="scheduler")


@app.on_event("startup")
async def start_scheduler():
    global app_loop, CLOUD_STATE
    app_loop = asyncio.get_running_loop()
    if os.environ.get("GOOGLE_CLOUD_PROJECT"):
        try:
            CLOUD_STATE = get_cloud_state()
            print("[cloud-state] Firestore run persistence enabled", flush=True)
        except Exception as exc:
            print(f"[cloud-state] Firestore unavailable: {exc}", flush=True)
    loop = app_loop

    def _loop():
        while True:
            try:
                if scheduler_config.get("enabled") and not pipeline_state.get("running"):
                    nxt = scheduler_config.get("next_run")
                    if nxt:
                        due = datetime.fromisoformat(nxt)
                        if datetime.now() >= due:
                            interval_hours = scheduler_config.get("interval_hours") or 6
                            scheduler_config["next_run"] = (
                                datetime.now() + timedelta(hours=interval_hours)
                            ).isoformat()
                            settings["scheduler"].update(
                                {"enabled": True, "interval_hours": interval_hours}
                            )
                            try:
                                save_settings()
                            except Exception:
                                pass
                            try:
                                asyncio.run_coroutine_threadsafe(_scheduled_launch(), loop)
                            except RuntimeError:
                                pass
            except Exception:
                pass
            time.sleep(20)

    threading.Thread(target=_loop, daemon=True).start()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
