#!/usr/bin/env python3
"""
build_video.py — Visual Producer for ColonyV.

Input:  a ScriptOutput JSON (contracts/script_output.schema.json)
Output: a rendered portrait MP4 (1080x1920)

Pipeline
--------
1. Narration   one measured TTS file per shot (hook, each beat, CTA).
2. Timing      every shot's duration comes from its own audio file, so the
               visuals can never drift from the voice.
3. Direction   the Art Director authors a VisualPlan: palette, illustration
               style contract, and a per-shot layout/copy/data/art spec.
4. Art         the illustrator renders the planned illustrations with Gemini,
               cached on a content hash so retries cost nothing.
5. Brand       the real COLONY V mark is staged for the watermark and outro.
6. Render      Remotion composes each shot from the layer library.

Every stage after narration degrades softly: a missing plan falls back to a
deterministic one, and a missing illustration downgrades that shot to a
text-forward layout rather than failing the video.

Usage:
    python3 build_video.py path/to/script.json [--output out.mp4]
                           [--visual-plan plan.json] [--research-json research.json]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
import random
import re
import shutil
import struct
import subprocess
import sys
import wave
from pathlib import Path
from typing import Any

PRODUCER_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = PRODUCER_DIR.parent
PUBLIC_DIR = PRODUCER_DIR / "public"

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

FPS = 30
SAMPLE_RATE = 44100
VOICE = os.environ.get("COLONYV_TTS_VOICE", "en-US-AndrewNeural")

HOOK_BEAT = "__hook__"
OUTRO_BEAT = "__outro__"

# Brand assets. icon_logo.png is the transparent sphere mark; it is the only one
# that composites cleanly onto paper.
BRAND_LOGO_SOURCE = PROJECT_ROOT / "icon_logo.png"
BRAND_LOGO_PUBLIC = "brand/logo_mark.png"

DEFAULT_ILLUSTRATION_BUDGET = int(os.environ.get("COLONYV_ILLUSTRATION_BUDGET", "4"))
CHANNEL_HANDLE = os.environ.get("COLONYV_CHANNEL_HANDLE", "@colonyv")


def slug(name: str) -> str:
    stem = re.sub(r"[^A-Za-z0-9_]+", "_", (name or "").strip()).strip("_")
    return stem or "shot"


# ---------------------------------------------------------------------------
# Script loading
# ---------------------------------------------------------------------------

def load_script(path: str) -> dict[str, Any]:
    with open(path) as f:
        return json.load(f)


def validate_script(data: dict[str, Any]) -> None:
    required = ["hook", "body", "cta", "estimated_duration", "format",
                "claims_used", "suggested_visual_beats"]
    for field in required:
        if field not in data:
            raise ValueError(f"ScriptOutput missing required field: {field}")

    seen: set[str] = set()
    for i, beat in enumerate(data["suggested_visual_beats"]):
        if "name" not in beat:
            raise ValueError(f"Beat {i} missing 'name'")
        if "narration_text" not in beat:
            raise ValueError(f"Beat {i} missing 'narration_text'")
        if beat["name"] in seen:
            raise ValueError(f"Duplicate beat name {beat['name']!r} in script")
        seen.add(beat["name"])


# ---------------------------------------------------------------------------
# Narration
# ---------------------------------------------------------------------------

async def generate_tts(text: str, out_path: Path) -> None:
    import edge_tts

    clean = (text or "").strip() or "..."
    await edge_tts.Communicate(clean, VOICE).save(str(out_path))


def measure_duration_seconds(path: Path) -> float | None:
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
            capture_output=True, text=True, check=True,
        )
        return float(result.stdout.strip())
    except (subprocess.CalledProcessError, FileNotFoundError, ValueError):
        print(f"  [warn] ffprobe unavailable, estimating duration for {path.name}")
        return None


# ---------------------------------------------------------------------------
# SFX synthesis (pure Python, no downloads)
# ---------------------------------------------------------------------------

def write_wav(path: Path, samples: list[float]) -> None:
    with wave.open(str(path), "w") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(SAMPLE_RATE)
        f.writeframes(
            b"".join(struct.pack("<h", max(-32767, min(32767, int(s)))) for s in samples)
        )


def synth_whoosh(duration_s: float = 0.45) -> list[float]:
    n = int(SAMPLE_RATE * duration_s)
    return [random.uniform(-1, 1) * (math.sin(math.pi * (i / n)) ** 0.6) * 9000 for i in range(n)]


def synth_pop(duration_s: float = 0.09) -> list[float]:
    n = int(SAMPLE_RATE * duration_s)
    out = []
    for i in range(n):
        t = i / SAMPLE_RATE
        out.append(math.sin(2 * math.pi * 220.0 * t) * math.exp(-t * 45) * 12000)
    return out


def synth_ding(duration_s: float = 0.55) -> list[float]:
    n = int(SAMPLE_RATE * duration_s)
    f0 = 1046.5
    out = []
    for i in range(n):
        t = i / SAMPLE_RATE
        sample = (
            math.sin(2 * math.pi * f0 * t)
            + math.sin(2 * math.pi * f0 * 2 * t) * 0.35
            + math.sin(2 * math.pi * f0 * 3 * t) * 0.15
        )
        out.append(sample * math.exp(-t * 5.5) * 7000)
    return out


def build_sfx(sfx_dir: Path) -> None:
    write_wav(sfx_dir / "whoosh.wav", synth_whoosh())
    write_wav(sfx_dir / "pop.wav", synth_pop())
    write_wav(sfx_dir / "ding.wav", synth_ding())


# ---------------------------------------------------------------------------
# Art direction
# ---------------------------------------------------------------------------

def _load_plan(path: Path) -> dict[str, Any] | None:
    try:
        with open(path) as f:
            plan = json.load(f)
        return plan if isinstance(plan, dict) and plan.get("shots") else None
    except (OSError, json.JSONDecodeError):
        return None


def obtain_visual_plan(
    script: dict[str, Any],
    research: dict[str, Any],
    *,
    plan_path: Path | None,
    illustration_budget: int,
) -> dict[str, Any]:
    """Return a VisualPlan, preferring one already produced by the pipeline.

    The ADK pipeline runs the Art Director as its own stage so the dashboard can
    show it, and passes the artifact in with --visual-plan. When build_video is
    invoked directly (tests, manual renders) the director is called inline so the
    renderer is never left without direction.
    """
    if plan_path:
        plan = _load_plan(plan_path)
        if plan:
            print(f"  [plan] using {plan_path.name}")
            return plan
        print(f"  [warn] Could not use visual plan at {plan_path}; directing inline")

    sys.path.insert(0, str(PROJECT_ROOT / "agents" / "artdirector"))
    try:
        from artdirector import fallback_visual_plan, generate_visual_plan

        plan = generate_visual_plan(script, research, illustration_budget=illustration_budget)
        if plan:
            return plan
        print("  [warn] Art director produced no plan; using deterministic fallback")
        return fallback_visual_plan(script, illustration_budget)
    except Exception as exc:
        print(f"  [warn] Art director unavailable ({exc}); using deterministic fallback")
        try:
            from artdirector import fallback_visual_plan

            return fallback_visual_plan(script, illustration_budget)
        except Exception:
            # Absolute last resort: a single hero shot per narration unit.
            return {
                "concept": "Minimal fallback",
                "palette": {"accent_role": "neutral"},
                "illustration_style": "",
                "motion_language": "precise",
                "shots": [
                    {"beat_name": HOOK_BEAT, "layout": "hero_statement",
                     "type_scale": "xl", "text_anchor": "center"},
                    *[
                        {"beat_name": b["name"], "layout": "hero_statement",
                         "type_scale": "lg", "text_anchor": "top"}
                        for b in script.get("suggested_visual_beats", [])
                    ],
                    {"beat_name": OUTRO_BEAT, "layout": "outro_brand"},
                ],
            }


def stage_brand_assets() -> str | None:
    """Copy the COLONY V mark into public/ and return its staticFile path.

    The logo lived in the repository root but was never referenced by the
    renderer; the outro drew a text circle reading "CV" instead.
    """
    target_dir = PUBLIC_DIR / "brand"
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / "logo_mark.png"

    if not BRAND_LOGO_SOURCE.exists():
        print(f"  [warn] Brand mark missing at {BRAND_LOGO_SOURCE}")
        return None

    try:
        from PIL import Image

        with Image.open(BRAND_LOGO_SOURCE) as image:
            image = image.convert("RGBA")
            # Trim the transparent starfield border so the mark optically fills
            # its box in the watermark and outro.
            alpha = image.split()[-1]
            bbox = alpha.getbbox()
            if bbox:
                image = image.crop(bbox)
            image.thumbnail((720, 720), Image.LANCZOS)
            image.save(target, "PNG", optimize=True)
        print(f"  [brand] staged {target.name} ({image.width}x{image.height})")
        return BRAND_LOGO_PUBLIC
    except Exception as exc:
        print(f"  [warn] Could not stage brand mark: {exc}")
        try:
            shutil.copy2(BRAND_LOGO_SOURCE, target)
            return BRAND_LOGO_PUBLIC
        except OSError:
            return None


def derive_cta_label(cta_text: str) -> str:
    """Pick a short button label that matches what the narrator actually says."""
    lowered = (cta_text or "").lower()
    if "subscribe" in lowered:
        return "Subscribe"
    if "follow" in lowered:
        return "Follow"
    if "comment" in lowered:
        return "Join the thread"
    if "link" in lowered or "description" in lowered:
        return "Details below"
    return "Subscribe"


# ---------------------------------------------------------------------------
# Main build
# ---------------------------------------------------------------------------

async def build_video(
    script_path: str,
    output_path: str | None = None,
    *,
    visual_plan_path: str | None = None,
    research_path: str | None = None,
    illustration_budget: int = DEFAULT_ILLUSTRATION_BUDGET,
    no_cache: bool = False,
) -> None:
    script_data = load_script(script_path)
    validate_script(script_data)

    script_stem = Path(script_path).stem
    render_dir = PRODUCER_DIR / "renders" / script_stem
    audio_dir = render_dir / "audio"
    sfx_dir = render_dir / "sfx"
    illo_dir = render_dir / "illustrations"
    for d in (audio_dir, sfx_dir, illo_dir):
        d.mkdir(parents=True, exist_ok=True)

    beats = script_data["suggested_visual_beats"]

    # --- 1. Narration -----------------------------------------------------
    print(f"[1/6] Generating {len(beats) + 2} narration files (voice={VOICE})...")
    hook_path = audio_dir / "01_hook.mp3"
    cta_path = audio_dir / "03_cta.mp3"

    await generate_tts(script_data["hook"], hook_path)
    beat_paths: list[Path] = []
    for i, beat in enumerate(beats):
        p = audio_dir / f"beat_{i + 1:02d}.mp3"
        await generate_tts(beat.get("narration_text", ""), p)
        beat_paths.append(p)
    await generate_tts(script_data["cta"], cta_path)

    # --- 2. Timing from measured audio -----------------------------------
    print("[2/6] Measuring narration...")
    wps = 2.6

    def measured(path: Path, text: str) -> float:
        seconds = measure_duration_seconds(path)
        return seconds if seconds is not None else max(0.6, len(text.split()) / wps)

    hook_s = measured(hook_path, script_data["hook"])
    beat_seconds = [
        measured(p, beats[i].get("narration_text", "")) for i, p in enumerate(beat_paths)
    ]
    cta_s = measured(cta_path, script_data["cta"])

    timing = {
        "hookFrames": max(1, round(hook_s * FPS)),
        "outroFrames": max(1, round(cta_s * FPS)),
        "beats": {
            beats[i]["name"]: max(1, round(seconds * FPS))
            for i, seconds in enumerate(beat_seconds)
        },
    }
    total_s = hook_s + sum(beat_seconds) + cta_s
    print(f"  hook {hook_s:.2f}s | body {sum(beat_seconds):.2f}s | cta {cta_s:.2f}s "
          f"| total {total_s:.2f}s")
    (render_dir / "timing.json").write_text(json.dumps(timing, indent=2))

    # --- 3. Art direction -------------------------------------------------
    print("[3/6] Art direction...")
    research: dict[str, Any] = {}
    if research_path:
        try:
            with open(research_path) as f:
                research = json.load(f)
        except (OSError, json.JSONDecodeError) as exc:
            print(f"  [warn] Could not read research JSON: {exc}")

    plan = obtain_visual_plan(
        script_data,
        research,
        plan_path=Path(visual_plan_path) if visual_plan_path else None,
        illustration_budget=illustration_budget,
    )
    palette = plan.get("palette", {})
    print(f"  concept: {plan.get('concept', '')[:100]}")
    print(f"  accent:  {palette.get('accent')} ({palette.get('accent_role')})")
    print(f"  layouts: {' -> '.join(s.get('layout', '?') for s in plan.get('shots', []))}")

    # --- 4. Illustrations -------------------------------------------------
    print("[4/6] Rendering illustrations...")
    from illustrate import illustrate_plan

    art_summary = illustrate_plan(
        plan, illo_dir, budget=illustration_budget, use_cache=not no_cache
    )
    (render_dir / "art_manifest.json").write_text(json.dumps(art_summary, indent=2))
    (render_dir / "visual_plan.resolved.json").write_text(json.dumps(plan, indent=2))

    # --- 5. Stage assets into public/ ------------------------------------
    print("[5/6] Staging assets...")
    build_sfx(sfx_dir)

    for sub in ("audio", "sfx", "images", "brand"):
        target = PUBLIC_DIR / sub
        if target.exists():
            shutil.rmtree(target)
        target.mkdir(parents=True, exist_ok=True)

    shutil.copy2(hook_path, PUBLIC_DIR / "audio" / "01_hook.mp3")
    shutil.copy2(cta_path, PUBLIC_DIR / "audio" / "03_cta.mp3")
    for p in beat_paths:
        shutil.copy2(p, PUBLIC_DIR / "audio" / p.name)
    for name in ("whoosh", "pop", "ding"):
        src = sfx_dir / f"{name}.wav"
        if src.exists():
            shutil.copy2(src, PUBLIC_DIR / "sfx" / f"{name}.wav")

    # Illustrations are addressed as images/<beat>.png from the composition.
    staged_art = 0
    for shot in plan.get("shots", []):
        illustration = shot.get("illustration")
        if not isinstance(illustration, dict) or not illustration.get("file"):
            continue
        src = illo_dir / illustration["file"]
        if not src.exists():
            shot.pop("illustration", None)
            if shot.get("layout", "").startswith("illustration"):
                shot["layout"] = "hero_statement"
            continue
        rel = f"images/{src.name}"
        shutil.copy2(src, PUBLIC_DIR / rel)
        illustration["file"] = rel
        staged_art += 1
    print(f"  {staged_art} illustration(s) staged")

    logo_path = stage_brand_assets()

    brand = {
        "logo": logo_path,
        "handle": CHANNEL_HANDLE,
        "ctaLabel": derive_cta_label(script_data.get("cta", "")),
    }

    props = {
        "script": script_data,
        "timing": timing,
        "visualPlan": plan,
        "brand": brand,
    }
    props_path = render_dir / "render_props.json"
    props_path.write_text(json.dumps(props, indent=2))

    # --- 6. Render --------------------------------------------------------
    print("[6/6] Rendering with Remotion...")
    output = output_path or str(render_dir / f"{script_stem}.mp4")

    cmd = [
        "npx", "remotion", "render",
        "src/index.ts", "ContentVideo", output,
        "--concurrency=2",
        "--image-format=jpeg",
        "--jpeg-quality=94",
        "--gl", "angle",
        "--no-sandbox",
        "--chromium-options=--disable-dev-shm-usage --no-sandbox",
        "--props", str(props_path),
    ]
    chromium = os.environ.get("REMOTION_CHROMIUM_EXECUTABLE_PATH", "/usr/bin/chromium")
    if Path(chromium).exists():
        cmd += ["--browser-executable", chromium]

    result = subprocess.run(cmd, cwd=str(PRODUCER_DIR))
    if result.returncode != 0:
        raise RuntimeError(f"Remotion render failed with code {result.returncode}")

    size_mb = Path(output).stat().st_size / 1024 / 1024 if Path(output).exists() else 0
    print(f"\nDone: {output} ({size_mb:.1f} MB, {total_s:.1f}s)")
    print(f"  illustrations: {art_summary['produced']}/{art_summary['requested']} "
          f"({art_summary['billed']} billed)")


def main() -> None:
    parser = argparse.ArgumentParser(description="Render a video from a ScriptOutput JSON")
    parser.add_argument("script_json", help="Path to ScriptOutput JSON file")
    parser.add_argument("--output", "-o", help="Output video path")
    parser.add_argument("--visual-plan", help="Path to a VisualPlan JSON from the Art Director")
    parser.add_argument("--research-json", help="Path to ResearchOutput JSON (improves direction)")
    parser.add_argument(
        "--illustrations",
        type=int,
        default=DEFAULT_ILLUSTRATION_BUDGET,
        help="Maximum generated illustrations for this video (cost control)",
    )
    parser.add_argument("--no-cache", action="store_true", help="Bypass the illustration cache")
    # Accepted for backwards compatibility with the legacy ScenePlanner flag.
    parser.add_argument("--scene-plan", help=argparse.SUPPRESS)
    args = parser.parse_args()

    asyncio.run(
        build_video(
            args.script_json,
            args.output,
            visual_plan_path=args.visual_plan,
            research_path=args.research_json,
            illustration_budget=max(0, args.illustrations),
            no_cache=args.no_cache,
        )
    )


if __name__ == "__main__":
    main()
