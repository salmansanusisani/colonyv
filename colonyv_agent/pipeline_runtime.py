"""Runtime hooks linking ADK pipeline tools to the dashboard and Firestore.

The dashboard registers its logger and agent-activity updater here before a
run so that the ADK tools (which run inside Google ADK's loop) can report
progress to the same state the web dashboard streams over WebSocket.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Callable

_log_fn: Callable[[str], None] | None = None
_activity_fn: Callable[[str, str, str], None] | None = None
env_overrides: dict[str, str] = {}
run_id: str | None = None
output_dir: Path | None = None
skip_publish: bool = False


def configure(
    *,
    logger: Callable[[str], None] | None = None,
    activity: Callable[[str, str, str], None] | None = None,
    env: dict[str, str] | None = None,
    out_dir: Path | None = None,
    run: str | None = None,
    skip: bool = False,
) -> None:
    global _log_fn, _activity_fn, env_overrides, output_dir, run_id, skip_publish
    if logger is not None:
        _log_fn = logger
    if activity is not None:
        _activity_fn = activity
    if env is not None:
        env_overrides = env
    if out_dir is not None:
        output_dir = out_dir
    if run is not None:
        run_id = run
    skip_publish = skip


def log(message: str) -> None:
    if _log_fn is not None:
        _log_fn(message)
    else:
        print(message, flush=True)


def activity(key: str, status: str, detail: str) -> None:
    if _activity_fn is not None:
        _activity_fn(key, status, detail)


def process_env() -> dict[str, str]:
    env = {**os.environ, **env_overrides}
    pythonpath = env.get("PYTHONPATH", "")
    project_root = str(Path(__file__).resolve().parent.parent)
    paths = [p for p in pythonpath.split(":") if p] + [project_root]
    env["PYTHONPATH"] = ":".join(dict.fromkeys(paths))
    return env