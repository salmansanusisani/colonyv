"""Runtime hooks linking ADK pipeline tools to the dashboard and Firestore.

The dashboard registers its logger and agent-activity updater here before a
run so that the ADK tools (which run inside Google ADK's loop) can report
progress to the same state the web dashboard streams over WebSocket.

Pause / resume / stop are cooperative controls: the factory loop calls
checkpoint() between stages and stories so a running production can be
frozen mid-run or aborted cleanly from the dashboard.
"""

from __future__ import annotations

import os
import signal
import subprocess
import time
from pathlib import Path
from typing import Callable

_log_fn: Callable[[str], None] | None = None
_activity_fn: Callable[[str, str, str], None] | None = None
env_overrides: dict[str, str] = {}
run_id: str | None = None
output_dir: Path | None = None
skip_publish: bool = False
_paused: bool = False
_stop_requested: bool = False
_active_processes: set[subprocess.Popen] = set()
_pause_start: float | None = None
_paused_total: float = 0.0


def _monotonic() -> float:
    return time.monotonic()


def _accumulate_pause() -> None:
    global _paused_total, _pause_start
    if _pause_start is not None:
        _paused_total += _monotonic() - _pause_start
        _pause_start = None


def _alive() -> list[subprocess.Popen]:
    return [p for p in list(_active_processes) if p is not None and p.poll() is None]


def set_active_process(proc: subprocess.Popen | None) -> None:
    """Register a running subprocess so pause/stop can signal it.

    Multiple concurrent stages are tracked as a set so a stop or pause signals
    every live subprocess. Teardown uses unregister_process(); passing None is
    a legacy no-op kept for compatibility.
    """
    if proc is None:
        return
    _active_processes.add(proc)


def unregister_process(proc: subprocess.Popen | None) -> None:
    if proc is not None:
        _active_processes.discard(proc)


def configure(
    *,
    logger: Callable[[str], str | None] | None = None,
    activity: Callable[[str, str, str], None] | None = None,
    env: dict[str, str] | None = None,
    out_dir: Path | None = None,
    run: str | None = None,
    skip: bool = False,
    reset_controls: bool = True,
) -> None:
    global _log_fn, _activity_fn, env_overrides, output_dir, run_id, skip_publish, _paused, _stop_requested, _paused_total
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
    if reset_controls:
        _paused = False
        _stop_requested = False
        _accumulate_pause()
        _paused_total = 0.0
        _active_processes.clear()


def set_paused(flag: bool) -> None:
    global _paused, _pause_start
    flag = bool(flag)
    if flag == _paused:
        return
    _paused = flag
    if flag:
        _pause_start = _monotonic()
    else:
        _accumulate_pause()
    sig = signal.SIGSTOP if _paused else signal.SIGCONT
    for p in _alive():
        try:
            os.killpg(p.pid, sig)
        except Exception:
            pass


def paused_elapsed() -> float:
    """Total wall-clock seconds the run has spent paused (incl. ongoing pause)."""
    total = _paused_total
    if _paused and _pause_start is not None:
        total += _monotonic() - _pause_start
    return total


def log(message: str) -> None:
    if _log_fn is not None:
        _log_fn(message)
    else:
        print(message, flush=True)


def activity(key: str, status: str, detail: str) -> None:
    if _activity_fn is not None:
        _activity_fn(key, status, detail)


def request_stop() -> None:
    global _stop_requested, _paused
    _stop_requested = True
    _paused = False
    _accumulate_pause()
    for p in _alive():
        try:
            os.killpg(p.pid, signal.SIGKILL)
        except Exception:
            pass


def is_stop_requested() -> bool:
    return bool(_stop_requested)


def is_paused() -> bool:
    return bool(_paused)


def checkpoint(label: str = "") -> bool:
    """Cooperative control point for the factory loop.

    Blocks while a run is paused, and returns False when a stop was
    requested so the caller can abort cleanly.
    """
    if _stop_requested:
        return False
    while _paused and not _stop_requested:
        time.sleep(0.5)
    return not _stop_requested


def process_env() -> dict[str, str]:
    env = {**os.environ, **env_overrides}
    env["PYTHONUNBUFFERED"] = "1"
    pythonpath = env.get("PYTHONPATH", "")
    project_root = str(Path(__file__).resolve().parent.parent)
    paths = [p for p in pythonpath.split(":") if p] + [project_root]
    env["PYTHONPATH"] = ":".join(dict.fromkeys(paths))
    return env