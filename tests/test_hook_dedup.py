"""De-duplication of body beats that repeat the opening hook.

ScriptWriter sometimes echoes the hook as the first body beat, so the same
sentence is narrated twice back-to-back in a rendered video. The producer drops
such duplicate beats before narration/timing/art-direction so the sentence is
spoken once. These tests cover the pure de-dup predicate.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _load(name: str, relative: str):
    spec = importlib.util.spec_from_file_location(name, PROJECT_ROOT / relative)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


build_video = _load("build_video", "producer/build_video.py")


def test_exact_hook_echo_is_a_duplicate():
    hook = "Amazon just ordered two million more Nvidia GPUs, but a massive tech rivalry is brewing behind the scenes."
    beat = "Amazon just ordered two million more Nvidia GPUs, but a massive tech rivalry is brewing behind the scenes."
    assert build_video._beat_repeats_hook(hook, beat) is True


def test_near_verbatim_rephrase_is_a_duplicate():
    assert build_video._beat_repeats_hook(
        "AI moves faster than any team can keep up.",
        "AI moves faster than any team can keep up",
    ) is True


def test_distinct_first_beat_is_kept():
    # Real beat from a different story: shares topic words but is a new point.
    hook = "Are Nvidia supercomputers actually heading to space? Elon Musk reportedly has massive plans for SpaceX and Nvidia."
    beat = "Reports claim SpaceX will exclusively use Nvidia GPUs because Musk considers them the absolute best on the market."
    assert build_video._beat_repeats_hook(hook, beat) is False


def test_empty_inputs_never_duplicates():
    assert build_video._beat_repeats_hook("", "anything") is False
    assert build_video._beat_repeats_hook("hello", "") is False
    assert build_video._beat_repeats_hook("", "") is False
