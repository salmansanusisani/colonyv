#!/usr/bin/env python3
"""
ScenePlanner Agent - turns a scriptwriter beat list into an explicit scene plan.

Each beat is assigned the Remotion scene template that best fits its content
(hook, kinetic, stat, diagram, timeline, quiet) so the visual producer renders
story-specific motion instead of generic editorial scenes.

Usage:
    python3 planner.py --script-json <script_output.json>
    echo '{"story_id":"...","suggested_visual_beats":[...]}' | python3 planner.py --stdin

Output: ScenePlan JSON on stdout (schema-validated) under "=== Scene Plan ===".
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
SCHEMA_PATH = PROJECT_ROOT / "contracts" / "scene_plan.schema.json"

LLM_MODEL_ID = os.environ.get("COLONYV_GEMINI_MODEL", "gemini-3.5-flash")
LLM_MAX_TOKENS = 3000
MAX_RETRIES = 3

SCENE_TYPES = {"stat", "diagram", "kinetic", "image", "timeline", "quiet"}


def load_schema():
    with open(SCHEMA_PATH) as f:
        return json.load(f)


def sanitize_scene_plan(plan: dict) -> dict | None:
    if not isinstance(plan, dict):
        return None
    accent = plan.get("accent_color", "")
    scenes = []
    raw = plan.get("scenes", [])
    if not isinstance(raw, list):
        raw = []
    for s in raw:
        if not isinstance(s, dict):
            continue
        scene_type = str(s.get("scene_type", "")).lower()
        if scene_type not in SCENE_TYPES:
            continue
        beat_name = str(s.get("beat_name", ""))
        if not beat_name:
            continue
        entry = {"beat_name": beat_name, "scene_type": scene_type}
        if s.get("stat_value"):
            entry["stat_value"] = str(s["stat_value"])[:24]
        if s.get("headline"):
            entry["headline"] = str(s["headline"])[:60]
        scenes.append(entry)
    if not scenes:
        return None
    out = {"scenes": scenes}
    if isinstance(accent, str) and accent.startswith("#") and len(accent) == 7:
        out["accent_color"] = accent
    return out


def generate_plan(script: dict) -> dict | None:
    from colonyv_agent.gemini import generate_json

    beats = script.get("suggested_visual_beats", [])
    beat_lines = []
    for i, b in enumerate(beats):
        if not isinstance(b, dict):
            continue
        beat_lines.append(
            f"{i}. name={b.get('name', '')} | beat_type={b.get('beat_type', '')} | "
            f"narration={b.get('narration_text', '')[:140]}"
        )
    beats_text = "\n".join(beat_lines) if beat_lines else "none"

    prompt = f"""You are a motion-graphics scene planner for a portrait (1080x1920) tech-news video.

SCRIPT ACCENT: {script.get('accent_color', '#7C3AED')}

VISUAL BEATS (body scenes):
{beats_text}

INSTRUCTIONS:
For EACH beat choose exactly one scene_type from:
- "stat" when the narration contains a concrete number, price, percent, or figure — give stat_value (the exact figure, keep units) and a 3-4 word headline
- "diagram" when the narration explains a mechanism, relationship, or process with two clear sides
- "kinetic" when it is an opinion/analysis point with no number and no two-sided mechanism
- "image" when a supporting photo makes the point stronger (beat has asset/image context)
- "timeline" when the narration sequences dates or events
- "quiet" for the closing reflection or CTA-adjacent beat

RULES:
- Do not invent numbers. stat_value must come verbatim from the narration.
- headline is short on-screen text (max 8 words), not a full sentence.
- Optional: accent_color override (hex) if the story needs a different mood; otherwise omit.

Return ONLY JSON:
{{"accent_color": "#RRGGBB", "scenes": [{{"beat_name": "<name>", "scene_type": "<type>", "stat_value": "<optional>", "headline": "<optional>"}}]}}"""

    for attempt in range(MAX_RETRIES):
        try:
            raw = generate_json(prompt)
            return sanitize_scene_plan(raw)
        except (json.JSONDecodeError, KeyError, TypeError) as e:
            print(f"  [warn] Parse error attempt {attempt + 1}: {e}", file=sys.stderr)
            if attempt < MAX_RETRIES - 1:
                time.sleep(5)
        except Exception as e:
            err_str = str(e)
            if "429" in err_str or "RATE_LIMIT" in err_str:
                wait = 30 * (attempt + 1)
                print(f"  [warn] Rate limited, waiting {wait}s...", file=sys.stderr)
                time.sleep(wait)
            else:
                print(f"  [warn] LLM error attempt {attempt + 1}: {e}", file=sys.stderr)
                if attempt < MAX_RETRIES - 1:
                    time.sleep(5)
    return None


def main():
    parser = argparse.ArgumentParser(description="ScenePlanner Agent")
    parser.add_argument("--script-json", type=str, help="Path to ScriptOutput JSON file")
    parser.add_argument("--stdin", action="store_true", help="Read ScriptOutput from stdin")
    args = parser.parse_args()

    if args.script_json:
        with open(args.script_json) as f:
            script = json.load(f)
    elif args.stdin:
        script = json.load(sys.stdin)
    else:
        print("Error: provide --script-json or --stdin", file=sys.stderr)
        return 2

    plan = generate_plan(script)
    if not plan:
        print("Error: Scene plan generation failed.", file=sys.stderr)
        return 1

    print("=== Scene Plan ===")
    print(json.dumps(plan, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())