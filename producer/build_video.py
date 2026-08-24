#!/usr/bin/env python3
"""
build_video.py — Generic video renderer for Content Ops Agent.

Input: A ScriptOutput JSON file (conforming to contracts/script_output.schema.json).
Output: A rendered mp4 video (portrait 1080x1920).

Architecture (same as bitcoin-remotion):
  - 3 audio files: hook, body (continuous), cta
  - Body beats split by word-count proportion, remainder absorbs rounding
  - No trail silence padding — audio IS the timing
  - fraction-based crossfades between beats

Usage:
    python3 build_video.py path/to/script.json [--output path/to/output.mp4]
"""

import argparse
import asyncio
import json
import math
import os
import random
import struct
import subprocess
import sys
import wave
from pathlib import Path
from typing import Any

PRODUCER_DIR = Path(__file__).parent
PUBLIC_DIR = PRODUCER_DIR / "public"
FPS = 30
SAMPLE_RATE = 44100

VOICE = "en-US-AndrewNeural"


def load_script(path: str) -> dict[str, Any]:
    with open(path) as f:
        return json.load(f)


def validate_script(data: dict[str, Any]) -> None:
    required = [
        "hook", "body", "cta", "estimated_duration",
        "format", "claims_used", "suggested_visual_beats",
    ]
    for field in required:
        if field not in data:
            raise ValueError(f"ScriptOutput missing required field: {field}")

    for i, beat in enumerate(data["suggested_visual_beats"]):
        if "name" not in beat:
            raise ValueError(f"Beat {i} missing 'name'")
        if "narration_text" not in beat:
            raise ValueError(f"Beat {i} missing 'narration_text'")


async def generate_tts(text: str, out_path: Path) -> None:
    import edge_tts
    clean_text = (text or "").strip()
    if not clean_text:
        clean_text = "..."
    communicate = edge_tts.Communicate(clean_text, VOICE)
    await communicate.save(str(out_path))


def measure_duration_seconds(path: Path) -> float:
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


# ---------- SFX synthesis (pure Python, no downloads) ----------

def write_wav(path: Path, samples: list) -> None:
    with wave.open(str(path), "w") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(SAMPLE_RATE)
        frames = b"".join(struct.pack("<h", max(-32767, min(32767, int(s)))) for s in samples)
        f.writeframes(frames)


def synth_whoosh(duration_s: float = 0.45) -> list:
    n = int(SAMPLE_RATE * duration_s)
    out = []
    for i in range(n):
        t = i / n
        envelope = math.sin(math.pi * t) ** 0.6
        noise = random.uniform(-1, 1)
        out.append(noise * envelope * 9000)
    return out


def synth_pop(duration_s: float = 0.09) -> list:
    n = int(SAMPLE_RATE * duration_s)
    out = []
    freq = 220.0
    for i in range(n):
        t = i / SAMPLE_RATE
        envelope = math.exp(-t * 45)
        out.append(math.sin(2 * math.pi * freq * t) * envelope * 12000)
    return out


def synth_ding(duration_s: float = 0.55) -> list:
    n = int(SAMPLE_RATE * duration_s)
    out = []
    fundamental = 1046.5
    for i in range(n):
        t = i / SAMPLE_RATE
        envelope = math.exp(-t * 5.5)
        sample = (
            math.sin(2 * math.pi * fundamental * t) * 1.0
            + math.sin(2 * math.pi * fundamental * 2 * t) * 0.35
            + math.sin(2 * math.pi * fundamental * 3 * t) * 0.15
        )
        out.append(sample * envelope * 7000)
    return out


def build_sfx(sfx_dir: Path) -> None:
    print("Synthesizing sound effects...")
    write_wav(sfx_dir / "whoosh.wav", synth_whoosh())
    write_wav(sfx_dir / "pop.wav", synth_pop())
    write_wav(sfx_dir / "ding.wav", synth_ding())
    print("  whoosh.wav, pop.wav, ding.wav")


# ---------- Placeholder images ----------

def generate_placeholder_image(name: str, output_path: Path, width: int = 1080, height: int = 1920) -> None:
    try:
        from PIL import Image, ImageDraw, ImageFilter

        rng = random.Random(hash(name))
        img = Image.new("RGB", (width, height), color=(10, 12, 25))
        draw = ImageDraw.Draw(img)

        palette = [
            (0, 180, 255),
            (255, 80, 120),
            (80, 255, 180),
            (255, 200, 0),
            (180, 80, 255),
        ]
        color = palette[rng.randint(0, len(palette) - 1)]

        for _ in range(12):
            x = rng.randint(0, width)
            y = rng.randint(0, height)
            r = rng.randint(30, 180)
            alpha = rng.randint(10, 40)
            draw.ellipse([x - r, y - r, x + r, y + r], fill=(*color, alpha))

        img = img.filter(ImageFilter.GaussianBlur(radius=8))
        img.save(str(output_path))
    except ImportError:
        pass


# ---------- Main build ----------

async def build_video(script_path: str, output_path: str | None = None) -> None:
    import shutil

    script_data = load_script(script_path)
    validate_script(script_data)

    script_stem = Path(script_path).stem
    render_dir = PRODUCER_DIR / "renders" / script_stem
    audio_dir = render_dir / "audio"
    sfx_dir = render_dir / "sfx"
    images_dir = render_dir / "images"

    for d in [audio_dir, sfx_dir, images_dir]:
        d.mkdir(parents=True, exist_ok=True)

    beats_data = script_data["suggested_visual_beats"]
    body_text = " ".join(b["narration_text"] for b in beats_data)

    # --- 1. Generate 3 audio files (no padding) ---
    print(f"[1/4] Generating 3 audio files (voice={VOICE})...")

    hook_path = audio_dir / "01_hook.mp3"
    body_path = audio_dir / "02_body.mp3"
    cta_path = audio_dir / "03_cta.mp3"

    await generate_tts(script_data["hook"], hook_path)
    await generate_tts(body_text, body_path)
    await generate_tts(script_data["cta"], cta_path)

    hook_s = measure_duration_seconds(hook_path)
    body_s = measure_duration_seconds(body_path)
    cta_s = measure_duration_seconds(cta_path)

    wps = 2.6
    if hook_s is None:
        hook_s = len(script_data["hook"].split()) / wps
    if body_s is None:
        body_s = len(body_text.split()) / wps
    if cta_s is None:
        cta_s = len(script_data["cta"].split()) / wps

    hook_frames = round(hook_s * FPS)
    body_frames = round(body_s * FPS)
    outro_frames = round(cta_s * FPS)

    print(f"  hook:  {hook_s:.2f}s -> {hook_frames}f")
    print(f"  body:  {body_s:.2f}s -> {body_frames}f")
    print(f"  outro: {cta_s:.2f}s -> {outro_frames}f")

    # --- 2. Split body frames by word count (remainder absorbs rounding) ---
    word_counts = {b["name"]: len(b.get("narration_text", "").split()) for b in beats_data}
    total_words = sum(word_counts.values())
    if total_words == 0:
        total_words = 1
    keys = [b["name"] for b in beats_data]
    beat_frames = {}
    allocated = 0
    for i, k in enumerate(keys):
        if i < len(keys) - 1:
            f = round(word_counts[k] / total_words * body_frames)
            beat_frames[k] = f
            allocated += f
        else:
            beat_frames[k] = body_frames - allocated

    print("  beat split:")
    for k, f in beat_frames.items():
        print(f"    {k}: {f}f ({f / FPS:.2f}s)")

    # --- 3. SFX ---
    print("[2/4] Generating SFX...")
    build_sfx(sfx_dir)

    # --- 4. Placeholder images ---
    print("[3/4] Generating placeholder images...")
    image_names = ["hook", "outro"] + [b["name"] for b in beats_data]
    for img_name in image_names:
        img_file = images_dir / f"{img_name}.png"
        if not img_file.exists():
            generate_placeholder_image(img_name, img_file)

    # --- 5. Write timing.json ---
    timing = {
        "hookFrames": hook_frames,
        "outroFrames": outro_frames,
        "beats": beat_frames,
    }
    timing_file = render_dir / "timing.json"
    timing_file.write_text(json.dumps(timing, indent=2))
    print(f"  Timing written to {timing_file}")

    # Also write a flat timing for build_video reference
    render_timing_file = PRODUCER_DIR / "src" / "timing.json"
    render_timing_file.write_text(json.dumps(timing, indent=2))

    # --- 6. Copy to public/ ---
    print("[4/4] Rendering video with Remotion...")

    for sub in ["audio", "sfx", "images"]:
        target = PUBLIC_DIR / sub
        if target.exists():
            shutil.rmtree(str(target))
        target.mkdir(parents=True, exist_ok=True)

    shutil.copy2(str(hook_path), str(PUBLIC_DIR / "audio" / "01_hook.mp3"))
    shutil.copy2(str(body_path), str(PUBLIC_DIR / "audio" / "02_body.mp3"))
    shutil.copy2(str(cta_path), str(PUBLIC_DIR / "audio" / "03_cta.mp3"))

    for sfx_name in ["whoosh", "pop", "ding"]:
        src = sfx_dir / f"{sfx_name}.wav"
        if src.exists():
            shutil.copy2(str(src), str(PUBLIC_DIR / "sfx" / f"{sfx_name}.wav"))

    for img_path in images_dir.glob("*"):
        if img_path.suffix.lower() in [".png", ".jpg", ".jpeg"]:
            shutil.copy2(str(img_path), str(PUBLIC_DIR / "images" / img_path.name))

    # Save script with timing for reference
    script_with_timing = {**script_data, "_timing": timing}
    (render_dir / "script_with_timing.json").write_text(json.dumps(script_with_timing, indent=2))

    # --- 7. Remotion render ---
    chromium_path = os.environ.get("REMOTION_CHROMIUM_EXECUTABLE_PATH", "/usr/bin/chromium")

    # Determine output path for the rendered video
    if output_path:
        output = output_path
    else:
        output = str(render_dir / f"{script_stem}.mp4")

    remotion_cmd = [
        "npx", "remotion", "render",
        "src/index.ts",
        "ContentVideo",
        output,
        "--concurrency=4",
        "--gl=angle-egl",
    ]
    if Path(chromium_path).exists():
        remotion_cmd.extend(["--browser-executable", chromium_path])

    result = subprocess.run(
        remotion_cmd,
        cwd=str(PRODUCER_DIR),
    )

    if result.returncode != 0:
        raise RuntimeError(f"Remotion render failed with code {result.returncode}")

    print(f"\nDone! Video rendered to: {output}")
    print(f"Timing data: {timing_file}")
    print(f"  hook: {hook_s:.2f}s ({hook_frames}f)")
    for k, f in beat_frames.items():
        print(f"  {k}: {f / FPS:.2f}s ({f}f)")
    print(f"  outro: {cta_s:.2f}s ({outro_frames}f)")


def main() -> None:
    parser = argparse.ArgumentParser(description="Render a video from a ScriptOutput JSON")
    parser.add_argument("script_json", help="Path to ScriptOutput JSON file")
    parser.add_argument("--output", "-o", help="Output video path")
    args = parser.parse_args()

    asyncio.run(build_video(args.script_json, args.output))


if __name__ == "__main__":
    main()
