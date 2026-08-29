"""Render smoke test.

`tsc --noEmit` proves the composition type-checks, which is not the same as
proving it renders. A layer that dereferences a missing field, an invalid CSS
value, or a Remotion component used outside its allowed context all compile
cleanly and then fail inside headless Chromium — historically only discovered
part-way through a multi-minute production render.

This renders a handful of still frames instead, covering every layout in the
library, and is skipped automatically wherever the toolchain is unavailable.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PRODUCER = PROJECT_ROOT / "producer"

# Opt-in: this is minutes of work, so it must not slow the default test run.
ENABLED = os.environ.get("COLONYV_RENDER_SMOKE") == "1"

pytestmark = [
    pytest.mark.skipif(not ENABLED, reason="set COLONYV_RENDER_SMOKE=1 to run"),
    pytest.mark.skipif(shutil.which("npx") is None, reason="Node toolchain unavailable"),
    pytest.mark.skipif(
        not (PRODUCER / "node_modules").is_dir(), reason="producer dependencies not installed"
    ),
]

FPS = 30

# One shot per layout, each carrying the payload its layout requires. The point is
# breadth: every layout and every layer must be exercised at least once.
SHOTS = [
    {
        "beat_name": "__hook__",
        "layout": "hero_statement",
        "kicker": "SMOKE TEST",
        "headline": "Every layout renders without throwing",
        "emphasis_words": ["renders"],
        "type_scale": "xl",
        "text_anchor": "center",
        "transition_in": "fade",
    },
    {
        "beat_name": "beat_01",
        "layout": "data_readout",
        "kicker": "FIGURE",
        "headline": "A measured value",
        "data": {"value": "84000", "prefix": "$", "suffix": "", "label": "Total cost"},
        "transition_in": "cut",
    },
    {
        "beat_name": "beat_02",
        "layout": "node_flow",
        "headline": "A chain of three",
        "nodes": [
            {"label": "Input", "detail": "source", "state": "neutral"},
            {"label": "Process", "detail": "middle", "state": "neutral"},
            {"label": "Output", "detail": "resolved", "state": "good"},
        ],
        "transition_in": "slide",
    },
    {
        "beat_name": "beat_03",
        "layout": "compare_two_up",
        "headline": "Two sides",
        "nodes": [
            {"label": "Before", "detail": "old", "state": "bad"},
            {"label": "After", "detail": "new", "state": "good"},
        ],
        "transition_in": "dot_wipe",
    },
    {
        "beat_name": "beat_04",
        "layout": "timeline_rail",
        "headline": "A sequence in time",
        "events": [
            {"label": "First", "when": "2024"},
            {"label": "Second", "when": "2025"},
            {"label": "Third", "when": "2026"},
        ],
        "transition_in": "rule_wipe",
    },
    {
        "beat_name": "beat_05",
        "layout": "quote_block",
        "kicker": "ON THE RECORD",
        "headline": "A statement worth setting apart from the narration.",
        "transition_in": "fade",
    },
    {
        "beat_name": "beat_06",
        "layout": "hero_statement",
        "kicker": "ANNOTATED",
        "headline": "With callouts attached",
        "annotations": [
            {"text": "Points at something", "anchor": "top_right"},
            {"text": "And another", "anchor": "bottom_left"},
        ],
        "transition_in": "cut",
    },
    {
        "beat_name": "__outro__",
        "layout": "outro_brand",
        "kicker": "COLONY V",
        "headline": "Subscribe for more",
        "transition_in": "fade",
    },
]


def _props() -> dict:
    beats = [s["beat_name"] for s in SHOTS if s["beat_name"] not in ("__hook__", "__outro__")]
    return {
        "script": {
            "hook": "Hook narration.",
            "body": " | ".join(f"Body for {b}." for b in beats),
            "cta": "Call to action.",
            "format": "smoke test",
            "suggested_visual_beats": [
                {"name": b, "narration_text": f"Body for {b}."} for b in beats
            ],
        },
        "timing": {
            "hookFrames": 45,
            "outroFrames": 45,
            "beats": {b: 45 for b in beats},
        },
        "visualPlan": {
            "concept": "Smoke test of every layout.",
            "palette": {
                "ground": "#F6F5F1",
                "ink": "#14150F",
                "accent": "#1F9D55",
                "accent_role": "verified",
            },
            "illustration_style": "Not used; no plates are generated for this test.",
            "motion_language": "precise",
            "shots": SHOTS,
        },
        "brand": {"handle": "@colonyv", "ctaLabel": "FOLLOW"},
        # Audio is irrelevant to a still, and skipping it avoids depending on
        # narration files that this test never generates.
        "sfx": False,
    }


@pytest.fixture(scope="module")
def props_file(tmp_path_factory) -> Path:
    path = tmp_path_factory.mktemp("smoke") / "props.json"
    path.write_text(json.dumps(_props()))
    return path


def _frame_for(index: int) -> int:
    """Middle of the shot at `index`, so transitions are past and copy has settled."""
    return index * 45 + 30


@pytest.mark.parametrize(
    "index,layout",
    [(i, s["layout"]) for i, s in enumerate(SHOTS)],
    ids=[f"{i}-{s['layout']}" for i, s in enumerate(SHOTS)],
)
def test_layout_renders_a_still_without_error(props_file, tmp_path, index, layout):
    out = tmp_path / f"{index}_{layout}.png"
    cmd = [
        "npx", "remotion", "still", "src/index.ts", "ContentVideo", str(out),
        "--frame", str(_frame_for(index)),
        "--props", str(props_file),
        "--no-sandbox",
        "--log", "error",
    ]
    chromium = os.environ.get("REMOTION_CHROMIUM_EXECUTABLE_PATH", "/usr/bin/chromium")
    if Path(chromium).exists():
        cmd += ["--browser-executable", chromium]

    result = subprocess.run(
        cmd, cwd=str(PRODUCER), capture_output=True, text=True, timeout=600
    )

    if result.returncode != 0:
        sys.stderr.write(result.stdout[-3000:])
        sys.stderr.write(result.stderr[-3000:])
    assert result.returncode == 0, f"{layout} failed to render"
    assert out.exists(), f"{layout} produced no output"
    # A frame that renders blank is usually a silently-failed layer.
    assert out.stat().st_size > 8000, f"{layout} rendered a suspiciously empty frame"
