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
import hashlib
import hmac
import json
import os
import random
import secrets
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
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
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


def _materialize_youtube_credentials():
    """Write YouTube client_secret.json / youtube_token.json from env vars.

    On Cloud Run the credential files are dockerignored and injected via
    COLONYV_YOUTUBE_TOKEN / COLONYV_YOUTUBE_CLIENT_SECRET. The dashboard reads
    the files directly (not the env), so materialize them here so the
    YouTube panel and publisher agree on one source of truth.
    """
    pub_dir = AGENTS_DIR / "publisher"
    pub_dir.mkdir(parents=True, exist_ok=True)
    token_json = os.environ.get("COLONYV_YOUTUBE_TOKEN")
    if token_json and not (pub_dir / "youtube_token.json").exists():
        try:
            json.loads(token_json)
            (pub_dir / "youtube_token.json").write_text(token_json)
        except ValueError:
            pass
    client_json = os.environ.get("COLONYV_YOUTUBE_CLIENT_SECRET")
    if client_json and not (pub_dir / "client_secret.json").exists():
        try:
            json.loads(client_json)
            (pub_dir / "client_secret.json").write_text(client_json)
        except ValueError:
            pass

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
        "selected_topics": ["AI & Machine Learning", "Cryptocurrency", "Big Tech & Startups", "Hardware & GPUs"],
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

_materialize_youtube_credentials()


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
    tmp = SETTINGS_PATH.with_suffix(".json.tmp")
    with open(tmp, "w") as f:
        json.dump(settings, f, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, SETTINGS_PATH)


def pick_run_topic() -> str:
    """Pick the focus topic for one production run.

    The dashboard's Topic Focus panel lets the operator arm any number of
    categories (selected_topics). Each cycle a run draws one of the armed
    topics uniformly at random, so successive runs drift across the enabled
    categories instead of reporting the same niche every time. Falls back to
    the legacy active_topic, then to the first custom topic, so a saved
    selection is never an empty string.
    """
    content = settings.get("content", {})
    pool = [t for t in content.get("selected_topics", []) if isinstance(t, str) and t.strip()]
    if not pool:
        legacy = content.get("active_topic") or ""
        if legacy.strip():
            pool = [legacy]
        else:
            first = next(
                (t for t in content.get("custom_topics", []) if isinstance(t, str) and t.strip()), ""
            )
            if first:
                pool = [first]
    return pool[random.choice(range(len(pool)))] if pool else ""

app = FastAPI(title="COLONY — Autonomous Media Orchestrator")
app.mount("/static", StaticFiles(directory=str(DASHBOARD_DIR / "static")), name="static")
templates = Jinja2Templates(directory=str(DASHBOARD_DIR / "templates"))

# --- Dashboard auth / login ------------------------------------------------
# Personal access: only the owner logs in. Auth activates only when both
# ADMIN_USERNAME and ADMIN_PASSWORD are set in the environment, so local
# development stays frictionless while deployed instances can be locked down.
#
# The password is never stored or logged; a salted PBKDF2 hash is derived at
# startup and verified with a constant-time compare. Login is rate-limited:
# 10 failed attempts per client IP lock that IP out for 15 minutes.

AUTH_USERNAME = os.environ.get("ADMIN_USERNAME", "").strip()
AUTH_PASSWORD_HASH: str | None = None
if AUTH_USERNAME and os.environ.get("ADMIN_PASSWORD"):
    salt = secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac("sha256", os.environ["ADMIN_PASSWORD"].encode(), salt.encode(), 120_000)
    AUTH_PASSWORD_HASH = f"pbkdf2_sha256$120000${salt}${dk.hex()}"
AUTH_ENABLED = AUTH_USERNAME != "" and AUTH_PASSWORD_HASH is not None

SESSION_COOKIE = "colonyv_session"
SESSION_TTL_SECONDS = 24 * 3600
LOGIN_ATTEMPTS: dict[str, tuple[int, float]] = {}  # ip -> (fails, lockout_until)
MAX_LOGIN_ATTEMPTS = 10
LOCKOUT_SECONDS = 900
# Stateless signed session cookie: every Cloud Run instance (and every restart)
# validates the same token without shared memory. Set an identical
# SESSION_SECRET in each environment; a random per-process key is used as a
# fallback for local dev.
SESSION_KEY: bytes = (os.environ.get("SESSION_SECRET") or secrets.token_hex(32)).encode()

PUBLIC_PATHS = {
    "/healthz",
    "/icon_logo.png",
    "/favicon.ico",
    "/login",
    "/api/login",
    "/api/logout",
    "/api/pubsub/run-stage",  # self-protected with its own bearer token
    "/api/youtube/callback",  # oauth redirect leg from Google
}


def _auth_check_password(password: str) -> bool:
    if not AUTH_PASSWORD_HASH:
        return False
    scheme, iterations, salt, hex_digest = AUTH_PASSWORD_HASH.split("$")
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), int(iterations))
    return hmac.compare_digest(dk.hex(), hex_digest)


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",")[0].strip() or request.client.host
    return request.client.host if request.client else "unknown"


def _login_allowed(ip: str) -> tuple[bool, int]:
    fails, until = LOGIN_ATTEMPTS.get(ip, (0, 0))
    if until and time.time() < until:
        return False, int(until - time.time())
    return True, 0


def _session_token(username: str) -> str:
    expires = int(time.time()) + SESSION_TTL_SECONDS
    payload = f"{username}|{expires}"
    sig = hmac.new(SESSION_KEY, payload.encode(), hashlib.sha256).hexdigest()[:32]
    return f"{payload}|{sig}"


def _cookie_valid(value: str | None) -> bool:
    if not value:
        return False
    parts = value.split("|")
    if len(parts) != 3:
        return False
    payload, sig = f"{parts[0]}|{parts[1]}", parts[2]
    expect = hmac.new(SESSION_KEY, payload.encode(), hashlib.sha256).hexdigest()[:32]
    if not hmac.compare_digest(sig, expect):
        return False
    try:
        return int(parts[1]) > int(time.time())
    except ValueError:
        return False


LOGIN_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>COLONY — Sign in</title>
  <style>
    * { box-sizing: border-box; }
    body { margin: 0; min-height: 100vh; display: flex; align-items: center; justify-content: center;
           background: #f5f5f7; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
           color: #1d1d1f; -webkit-font-smoothing: antialiased; }
    .card { width: 340px; background: #ffffff; border: 1px solid rgba(0,0,0,0.08); border-radius: 16px;
            padding: 36px 32px; box-shadow: 0 12px 40px rgba(0,0,0,0.1); }
    .logo { font-size: 22px; font-weight: 600; letter-spacing: 4px; color: #1d1d1f; margin-bottom: 4px; }
    .sub { color: #6e6e73; font-size: 13px; margin-bottom: 28px; }
    label { display: block; font-size: 13px; font-weight: 500; color: #6e6e73; margin: 14px 0 6px; }
    input { width: 100%; background: #ffffff; border: 1px solid rgba(0,0,0,0.08); color: #1d1d1f;
            border-radius: 10px; padding: 12px 14px; font-size: 14px; outline: none; box-shadow: 0 2px 8px rgba(0,0,0,0.04); }
    input:focus { border-color: #0071e3; box-shadow: 0 0 0 3px rgba(0,113,227,0.2); }
    .btn-wrap { margin-top: 24px; }
    button { width: 100%; margin-top: 24px; background: #0071e3; color: #ffffff; font-weight: 500; border: none;
             border-radius: 10px; padding: 13px; font-size: 14px; cursor: pointer; }
    button:hover { background: #0077ed; }
    button:disabled { background: #7ab8f0; cursor: wait; }
    .msg { display: none; margin-top: 16px; font-size: 13px; border-radius: 10px; padding: 10px 12px;
           background: #fff2f0; border: 1px solid rgba(255,59,48,0.3); color: #ff3b30; }
    .msg.show { display: block; }
  </style>
</head>
<body>
  <div class="card">
    <div class="logo">COLONY</div>
    <div class="sub">Autonomous Media Orchestrator</div>
    <label for="username">Username</label>
    <input id="username" autocomplete="username" autofocus>
    <label for="password">Password</label>
    <input id="password" type="password" autocomplete="current-password">
    <button id="signin" onclick="doLogin()">Sign in</button>
    <div id="msg" class="msg"></div>
  </div>
  <script>
    async function doLogin() {
      const btn = document.getElementById('signin');
      const msg = document.getElementById('msg');
      btn.disabled = true; msg.className = 'msg';
      try {
        const r = await fetch('/api/login', { method: 'POST', headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({ username: document.getElementById('username').value.trim(),
                                 password: document.getElementById('password').value }) });
        const data = await r.json();
        if (r.ok && data.ok) { location.href = '/'; return; }
        msg.textContent = (data && data.error) ? data.error : ('Login failed (' + r.status + ')');
        msg.className = 'msg show';
      } catch (e) {
        msg.textContent = 'Network error: ' + e.message; msg.className = 'msg show';
      }
      btn.disabled = false; document.getElementById('password').value = '';
    }
    document.getElementById('password').addEventListener('keydown', e => { if (e.key === 'Enter') doLogin(); });
  </script>
</body>
</html>"""


@app.middleware("http")
async def _auth_http_middleware(request: Request, call_next):
    if not AUTH_ENABLED:
        return await call_next(request)
    path = request.url.path
    if path.startswith("/static/") or path in PUBLIC_PATHS:
        return await call_next(request)
    if _cookie_valid(request.cookies.get(SESSION_COOKIE)):
        return await call_next(request)
    if path.startswith("/api/"):
        return JSONResponse({"error": "Unauthorized. Please log in."}, status_code=401)
    return RedirectResponse("/login", status_code=303)


@app.get("/login", response_class=HTMLResponse)
async def login_page():
    return HTMLResponse(LOGIN_HTML)


@app.post("/api/login")
async def api_login(request: Request):
    if not AUTH_ENABLED:
        return JSONResponse({"error": "Authentication is not configured."}, 403)
    ip = _client_ip(request)
    allowed, remaining = _login_allowed(ip)
    if not allowed:
        return JSONResponse(
            {"error": f"Too many failed attempts. Try again in {max(1, remaining // 60)} min."},
            429,
        )
    try:
        body = await request.json()
    except Exception:
        body = {}
    username = str(body.get("username", "")).strip()
    password = str(body.get("password", ""))
    if username == AUTH_USERNAME and _auth_check_password(password):
        LOGIN_ATTEMPTS.pop(ip, None)
        token = _session_token(username)
        resp = JSONResponse({"ok": True})
        resp.set_cookie(
            SESSION_COOKIE,
            token,
            max_age=SESSION_TTL_SECONDS,
            path="/",
            httponly=True,
            samesite="lax",
            secure=(request.url.scheme == "https"),
        )
        return resp
    fails, until = LOGIN_ATTEMPTS.get(ip, (0, 0))
    fails += 1
    if fails >= MAX_LOGIN_ATTEMPTS:
        LOGIN_ATTEMPTS[ip] = (0, time.time() + LOCKOUT_SECONDS)
        return JSONResponse(
            {"error": f"Too many failed attempts. Locked out for {LOCKOUT_SECONDS // 60} minutes."},
            429,
        )
    LOGIN_ATTEMPTS[ip] = (fails, until)
    return JSONResponse(
        {"error": f"Invalid credentials. {MAX_LOGIN_ATTEMPTS - fails} attempts remaining."}, 401)


@app.post("/api/logout")
async def api_logout():
    resp = JSONResponse({"ok": True})
    resp.delete_cookie(SESSION_COOKIE, path="/")
    return resp


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
    # Set when a cycle finishes. The dashboard uses it to hold the completed
    # (green) state briefly, then return the cards to their waiting state.
    "last_completed_at": None,
}

# The six stages that actually produce a video. These are what the Agent
# Workspace shows.
#
# The Analyst is deliberately absent. It is not a production stage — it observes
# published videos after the fact and feeds learned signals back into Discovery
# and Scriptwriter. Showing it as a seventh card implied the run was still working
# when it had already finished, so it now runs in the background and surfaces
# through the content performance analytics instead.
AGENT_DEFINITIONS = [
    ("monitor", "Discovery Agent", "Find and rank the most valuable stories"),
    ("research", "Research Agent", "Gather evidence and test claims"),
    ("script", "Scriptwriter Agent", "Shape evidence into a concise story"),
    ("direct", "Art Director", "Author the palette, shot list, and illustration briefs"),
    ("render", "Visual Producer", "Illustrate, compose, and render the motion graphics"),
    ("publish", "Publisher Agent", "Deliver the finished video to YouTube"),
]

# Stages that run but are not shown as workspace cards.
BACKGROUND_STAGES = {"analyst"}


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
    # Background stages (the Analyst) intentionally have no workspace card, so
    # their updates are dropped rather than creating a phantom agent.
    if key in BACKGROUND_STAGES or key not in pipeline_state["agent_activity"]:
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

# A finished run holds its green board briefly so the operator sees the completed
# cycle, then the cards return to waiting. Leaving every card green forever
# implies the system is permanently "done". This has to happen server-side: the
# client-side timer alone could never win, because the next 2s poll repainted the
# still-"complete" server state straight back to green.
BOARD_COOLDOWN_SECONDS = float(os.environ.get("COLONYV_BOARD_COOLDOWN", "6"))
_board_cooldown_task: "asyncio.Task | None" = None


async def cool_down_agent_board(delay: float | None = None) -> None:
    """Return the workspace cards to waiting once a finished run has settled.

    Skipped if another run started during the hold, so a quick re-run never has
    its fresh board wiped by the previous cycle's cooldown.
    """
    await asyncio.sleep(BOARD_COOLDOWN_SECONDS if delay is None else delay)
    if pipeline_state.get("running"):
        return
    reset_agent_activity()
    pipeline_state["progress"] = 0
    persist_pipeline_state(force=True)


def schedule_board_cooldown() -> None:
    global _board_cooldown_task
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return
    if _board_cooldown_task is not None and not _board_cooldown_task.done():
        _board_cooldown_task.cancel()
    # Held in a module global: asyncio keeps only a weak reference to tasks, so a
    # bare create_task() can be garbage collected before it ever fires.
    _board_cooldown_task = asyncio.create_task(cool_down_agent_board())


log_subscribers: list[WebSocket] = []

# Serialises run starts so a double-click (or scheduler + click) cannot launch
# two production runs, and so a new run never revives a stopping one.
_RUN_START_LOCK = asyncio.Lock()
_production_task: "asyncio.Task | None" = None
_legacy_task: "asyncio.Task | None" = None
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
        "last_completed_at": pipeline_state.get("last_completed_at"),
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


async def launch_production_run(stories: int, *, source: str = "manual") -> dict[str, Any]:
    """Start a full autonomous production run through the ADK Production Director."""
    global _production_task
    skip_publish = False

    # Starting a run is serialised. Two things went wrong without this lock:
    #   * the old `if pipeline_state["running"]` check in the route ran before an
    #     `await`, so a double-click started several concurrent runs, each
    #     rendering and uploading its own video;
    #   * Stop only raises a flag that the factory observes at its next
    #     checkpoint, and configure() resets that flag, so starting a new run
    #     while the previous one was still mid-step revived it and published
    #     twice. We wait for the previous task to actually exit first.
    async with _RUN_START_LOCK:
        if pipeline_state["running"]:
            return {"error": "Pipeline already running", "status": "rejected"}

        previous = _production_task
        if previous is not None and not previous.done():
            done, _pending = await asyncio.wait({previous}, timeout=15)
            if not done:
                return {
                    "error": "The previous run is still stopping. Try again in a moment.",
                    "status": "rejected",
                }

        return await _begin_production_run(stories, source=source, skip_publish=skip_publish)


async def _begin_production_run(stories: int, *, source: str, skip_publish: bool) -> dict[str, Any]:
    global _production_task

    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_id = f"{run_id}_{uuid.uuid4().hex[:4]}"
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

    if scheduler_config.get("enabled"):
        hours = scheduler_config.get("interval_hours") or 6
        scheduler_config["next_run"] = (datetime.now() + timedelta(hours=hours)).isoformat()
        if source != "scheduler":
            log(f"Schedule armed: next run in {hours}h (or when this run completes).")

    model_id = settings["model"].get("model_id", "gemini/gemini-3.5-flash")
    topic = pick_run_topic()
    pipeline_state["run_topic"] = topic
    log(f"Focus topic for this run: {topic}")
    model_env = {
        **os.environ,
        "COLONY_MODEL_ID": model_id,
        "COLONYV_GEMINI_MODEL": model_id.removeprefix("gemini/"),
        "COLONY_MAX_DURATION_SECONDS": str(settings["pipeline"].get("max_duration_seconds", 60)),
        "COLONY_TOPIC_PROMPT": topic,
    }
    if os.environ.get("GOOGLE_CLOUD_PROJECT"):
        model_env["GOOGLE_GENAI_USE_VERTEXAI"] = "true"
    model_env.pop("GOOGLE_API_KEY", None)
    model_env.pop("GEMINI_API_KEY", None)

    from colonyv_agent import pipeline_runtime

    pipeline_runtime.configure(
        logger=log,
        activity=set_agent_activity,
        reset=reset_agent_activity,
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

    _production_task = asyncio.create_task(run_production_director(stories))

    return {"status": "started", "mode": "adk-production", "run_id": run_id}


@app.post("/api/agent/run")
async def api_agent_run(request: Request):
    """Start a full autonomous production run through the ADK Production Director."""
    global app_loop
    app_loop = asyncio.get_running_loop()

    try:
        body = await request.json()
    except Exception:
        body = {}
    stories = int((body and body.get("stories")) or settings["pipeline"].get("videos_per_run", 1))

    result = await launch_production_run(stories, source="manual")
    if result.get("error"):
        return JSONResponse(result, 409)
    return JSONResponse(result)


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
            if notification_config.get("on_error"):
                await send_notification(f"ADK production failed: {result['error']}", level="error")
        else:
            produced = result.get("stories_produced", [])
            log(f"ADK production completed with {len(produced)} finished story(ies).")
            pipeline_state["last_completed_run"] = {
                "ts": datetime.now().isoformat(),
                "stories": len(produced),
                "topic": pipeline_state.get("run_topic", ""),
            }
            if notification_config.get("on_complete"):
                await send_notification(
                    f"ADK production complete: {len(produced)} story(ies) rendered",
                    level="success",
                )
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
            await send_notification(f"ADK production error: {e}", level="error")
    finally:
        pipeline_state["running"] = False
        pipeline_state["start_time"] = None
        pipeline_state["last_completed_at"] = datetime.now().isoformat()
        persist_pipeline_state(force=True)
        _persist_run_summary()
        schedule_board_cooldown()

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
            reset=reset_agent_activity,
            env=dict(os.environ),
            out_dir=OUTPUT_DIR,
            run=run_id,
            skip=False,
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

    if stage == "publish" and result.get("decision") == "complete":
        from colonyv_agent import pipeline_runtime
        pipeline_runtime.reset_activity()
        pipeline_runtime.activity("monitor", "complete", "Discovery complete")

    project_id = settings.get("cloud", {}).get("project_id") or os.environ.get("GOOGLE_CLOUD_PROJECT", "")
    from cloud import pubsub as ps

    if result.get("next"):
        ps.publish_next(project_id, run_id, result)
    else:
        pipeline_state["progress"] = 100
        pipeline_state["current_step"] = "complete"
        pipeline_state["running"] = False
        pipeline_state["start_time"] = None
        pipeline_state["last_completed_at"] = datetime.now().isoformat()
        log(f"[async] run {run_id} completed ({result.get('decision')})")
        schedule_board_cooldown()
        pipeline_state["run_id"] = run_id
        _persist_run_summary()
        try:
            await asyncio.to_thread(snapshot_performance, True)
        except Exception as exc:
            log(f"[performance] post-run snapshot failed: {exc}")
    persist_pipeline_state(force=True)


def runtime_state_run_id(run_id: str) -> str:
    from colonyv_agent import pipeline_runtime as pr

    return pr.run_id or run_id


@app.post("/api/pubsub/run-stage")
async def api_pubsub_run_stage(request: Request):
    """Pub/Sub push webhook: executes one pipeline stage message.

    Authorization: when COLONYV_PUBSUB_TOKEN is set, the request must carry it
    as a bearer token (matching the push subscription's auth token). Without a
    configured token the endpoint refuses requests when running in a deployed
    (non-local) environment to avoid unauthenticated pipeline execution.
    """
    expected = os.environ.get("COLONYV_PUBSUB_TOKEN", "")
    if expected:
        auth = request.headers.get("Authorization", "")
        provided = auth[7:].strip() if auth.lower().startswith("bearer ") else auth
        if provided != expected:
            return JSONResponse({"error": "unauthorized"}, 401)
    elif os.environ.get("K_SERVICE"):  # deployed Cloud Run without a token
        return JSONResponse({"error": "webhook auth not configured"}, 503)
    try:
        payload = await request.json()
        message = payload.get("message", {})
        attrs = message.get("attributes", {})
        run_id = attrs.get("run_id", "")
        stage = attrs.get("stage", "")
        story_index = int(attrs.get("story_index", 0))
        attempt = int(attrs.get("attempt", 1))
        if not run_id or stage not in {"monitor", "research", "script", "direct", "render", "publish", "analyst"}:
            return JSONResponse({"error": "invalid message"}, 400)
        asyncio.create_task(handle_stage_message(run_id, stage, story_index, attempt))
        return JSONResponse({"ok": True, "ack": True})
    except Exception as e:
        log(f"[pubsub] handler error: {e}")
        return JSONResponse({"error": str(e)}, 500)


def _summarize_local_dir(run_dir: Path) -> dict | None:
    """Read one run folder into the shape the Runs table and Analytics need."""
    if not run_dir.is_dir():
        return None
    files = list(run_dir.glob("*"))
    mp4s = [f for f in files if f.suffix == ".mp4"]
    monitors = [f for f in files if f.name.endswith("_monitor.json")]
    scripts = [f for f in files if f.name.endswith("_script.json")]
    researches = [f for f in files if f.name.endswith("_research.json")]

    total_size = sum(f.stat().st_size for f in mp4s)
    topics = []
    for mf in monitors:
        try:
            with open(mf) as f:
                topics.append(json.load(f).get("title", "")[:50])
        except Exception:
            pass

    return {
        "run_id": run_dir.name,
        "timestamp": run_dir.name,
        "date": run_dir.name[:8],
        "content": len(monitors) or 1,
        "researched": len(researches),
        "scripted": len(scripts),
        "rendered": len(mp4s),
        "video_size_mb": round(total_size / 1024 / 1024, 1),
        "has_video": len(mp4s) > 0,
        "topics": topics,
    }


def _build_run_summary() -> dict | None:
    """Durable record of the finished/stopped run, saved to Firestore so the
    dashboard's history and charts survive instance recycles. When the run
    folder is already gone (mid-cycle recycles) it falls back to state fields."""
    run_id = pipeline_state.get("run_id")
    if not run_id:
        return None
    summary = _summarize_local_dir(OUTPUT_DIR / run_id)
    if summary is None:
        summary = {
            "run_id": run_id,
            "timestamp": run_id,
            "date": run_id[:8],
            "content": pipeline_state.get("content_count") or 1,
            "researched": 0,
            "scripted": 0,
            "rendered": 1 if pipeline_state.get("current_step") == "complete" else 0,
            "video_size_mb": 0.0,
            "has_video": pipeline_state.get("current_step") == "complete",
            "topics": [],
        }
    story_state = pipeline_state.get("stage_state") or {}
    topic = pipeline_state.get("run_topic") or story_state.get("topic") or ""
    summary.setdefault("topic", topic)
    if not summary.get("topics") and topic:
        summary["topics"] = [str(topic)[:50]]
    summary["status"] = pipeline_state.get("current_step", "unknown")
    summary["video_id"] = str(story_state.get("video_id") or pipeline_state.get("video_id") or "")
    return summary


def _persist_run_summary() -> None:
    if not CLOUD_STATE:
        # Even without Firestore we should try to back up run artifacts; the
        # two go together but one failing must not block the other.
        _backup_run_folder()
        return
    run_id = pipeline_state.get("run_id")
    summary = _build_run_summary()
    if not run_id or not summary:
        return
    try:
        CLOUD_STATE.save_run_summary(run_id, summary)
    except Exception as exc:
        print(f"[cloud-state] run summary persistence failed: {exc}", flush=True)
    _backup_run_folder()


def _backup_run_folder() -> None:
    """Upload the finished run's MP4(s) and story JSONs to GCS (best-effort)."""
    run_id = pipeline_state.get("run_id")
    run_dir = OUTPUT_DIR / run_id if run_id else None
    if not run_id or not run_dir or not run_dir.exists():
        return
    try:
        from colonyv_agent import artifacts
        result = artifacts.backup_run_artifacts(run_id, run_dir)
        if result.get("error"):
            log(f"[artifacts] backup note: {result['error']}")
        elif result.get("uploaded"):
            log(f"[artifacts] backed up {result['uploaded']} file(s) for {run_id}")
    except Exception as exc:
        log(f"[artifacts] backup failed: {exc}")


def _firestore_runs() -> list[dict]:
    if not CLOUD_STATE:
        return []
    try:
        return CLOUD_STATE.list_run_summaries() or []
    except Exception as exc:
        print(f"[cloud-state] reading run summaries failed: {exc}", flush=True)
        return []


def _backfilled_cloud_runs() -> list[dict]:
    """Runs that predate summaries, inferred from their saved pipeline state."""
    if not CLOUD_STATE:
        return []
    try:
        states = CLOUD_STATE.list_run_states()
    except Exception as exc:
        print(f"[cloud-state] reading run states failed: {exc}", flush=True)
        return []
    return [
        {
            "run_id": s.get("run_id") or "",
            "timestamp": s.get("run_id") or "",
            "date": (s.get("run_id") or "00000000")[:8],
            "content": s.get("content_count") or 1,
            "researched": 0,
            "scripted": 0,
            "rendered": 1 if (s.get("current_step") or "").lower() == "complete" else 0,
            "video_size_mb": 0.0,
            "has_video": (s.get("current_step") or "").lower() == "complete",
            "status": s.get("current_step", "unknown"),
            "topic": s.get("run_topic") or "",
        }
        for s in states
        if s.get("run_id")
    ]


@app.get("/api/runs")
async def api_runs(limit: int = 20):
    by_id: dict[str, dict] = {}
    for run_dir in sorted(OUTPUT_DIR.iterdir(), reverse=True) if OUTPUT_DIR.exists() else []:
        summary = _summarize_local_dir(run_dir)
        if summary:
            by_id[summary["run_id"]] = summary
    for summary in _firestore_runs() + _backfilled_cloud_runs():
        by_id.setdefault(summary["run_id"], summary)
    runs = sorted(by_id.values(), key=lambda r: r["run_id"], reverse=True)
    return {"runs": runs[:limit]}


@app.get("/api/run/{run_id}")
async def api_run_detail(run_id: str):
    import re
    # Allow the timestamp run id format and the legacy "agent-<timestamp>" dirs.
    if not re.match(r"^[\w.-]+$", run_id) or ".." in run_id:
        return JSONResponse({"error": "invalid run_id"}, 400)
    run_dir = OUTPUT_DIR / run_id
    if not run_dir.is_dir():
        # The instance was recycled (ephemeral disk) — pull the run's files back
        # from the durable GCS backup so the row is still clickable.
        from colonyv_agent import artifacts

        fetched = artifacts.download_run_artifacts(run_id, run_dir)
        if not fetched.get("local") and not fetched.get("remote_available"):
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

    # Nothing on disk nor in storage for this run: treat as unavailable.
    if not run_dir.exists() or not any(run_dir.glob("*")):
        return JSONResponse({"error": "not found"}, 404)

    return {"run_id": run_id, "content": stories}


@app.post("/api/pipeline/start")
async def api_pipeline_start(request: Request):
    global _legacy_task
    try:
        body = await request.json()
    except Exception:
        body = {}
    stories = int(settings["pipeline"].get("videos_per_run", 1))
    # Dashboard always sends skip_publish:false; publishing is an invariant.
    # Never trust a stray truthy string from settings ("true" == True bug).
    skip_publish = False
    if isinstance(body, dict) and "skip_publish" in body:
        skip_publish = bool(body.get("skip_publish")) and body.get("skip_publish") not in (False, 0)

    # Same serialisation as the ADK path: check and claim under one lock, after
    # every await, so concurrent posts cannot both start a run.
    async with _RUN_START_LOCK:
        if pipeline_state["running"]:
            return JSONResponse({"error": "Pipeline already running"}, 409)

        previous = _legacy_task
        if previous is not None and not previous.done():
            done, _pending = await asyncio.wait({previous}, timeout=15)
            if not done:
                return JSONResponse(
                    {"error": "The previous run is still stopping. Try again in a moment."}, 409)

        pipeline_state.update({
            "running": True,
            "paused": False,
            "run_id": f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:4]}",
            "current_step": "starting",
            "progress": 0,
            "logs": [],
            "content_count": stories,
            "content_done": 0,
            "start_time": time.time(),
            "paused_duration": 0.0,
            "pause_start": None,
        })
        reset_agent_activity()
        persist_pipeline_state()

        _legacy_task = asyncio.create_task(run_pipeline(stories, skip_publish))

    return {"status": "started", "run_id": pipeline_state["run_id"]}


@app.post("/api/pipeline/pause")
async def api_pipeline_pause():
    if not pipeline_state["running"]:
        return JSONResponse({"error": "Pipeline is not running"}, 409)
    pipeline_state["paused"] = True
    pipeline_state["pause_start"] = time.time()
    # Deliberately do NOT reset agent activity here: pause freezes the board in
    # its current state (active stays active, completed stays completed) so
    # resume continues exactly where it left off. Resetting would grey every
    # card and lost completed stages would never get their status back.
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
    scheduler_config["next_run"] = None
    log("Pipeline stopped. Schedule disarmed; click Run to arm it again.")
    # A stopped run returns the board to waiting on the same delay as a finished
    # one, so a terminated cycle does not sit frozen mid-stage forever.
    schedule_board_cooldown()
    _persist_run_summary()
    from colonyv_agent import pipeline_runtime
    pipeline_runtime.request_stop()
    proc = pipeline_state.get("current_process")
    if proc is not None and proc.poll() is None:
        loop = asyncio.get_running_loop()

        def _teardown():
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

        await loop.run_in_executor(None, _teardown)
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
    content = settings.get("content", {})
    custom_topics = content.get("custom_topics") or []
    selected = [t for t in content.get("selected_topics", []) if isinstance(t, str) and t.strip()]
    if not selected:
        selected = [t for t in content.get("active_topic", "").split(",") if t.strip()]
    settings["content"]["selected_topics"] = selected
    settings["content"]["active_topic"] = selected[0] if selected else (custom_topics[0] if custom_topics else "")
    model_values = body.get("model")
    if isinstance(model_values, dict):
        settings["model"]["provider"] = "gemini"
        if model_values.get("model_id"):
            settings["model"]["model_id"] = model_values["model_id"]
    scheduler_values = body.get("scheduler")
    if isinstance(scheduler_values, dict):
        settings["scheduler"].update(scheduler_values)
        scheduler_config["enabled"] = bool(scheduler_values.get("enabled", scheduler_config["enabled"]))
        if "interval_hours" in scheduler_values and scheduler_values.get("interval_hours") is not None:
            scheduler_config["interval_hours"] = float(scheduler_values["interval_hours"])
        if scheduler_values.get("videos_per_run"):
            scheduler_config["stories"] = int(scheduler_values["videos_per_run"])
        if scheduler_config.get("next_run"):
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
            loop = asyncio.get_running_loop()
            response = await loop.run_in_executor(
                None,
                lambda: requests.get(
                    "https://generativelanguage.googleapis.com/v1beta/models",
                    params={"key": key}, timeout=10,
                ),
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


_yt_video_count_cache: dict = {"ts": 0.0, "count": 0}


def _published_video_count() -> int:
    """Live count of videos on the YouTube channel — the durable truth of what
    runs have published, instead of guessing from ephemeral run records."""
    if time.time() - _yt_video_count_cache["ts"] < 120:
        return _yt_video_count_cache["count"]
    count = 0
    try:
        data = _youtube_data()
        count = int((data.get("channel") or {}).get("total_videos") or 0)
    except Exception as exc:
        print(f"[analytics] youtube count failed: {exc}", flush=True)
    _yt_video_count_cache.update(ts=time.time(), count=count)
    return count


@app.get("/api/analytics")
async def api_analytics():
    runs = []
    if OUTPUT_DIR.exists():
        for run_dir in sorted(OUTPUT_DIR.iterdir()):
            if not run_dir.is_dir():
                continue
            monitor_titles = []
            monitors = list(run_dir.glob("*_monitor.json"))
            mp4s = list(run_dir.glob("*.mp4"))
            total_size = sum(f.stat().st_size for f in mp4s)
            for mf in monitors:
                try:
                    with open(mf) as f:
                        monitor_titles.append(json.load(f).get("title", "")[:50])
                except Exception:
                    pass
            runs.append({
                "date": run_dir.name[:8],
                "content": len(monitors) or 1,
                "rendered": len(mp4s),
                "size_mb": round(total_size / 1024 / 1024, 1),
                "topics": monitor_titles,
            })

    # Merge cloud summaries (and inferred history) so the charts hold their
    # full history even on a fresh instance after a redeploy. Local folders win
    # where both exist; the local run's own counts are the most accurate.
    cloud = _firestore_runs() + _backfilled_cloud_runs()
    by_id = {r["run_id"]: r for r in runs}
    for r in cloud:
        if r["run_id"] in by_id:
            continue
        by_id[r["run_id"]] = r
    merged = sorted(by_id.values(), key=lambda r: r["run_id"])
    runs = [
        {
            "date": r["date"],
            "content": r.get("content") or 1,
            "rendered": r.get("rendered") or 0,
            "size_mb": r.get("video_size_mb", r.get("size_mb", 0)) or 0,
            "topics": r.get("topics") or ([r["topic"]] if r.get("topic") else []),
        }
        for r in merged
    ]

    total_content = sum(r["content"] for r in runs)
    total_rendered = _published_video_count()
    if not total_rendered:
        total_rendered = sum(r["rendered"] for r in runs)
    total_size = sum(r["size_mb"] for r in runs)

    return {
        "total_runs": len(runs),
        "total_content": total_content,
        "total_rendered": total_rendered,
        "total_size_mb": total_size,
        "runs": runs[-30:],
    }


# ---------------------------------------------------------------------------
# Content performance history
#
# The YouTube API only reports a video's *current* cumulative view count, so
# "views over time" cannot be queried — it has to be accumulated. A background
# snapshot appends the current counts periodically, and the series is derived by
# differencing consecutive snapshots.
#
# This is what the Analyst works from. The Analyst no longer appears as a card in
# the Agent Workspace, because it is not a stage in producing a video; it observes
# what happened after publication and feeds the result back into Discovery and
# Scriptwriter prompts.
# ---------------------------------------------------------------------------

PERFORMANCE_LOG = OUTPUT_DIR / "performance_history.json"
# One snapshot per hour is plenty of resolution for a view-count curve, and keeps
# the file small enough to read synchronously on request.
SNAPSHOT_MIN_INTERVAL_SECONDS = 3300
MAX_SNAPSHOTS = 1500


def _load_performance_history() -> list[dict]:
    local: list[dict] = []
    if PERFORMANCE_LOG.exists():
        try:
            with open(PERFORMANCE_LOG) as f:
                data = json.load(f)
            local = data.get("snapshots", []) if isinstance(data, dict) else data
            if not isinstance(local, list):
                local = []
        except (OSError, json.JSONDecodeError):
            local = []
    if local or not CLOUD_STATE:
        return local
    # Fresh instance after a redeploy: the ephemeral performance log is gone,
    # but Firestore keeps the accumulated snapshots, so the charts still render.
    try:
        return CLOUD_STATE.load_performance_snapshots()
    except Exception as exc:
        print(f"[cloud-state] reading performance snapshots failed: {exc}", flush=True)
        return []


def _save_performance_history(snapshots: list[dict]) -> None:
    try:
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        tmp = PERFORMANCE_LOG.with_suffix(".tmp")
        with open(tmp, "w") as f:
            json.dump({"snapshots": snapshots[-MAX_SNAPSHOTS:]}, f, indent=2)
        tmp.replace(PERFORMANCE_LOG)
    except OSError as exc:
        log(f"[performance] could not persist history: {exc}")
    if CLOUD_STATE:
        try:
            CLOUD_STATE.save_performance_snapshots(snapshots)
        except Exception as exc:
            print(f"[cloud-state] persisting performance snapshots failed: {exc}", flush=True)


def snapshot_performance(force: bool = False) -> dict:
    """Record the current view counts for every published video.

    Rate-limited so a burst of dashboard traffic cannot spam the YouTube API or
    fill the history with near-identical points. Never raises: a failed snapshot
    must not affect a run.
    """
    snapshots = _load_performance_history()
    now = datetime.now()

    if snapshots and not force:
        try:
            last = datetime.fromisoformat(snapshots[-1]["at"])
            if (now - last).total_seconds() < SNAPSHOT_MIN_INTERVAL_SECONDS:
                return {"recorded": False, "reason": "too soon", "snapshots": len(snapshots)}
        except (ValueError, KeyError):
            pass

    try:
        data = _youtube_data()
    except Exception as exc:
        log(f"[performance] snapshot skipped: {exc}")
        return {"recorded": False, "reason": str(exc), "snapshots": len(snapshots)}

    if not data.get("connected"):
        return {
            "recorded": False,
            "reason": "YouTube not connected",
            "snapshots": len(snapshots),
        }

    videos = [
        {
            "id": v.get("id", ""),
            "title": v.get("title", "Untitled"),
            "published": v.get("published", ""),
            "thumbnail": v.get("thumbnail", ""),
            "views": int(v.get("views", 0) or 0),
            "likes": int(v.get("likes", 0) or 0),
            "comments": int(v.get("comments", 0) or 0),
        }
        for v in data.get("videos", [])
        if v.get("id")
    ]
    if not videos:
        return {"recorded": False, "reason": "no videos", "snapshots": len(snapshots)}

    snapshots.append({
        "at": now.isoformat(timespec="seconds"),
        "subscribers": int(data.get("channel", {}).get("subscribers", 0) or 0),
        "videos": videos,
    })
    _save_performance_history(snapshots)
    log(f"[performance] snapshot recorded for {len(videos)} video(s)")
    return {"recorded": True, "videos": len(videos), "snapshots": len(snapshots)}


def _performance_payload() -> dict:
    """Shape the history into everything the analytics chart needs."""
    snapshots = _load_performance_history()
    if not snapshots:
        return {
            "ready": False,
            "reason": "no_data",
            "snapshots": 0,
            "series": [],
            "top": [],
            "weekly": [],
            "totals": {"views": 0, "likes": 0, "videos": 0},
        }

    latest = snapshots[-1]
    latest_by_id = {v["id"]: v for v in latest.get("videos", [])}

    # Leaderboard: what actually performed.
    top = sorted(latest_by_id.values(), key=lambda v: v.get("views", 0), reverse=True)

    # Views over time, for the strongest few videos. More than five lines on one
    # chart stops being readable.
    tracked = [v["id"] for v in top[:5]]
    series = []
    for vid in tracked:
        points = []
        for snap in snapshots:
            for v in snap.get("videos", []):
                if v.get("id") == vid:
                    points.append({"at": snap["at"], "views": int(v.get("views", 0) or 0)})
                    break
        if points:
            series.append({
                "id": vid,
                "title": latest_by_id[vid].get("title", "Untitled"),
                "points": points,
            })

    # Views *gained* per ISO week, which is what "is my content improving"
    # actually asks. Cumulative totals always rise and so answer nothing.
    weekly: dict[str, int] = {}
    previous_totals: dict[str, int] = {}
    for snap in snapshots:
        try:
            week = datetime.fromisoformat(snap["at"]).strftime("%G-W%V")
        except (ValueError, KeyError):
            continue
        for v in snap.get("videos", []):
            vid = v.get("id")
            if not vid:
                continue
            current = int(v.get("views", 0) or 0)
            gained = max(0, current - previous_totals.get(vid, current))
            previous_totals[vid] = current
            weekly[week] = weekly.get(week, 0) + gained

    weekly_series = [{"week": w, "views_gained": n} for w, n in sorted(weekly.items())]

    return {
        # A single snapshot draws a flat line, which reads as broken. The UI shows
        # a "collecting" state until there is something to plot.
        "ready": len(snapshots) >= 2,
        "reason": "collecting" if len(snapshots) < 2 else "",
        "snapshots": len(snapshots),
        "first_snapshot": snapshots[0].get("at", ""),
        "last_snapshot": latest.get("at", ""),
        "subscribers": latest.get("subscribers", 0),
        "series": series,
        "top": top[:10],
        "weekly": weekly_series[-12:],
        "totals": {
            "views": sum(v.get("views", 0) for v in latest_by_id.values()),
            "likes": sum(v.get("likes", 0) for v in latest_by_id.values()),
            "videos": len(latest_by_id),
        },
    }


@app.get("/api/performance")
async def api_performance():
    return _performance_payload()


@app.post("/api/performance/snapshot")
async def api_performance_snapshot():
    """Force a snapshot. Used by the dashboard's refresh control."""
    return await asyncio.to_thread(snapshot_performance, True)


YOUTUBE_SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.readonly",
    "https://www.googleapis.com/auth/yt-analytics.readonly",
]


def _youtube_data():
    _materialize_youtube_credentials()
    token_path = AGENTS_DIR / "publisher" / "youtube_token.json"
    has_credentials = (AGENTS_DIR / "publisher" / "client_secret.json").exists()
    if not token_path.exists():
        return {
            "connected": False,
            "has_credentials": has_credentials,
            "message": (
                "Credentials saved. Click Connect with Google to authorise the channel."
                if has_credentials
                else "Paste your client_secret.json below, then connect with Google."
            ),
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
    except json.JSONDecodeError:
        return JSONResponse(
            {"error": "That is not valid JSON. Paste the whole contents of client_secret.json."},
            400,
        )

    # Validate the shape before saving. Previously any JSON was accepted, so a
    # wrong-but-parseable paste only failed later, during the OAuth redirect,
    # where the error was much harder to understand.
    if not isinstance(parsed, dict) or not ({"installed", "web"} & set(parsed)):
        return JSONResponse(
            {"error": "This does not look like an OAuth client file. It should contain an "
                      "\"installed\" or \"web\" section."},
            400,
        )
    section = parsed.get("installed") or parsed.get("web") or {}
    missing = [k for k in ("client_id", "client_secret") if not section.get(k)]
    if missing:
        return JSONResponse(
            {"error": f"OAuth client file is missing: {', '.join(missing)}."}, 400
        )

    try:
        with open(secret_path, "w") as f:
            json.dump(parsed, f, indent=2)
    except OSError as exc:
        return JSONResponse({"error": f"Could not save credentials: {exc}"}, 500)

    return {"status": "ok", "message": "Credentials saved", "has_credentials": True}


def _youtube_redirect_uri(request: Request):
    """Public callback URL for this deployment.

    On Cloud Run the app sees the request via the proxy, so scheme + host come
    from the forwarded headers rather than the loopback the container receives.
    Locally it resolves to http://localhost:<port>/api/youtube/callback.
    """
    scheme = request.headers.get("x-forwarded-proto") or request.url.scheme
    host = request.headers.get("host") or request.url.netloc
    return f"{scheme}://{host}/api/youtube/callback"


@app.post("/api/youtube/auth")
async def api_youtube_auth(request: Request):
    """Trigger YouTube OAuth flow (returns auth URL)."""
    secret_path = AGENTS_DIR / "publisher" / "client_secret.json"
    if not secret_path.exists():
        return JSONResponse({"error": "No client_secret.json found. Upload it first."}, 400)

    # Keep any existing token until re-auth completes, so an aborted or
    # failed flow never leaves the service without working credentials.
    token_path = AGENTS_DIR / "publisher" / "youtube_token.json"

    try:
        from google_auth_oauthlib.flow import InstalledAppFlow

        flow = InstalledAppFlow.from_client_secrets_file(str(secret_path), YOUTUBE_SCOPES)
        flow.redirect_uri = _youtube_redirect_uri(request)

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
async def api_youtube_callback(request: Request, code: str = None, state: str = None):
    """OAuth callback from Google."""
    if not code:
        return HTMLResponse("<h1>Auth failed - no code received</h1>")

    if state and app.state.oauth_state and state != app.state.oauth_state:
        return HTMLResponse("<h1>Auth failed - state mismatch. Please try again.</h1>")

    try:
        from google_auth_oauthlib.flow import InstalledAppFlow

        secret_path = AGENTS_DIR / "publisher" / "client_secret.json"
        flow = getattr(app.state, "oauth_flow", None)

        if not flow:
            if not secret_path.exists():
                return HTMLResponse("<h1>Auth session expired and client_secret.json is missing.</h1>")
            flow = InstalledAppFlow.from_client_secrets_file(str(secret_path), YOUTUBE_SCOPES)
            flow.redirect_uri = _youtube_redirect_uri(request)

        flow.fetch_token(code=code)
        creds = flow.credentials

        token_path = AGENTS_DIR / "publisher" / "youtube_token.json"
        token_path.parent.mkdir(parents=True, exist_ok=True)
        with open(token_path, "w") as f:
            f.write(creds.to_json())

        app.state.oauth_flow = None
        app.state.oauth_state = None

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
    if AUTH_ENABLED and not _cookie_valid(websocket.cookies.get(SESSION_COOKIE)):
        await websocket.close(code=4001)
        return
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
            "COLONY_TOPIC_PROMPT": pick_run_topic(),
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
                from colonyv_agent import publishing

                _topic = pipeline_state.get("run_topic", "")
                cmd = [
                    py_exec, str(AGENTS_DIR / "publisher" / "youtube.py"),
                    "upload", str(video_path),
                    "--title", publishing.build_title(script),
                    "--description", publishing.build_description(script, topic=_topic),
                    "--tags", ",".join(publishing.build_keyword_tags(topic=_topic)),
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
                await send_notification(f"Pipeline complete: {pipeline_state['content_done']}/{len(stories_list)} pieces of content rendered", level="success")

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
            await send_notification(f"Pipeline error: {e}", level="error")
    finally:
        pipeline_state["running"] = False
        pipeline_state["start_time"] = None
        pipeline_state["last_completed_at"] = datetime.now().isoformat()
        _persist_run_summary()
        schedule_board_cooldown()
        # Record where the newly published video starts from, so the performance
        # curve has a baseline the moment it goes live.
        try:
            await asyncio.to_thread(snapshot_performance, True)
        except Exception as exc:
            log(f"[performance] post-run snapshot failed: {exc}")


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
# Do NOT arm the schedule at startup. A manual run is the trigger that starts
# the cadence; until then, saving settings / restarting must not fire runs.


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
    if scheduler_config.get("next_run"):
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
    "on_complete": settings["notifications"].get("on_complete", True),
    "on_error": settings["notifications"].get("on_error", True),
}

# In-app notification log: persisted locally so any logged-in session visiting
# Settings -> Alerts & Notifications sees the same history on this host.
NOTIFICATIONS_LOG_PATH = CONFIG_DIR / "notifications.json"
MAX_SAVED_NOTIFICATIONS = 50


def _load_notification_log() -> list[dict]:
    if NOTIFICATIONS_LOG_PATH.exists():
        try:
            with open(NOTIFICATIONS_LOG_PATH) as f:
                data = json.load(f)
            if isinstance(data, list):
                return data[-MAX_SAVED_NOTIFICATIONS:]
        except (OSError, json.JSONDecodeError):
            pass
    return []


def _append_notification(level: str, message: str) -> None:
    log_entries = _load_notification_log()
    log_entries.append({
        "id": f"{int(time.time() * 1000)}-{uuid.uuid4().hex[:4]}",
        "ts": datetime.now().isoformat(),
        "level": level,  # success | error | info
        "message": message,
    })
    try:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        tmp = NOTIFICATIONS_LOG_PATH.with_suffix(".json.tmp")
        with open(tmp, "w") as f:
            json.dump(log_entries[-MAX_SAVED_NOTIFICATIONS:], f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, NOTIFICATIONS_LOG_PATH)
    except OSError:
        pass


@app.get("/api/notifications")
async def api_notifications_get():
    return {
        "slack_webhook": notification_config["slack_webhook"] or "",
        "slack_configured": bool(notification_config["slack_webhook"]),
        "on_complete": notification_config["on_complete"],
        "on_error": notification_config["on_error"],
        "notifications": list(reversed(_load_notification_log())),
    }


@app.post("/api/notifications")
async def api_notifications_set(request: Request):
    body = await request.json() or {}
    # Never silently wipe a configured endpoint: an empty value keeps the
    # previously saved webhook unless an explicit "clear_webhook" flag is set.
    value = body.get("slack_webhook")
    if value:
        notification_config["slack_webhook"] = str(value).strip()
    for key in ("on_complete", "on_error"):
        if key in body:
            notification_config[key] = bool(body[key])
    if body.get("clear_webhook"):
        notification_config["slack_webhook"] = ""
    settings["notifications"].update({
        key: notification_config[key]
        for key in ("slack_webhook", "on_complete", "on_error")
        if key in notification_config
    })
    save_settings()
    return {"status": "ok"}


# --- RSS Feeds ---

def _load_feeds() -> list[dict]:
    if FEEDS_PATH.exists():
        try:
            with open(FEEDS_PATH) as f:
                data = json.load(f)
            if isinstance(data, list):
                return data
        except (json.JSONDecodeError, OSError, ValueError):
            pass
    return list(DEFAULT_FEEDS)


def _save_feeds(feeds: list[dict]) -> None:
    FEEDS_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = FEEDS_PATH.with_suffix(".json.tmp")
    with open(tmp, "w") as f:
        json.dump(feeds, f, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, FEEDS_PATH)


@app.get("/api/feeds")
async def api_feeds_get():
    return {"feeds": _load_feeds()}


@app.post("/api/feeds")
async def api_feeds_set(request: Request):
    body = await request.json() or {}
    feeds = body.get("feeds")
    if not isinstance(feeds, list):
        return JSONResponse({"error": "feeds must be a list"}, 400)
    cleaned = []
    for f in feeds:
        if not isinstance(f, dict):
            continue
        url = str(f.get("url", "")).strip()
        category = str(f.get("category", "tech")).strip() or "tech"
        if not url:
            continue
        cleaned.append({
            "url": url,
            "category": category,
            "enabled": False if f.get("enabled") in (False, "false", 0) else True,
        })
    _save_feeds(cleaned)
    return {"feeds": cleaned}


@app.post("/api/notifications/test")
async def api_notifications_test():
    sent = []
    if notification_config["slack_webhook"]:
        try:
            import requests
            loop = asyncio.get_running_loop()
            resp = await loop.run_in_executor(
                None,
                lambda: requests.post(
                    notification_config["slack_webhook"],
                    json={"text": "Content Ops Dashboard: Test notification"},
                    timeout=10,
                ),
            )
            sent.append("slack")
        except Exception as e:
            return {"error": f"Slack failed: {e}"}

    return {"sent": sent}


@app.post("/api/notifications/clear")
async def api_notifications_clear():
    try:
        if NOTIFICATIONS_LOG_PATH.exists():
            NOTIFICATIONS_LOG_PATH.unlink()
    except OSError:
        pass
    return {"status": "ok"}


async def send_notification(message: str, level: str = "info"):
    """Record a notification in-app (always) and push to Slack (if configured)."""
    _append_notification(level, message)
    webhook = notification_config["slack_webhook"]
    if not webhook:
        return
    try:
        import requests
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(
            None,
            lambda: requests.post(webhook, json={"text": f"Content Ops: {message}"}, timeout=10),
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

    def _performance_loop():
        """Accumulate the view-count history the analytics chart is built from.

        Runs independently of the pipeline: view counts keep changing long after a
        video is published, and the point of the chart is to show that. The
        snapshot function is itself rate-limited, so polling more often than the
        minimum interval is harmless.
        """
        # Let the app finish starting before touching the network.
        time.sleep(30)
        while True:
            try:
                snapshot_performance()
            except Exception as exc:
                log(f"[performance] scheduled snapshot failed: {exc}")
            time.sleep(600)

    threading.Thread(target=_performance_loop, daemon=True).start()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
