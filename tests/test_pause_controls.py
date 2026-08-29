"""Regression tests for cooperative pause/resume of live subprocesses.

A pause press must freeze *every* stage, including a stage that is spawned
after the button was pressed while no subprocess was alive (the gap between
factory checkpoints). See pause-harness repros that exposed the original race.
"""

import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from colonyv_agent import pipeline_runtime as runtime
from colonyv_agent.tools import pipeline as tl

REPO_ROOT = Path(__file__).resolve().parent.parent
STEPS = Path(os.environ.get("TMPDIR", "/tmp")) / "colonyv_pause_steps.log"


def _stage_script(path: Path):
    return [
        sys.executable,
        "-c",
        "import time\n"
        f"for i in range(60):\n"
        f"    open({str(path)!r}, 'a').write(str(i) + '\\n')\n"
        "    time.sleep(0.05)",
    ]


def teardown_module():
    if STEPS.exists():
        STEPS.unlink()


@pytest.fixture(autouse=True)
def _clean_runtime_and_steps():
    runtime.configure()
    if STEPS.exists():
        STEPS.unlink()
    yield
    runtime.configure()


def _wait_until(cond, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if cond():
            return True
        time.sleep(0.05)
    return False


def test_spawn_while_paused_is_frozen_until_resume():
    """Regression: pressing pause during a factory gap must freeze the next
    stage's subprocess at spawn, not let it run free to completion."""
    runtime.set_paused(True)
    rc = {}

    def spawn_next():
        result = tl.run_script(
            _stage_script(STEPS),
            cwd=str(REPO_ROOT),
            timeout=30,
            step_label="next",
        )
        rc["value"] = result.returncode

    worker = threading.Thread(target=spawn_next, daemon=True)
    worker.start()

    assert _wait_until(lambda: len(runtime._stopped_for_pause) == 1)
    time.sleep(0.4)
    steps_while_paused = STEPS.read_text() if STEPS.exists() else ""
    assert steps_while_paused == "", (
        f"stage ran free while paused: wrote {steps_while_paused!r}"
    )
    assert worker.is_alive(), "run_script returned while paused"

    runtime.set_paused(False)
    worker.join(timeout=20)
    assert rc.get("value") == 0
    assert len(STEPS.read_text().splitlines()) == 60
    assert runtime._stopped_for_pause == set()


def test_resume_sigcont_reaches_process_stopped_by_spawn_guard():
    """The same frozen process must actually continue (SIGCONT) on resume,
    not stall forever inside run_script."""
    runtime.set_paused(True)
    rc = {}

    def spawn():
        result = tl.run_script(
            _stage_script(STEPS),
            cwd=str(REPO_ROOT),
            timeout=30,
            step_label="next",
        )
        rc["value"] = result.returncode

    worker = threading.Thread(target=spawn, daemon=True)
    worker.start()
    assert _wait_until(lambda: len(runtime._stopped_for_pause) == 1)
    runtime.set_paused(False)
    worker.join(timeout=20)
    assert not worker.is_alive()
    assert rc.get("value") == 0


def test_pause_freezes_already_running_process_and_resume_completes():
    """Mid-run pause freezes the live subprocess; resume lets it finish."""
    rc = {}

    def stage():
        result = tl.run_script(
            _stage_script(STEPS),
            cwd=str(REPO_ROOT),
            timeout=30,
            step_label="stage",
        )
        rc["value"] = result.returncode

    worker = threading.Thread(target=stage, daemon=True)
    worker.start()
    assert _wait_until(lambda: STEPS.exists() and STEPS.read_text() != "")
    assert _wait_until(lambda: worker.is_alive())

    runtime.set_paused(True)
    time.sleep(0.3)
    frozen = STEPS.read_text()
    time.sleep(0.3)
    assert STEPS.read_text() == frozen, "stage kept writing while paused"

    runtime.set_paused(False)
    worker.join(timeout=20)
    assert rc.get("value") == 0
    assert len(STEPS.read_text().splitlines()) == 60


def test_request_stop_kills_frozen_process():
    """Stop must still reap a process that was SIGSTOP'd by the spawn guard."""
    runtime.set_paused(True)
    rc = {}

    def spawn():
        result = tl.run_script(
            _stage_script(STEPS),
            cwd=str(REPO_ROOT),
            timeout=30,
            step_label="next",
        )
        rc["value"] = result.returncode

    worker = threading.Thread(target=spawn, daemon=True)
    worker.start()
    assert _wait_until(lambda: len(runtime._stopped_for_pause) == 1)
    runtime.request_stop()
    worker.join(timeout=20)
    assert not worker.is_alive()
    assert rc.get("value") not in (None, 0)