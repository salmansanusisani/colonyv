#!/usr/bin/env python3
"""
illustrate.py — turns a VisualPlan's illustration prompts into rendered art.

Uses Gemini's image model to draw one bespoke illustration per planned shot, in
portrait 9:16, locked to the episode's palette and style contract so separately
generated images read as a single film.

Design notes
------------
Cost control is the primary constraint. Image generation dominates the cost of a
run, so every result is cached on a content hash of everything that affects the
pixels (prompt, style contract, palette, aspect, model). Re-renders, render
retries, and repeated experiments therefore cost nothing.

Failure is always soft. A missing illustration downgrades that shot to a
text-forward layout rather than failing the video, and the manifest records what
happened so the renderer and the dashboard can both see it.

Usage:
    python3 illustrate.py --plan <visual_plan.json> --out-dir <dir> [--budget 4]
"""

from __future__ import annotations

import argparse
import concurrent.futures as futures
import hashlib
import json
import os
import random
import re
import sys
import threading
import time
from pathlib import Path
from typing import Any

PRODUCER_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = PRODUCER_DIR.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

CACHE_DIR = Path(
    os.environ.get("COLONYV_ILLUSTRATION_CACHE", str(PRODUCER_DIR / ".illustration_cache"))
)

IMAGE_MODEL = os.environ.get("COLONYV_IMAGE_MODEL", "gemini-2.5-flash-image")
ASPECT_RATIO = "9:16"
# Bump when post-processing changes, to invalidate cached plates.
CACHE_VERSION = 5
MAX_ATTEMPTS = 4

# Each layout shows its illustration in a differently shaped region. Generating
# the plate at that region's aspect ratio keeps the model's composition intact.
#
# Previously every plate was generated 9:16 and then cover-cropped to fit, which
# was harmless for full-bleed shots but destroyed side-by-side shots: cropping a
# portrait drawing to a narrow vertical column showed a hugely magnified sliver
# of its right edge, usually empty paper.
LAYOUT_ASPECT: dict[str, str] = {
    "illustration_full": "9:16",
    "illustration_top": "1:1",
    "illustration_side": "3:4",
    "data_readout": "5:4",
    "quote_block": "3:2",
    "hero_statement": "9:16",
}
DEFAULT_ASPECT = "9:16"

# Longest edge of a stored plate. Large enough that a full-bleed 1080x1920 plate
# is native resolution, small enough to keep Chromium's rasteriser comfortable.
MAX_EDGE = 1920
# The image model's per-project quota is low. Generating serially with adaptive
# pacing produces a complete shot list far more reliably than generating in
# parallel and hoping the retries win, and total wall time is comparable because
# throttled parallel requests spend their time sleeping anyway.
MAX_WORKERS = int(os.environ.get("COLONYV_ILLUSTRATION_WORKERS", "1"))
# Minimum seconds between request starts. Grows when the API signals quota
# pressure and decays again on sustained success.
MIN_REQUEST_INTERVAL = float(os.environ.get("COLONYV_ILLUSTRATION_INTERVAL", "1.5"))
MAX_REQUEST_INTERVAL = 20.0


class _Pacer:
    """Adaptive rate limiter shared by all illustration requests.

    Vertex reports quota exhaustion without a retry-after hint, so the pacer
    learns the sustainable rate: every 429 widens the gap between requests, and
    a run of successes narrows it again.
    """

    def __init__(self, interval: float) -> None:
        self._interval = interval
        self._next_at = 0.0
        self._streak = 0
        self._lock = threading.Lock()

    def wait(self) -> None:
        with self._lock:
            now = time.monotonic()
            delay = max(0.0, self._next_at - now)
            self._next_at = max(now, self._next_at) + self._interval
        if delay > 0:
            time.sleep(delay)

    def penalise(self) -> None:
        with self._lock:
            self._streak = 0
            self._interval = min(MAX_REQUEST_INTERVAL, max(4.0, self._interval * 2))
            self._next_at = time.monotonic() + self._interval

    def reward(self) -> None:
        with self._lock:
            self._streak += 1
            if self._streak >= 2 and self._interval > MIN_REQUEST_INTERVAL:
                self._interval = max(MIN_REQUEST_INTERVAL, self._interval * 0.7)


_pacer = _Pacer(MIN_REQUEST_INTERVAL)

# Repeated at both ends of every request. Text leaking into a generated
# illustration is the single most damaging failure mode, because the composition
# already carries real typography and a second, usually misspelled, set of words
# looks broken. Stating the rule once was not sufficient in practice: the model
# would still label inherently label-like subjects such as a funding round or a
# product box, so the constraint is now asserted first and last.
NO_TEXT_LEAD = (
    "CRITICAL RULE, READ FIRST: this must be a wordless image. Do not render any text, "
    "letters, numerals, labels, captions, signage, screens showing words, logos, or "
    "watermarks. Not even small, decorative, or blurred text."
)

NO_TEXT_CLAUSE = (
    "ABSOLUTE CONSTRAINT, RESTATED: the image contains ZERO text. No letters, no words, "
    "no numbers, no digits, no labels, no captions, no signage, no logos, no watermarks, "
    "no typography of any kind anywhere in the frame, including on objects, plaques, "
    "screens, boxes, banners and packaging. Leave every surface blank rather than "
    "lettering it. Communicate purely through pictorial shapes; if a concept seems to "
    "need a label, express it with an icon, a colour, or a diagram instead. "
    "An image containing any glyph is a failed image."
)

FIGURE_CLAUSE = (
    "Depict people only as simple, faceless geometric figures. No detailed faces, "
    "no attempts at photorealistic likeness of any real person."
)


def _slug(name: str) -> str:
    stem = re.sub(r"[^A-Za-z0-9_]+", "_", (name or "").strip()).strip("_")
    return stem or "shot"


def _aspect_phrase(aspect: str) -> str:
    """Describe the aspect in words as well as in ratio.

    The image config already constrains the output shape, but restating it in the
    prompt measurably improves how the model composes within that shape.
    """
    phrases = {
        "9:16": "a tall vertical 9:16 portrait poster",
        "3:4": "a vertical 3:4 portrait panel",
        "4:5": "a vertical 4:5 portrait panel",
        "1:1": "a square 1:1 panel",
        "5:4": "a gently landscape 5:4 panel",
        "4:3": "a landscape 4:3 panel",
        "3:2": "a wide landscape 3:2 panel",
        "16:9": "a wide 16:9 landscape panel",
    }
    return phrases.get(aspect, f"a {aspect} panel")


def aspect_for_layout(layout: str | None) -> str:
    return LAYOUT_ASPECT.get(str(layout or ""), DEFAULT_ASPECT)


def build_prompt(
    subject_prompt: str,
    *,
    style_contract: str,
    palette: dict[str, Any],
    aspect: str = DEFAULT_ASPECT,
) -> str:
    """Compose the full image prompt for one shot.

    Order matters: subject first so the model anchors on content, then the style
    contract that unifies the episode, then the palette lock, then the hard
    constraints last so they stay salient.
    """
    ground = palette.get("ground", "#F6F5F1")
    ink = palette.get("ink", "#14150F")
    accent = palette.get("accent", ink)
    role = palette.get("accent_role", "neutral")

    if role == "neutral" or accent.lower() == ink.lower():
        colour_rule = (
            f"PALETTE: strictly monochrome. Warm paper-white ground {ground} and "
            f"near-black {ink} linework only. No other colour anywhere."
        )
    else:
        colour_rule = (
            f"PALETTE: warm paper-white ground {ground}, near-black {ink} linework, and "
            f"exactly ONE accent colour {accent}. Use the accent on AT MOST 15% of the "
            f"image and only on the single most important element. Every other element "
            f"stays black and white. No other hues."
        )

    return "\n\n".join([
        NO_TEXT_LEAD,
        f"SUBJECT AND COMPOSITION:\n{subject_prompt}",
        f"STYLE CONTRACT (obey exactly):\n{style_contract}",
        colour_rule,
        # The layout engine already reserves a type region around the plate, so
        # the plate itself must be filled edge to edge. Asking for negative space
        # here as well produced shots that were two-thirds empty paper.
        (
            "FRAMING: fill this panel with the subject. Centre it and let it occupy "
            "roughly 85% of the panel's width and height, with only a slim, even "
            "breathing margin. Do NOT reserve a large empty area for text, and do NOT "
            "leave the subject small in a corner; the surrounding page layout already "
            "provides the space for typography."
        ),
        # The renderer overlays its own pegboard grid across the whole frame, so a
        # grid drawn into the plate would collide with it and reveal the plate's
        # edge as a seam.
        (
            "GROUND: plain, flat, untextured warm-white paper, edge to edge, filling the "
            "entire panel. Do NOT draw a dot grid, graph paper, grid lines, borders, "
            "frames, rounded corners, vignettes or drop shadows."
        ),
        f"FORMAT: {_aspect_phrase(aspect)}.\n\n{FIGURE_CLAUSE}\n\n{NO_TEXT_CLAUSE}",
    ])


def cache_key(full_prompt: str, aspect: str = DEFAULT_ASPECT) -> str:
    """Content hash of everything that affects the produced pixels.

    CACHE_VERSION is part of the key so that changes to post-processing (for
    example the ground tone matching) invalidate previously cached plates instead
    of silently serving stale art.
    """
    payload = json.dumps(
        {
            "prompt": full_prompt,
            "model": IMAGE_MODEL,
            "aspect": aspect,
            "version": CACHE_VERSION,
        },
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]


def _image_client():
    """Build a Gemini client for image generation.

    The image model is not served from the `global` endpoint in every project, so
    a regional location is used when the caller has not pinned one explicitly.
    """
    from google import genai

    if (
        os.environ.get("GOOGLE_GENAI_USE_VERTEXAI", "").lower() == "true"
        or os.environ.get("GOOGLE_CLOUD_PROJECT")
    ):
        location = (
            os.environ.get("COLONYV_IMAGE_LOCATION")
            or os.environ.get("GOOGLE_CLOUD_LOCATION")
            or "global"
        )
        return genai.Client(
            vertexai=True,
            project=os.environ.get("GOOGLE_CLOUD_PROJECT"),
            location=location,
        )

    api_key = os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError(
            "Set GOOGLE_API_KEY or configure Vertex AI with GOOGLE_CLOUD_PROJECT"
        )
    return genai.Client(api_key=api_key)


def _generate_once(client, full_prompt: str, aspect: str = DEFAULT_ASPECT) -> bytes | None:
    from google.genai import types

    response = client.models.generate_content(
        model=IMAGE_MODEL,
        contents=full_prompt,
        config=types.GenerateContentConfig(
            response_modalities=["IMAGE"],
            image_config=types.ImageConfig(aspect_ratio=aspect),
        ),
    )
    for candidate in response.candidates or []:
        content = getattr(candidate, "content", None)
        for part in (getattr(content, "parts", None) or []):
            inline = getattr(part, "inline_data", None)
            if inline and inline.data:
                return inline.data
    return None


def _sample_ground_tone(image, border_frac: float = 0.04) -> tuple[int, int, int]:
    """Estimate an illustration's paper tone from its outer border.

    The border of a generated plate is almost always untouched ground, so its
    median is a robust estimate of the paper the model chose. The median is used
    rather than the mean so a stray line entering the border cannot drag it.
    """
    w, h = image.size
    band = max(2, int(min(w, h) * border_frac))

    strips = [
        image.crop((0, 0, w, band)),                 # top
        image.crop((0, h - band, w, h)),             # bottom
        image.crop((0, 0, band, h)),                 # left
        image.crop((w - band, 0, w, h)),             # right
    ]

    channels: list[list[int]] = [[], [], []]
    for strip in strips:
        # Downsample hard; we only need a colour estimate, not detail.
        small = strip.resize((max(1, strip.width // 8), max(1, strip.height // 8)))
        for pixel in small.getdata():
            for c in range(3):
                channels[c].append(pixel[c])

    tone = []
    for values in channels:
        values.sort()
        tone.append(values[len(values) // 2] if values else 246)
    return tone[0], tone[1], tone[2]


def _match_ground(image, target_hex: str):
    """Shift an illustration's paper tone to the brand paper colour.

    Generated plates each pick their own warm-white, so the canvas paper and the
    plate paper never matched exactly. Where a plate met the page, that mismatch
    showed as a visible band or vertical seam and destroyed the intended effect of
    ink drawn directly on the page.

    A per-channel additive shift is used rather than a full colour transform
    because it makes the grounds identical while leaving the ink and the single
    accent hue essentially untouched.
    """
    from PIL import Image, ImageChops

    target_hex = target_hex.lstrip("#")
    try:
        target = tuple(int(target_hex[i : i + 2], 16) for i in (0, 2, 4))
    except (ValueError, IndexError):
        return image

    source = _sample_ground_tone(image)
    delta = tuple(target[i] - source[i] for i in range(3))

    # Nothing meaningful to correct, and large deltas mean the border was not
    # actually ground, so leave those alone rather than wrecking the image.
    if all(abs(d) <= 1 for d in delta) or any(abs(d) > 60 for d in delta):
        return image

    shift = Image.new("RGB", image.size, tuple(abs(d) for d in delta))
    if all(d >= 0 for d in delta):
        return ImageChops.add(image, shift)
    if all(d <= 0 for d in delta):
        return ImageChops.subtract(image, shift)

    # Mixed signs: apply each channel independently.
    bands = list(image.split())
    for i, d in enumerate(delta):
        if d == 0:
            continue
        flat = Image.new("L", image.size, abs(d))
        bands[i] = (
            ImageChops.add(bands[i], flat) if d > 0 else ImageChops.subtract(bands[i], flat)
        )
    return Image.merge("RGB", bands)


def _normalise(raw: bytes, out_path: Path, *, ground: str | None = None) -> bool:
    """Write the plate as PNG, tone-matched and capped in resolution.

    The generated aspect ratio is preserved rather than forced to portrait: each
    plate was requested at the shape of the region it will occupy, so re-cropping
    here would undo that.
    """
    try:
        from io import BytesIO

        from PIL import Image

        with Image.open(BytesIO(raw)) as opened:
            image = opened.convert("RGB")

            if ground:
                image = _match_ground(image, ground)

            longest = max(image.size)
            if longest > MAX_EDGE:
                factor = MAX_EDGE / longest
                image = image.resize(
                    (max(1, round(image.width * factor)), max(1, round(image.height * factor))),
                    Image.LANCZOS,
                )

            out_path.parent.mkdir(parents=True, exist_ok=True)
            image.save(out_path, "PNG", optimize=True)
        return True
    except Exception as exc:
        print(f"  [warn] Could not normalise illustration: {exc}", file=sys.stderr)
        out_path.unlink(missing_ok=True)
        return False


def render_illustration(
    client,
    *,
    beat_name: str,
    subject_prompt: str,
    style_contract: str,
    palette: dict[str, Any],
    out_dir: Path,
    aspect: str = DEFAULT_ASPECT,
    use_cache: bool = True,
) -> dict[str, Any]:
    """Produce one illustration. Never raises; reports outcome in the result."""
    full_prompt = build_prompt(
        subject_prompt, style_contract=style_contract, palette=palette, aspect=aspect
    )
    key = cache_key(full_prompt, aspect)
    cached = CACHE_DIR / f"{key}.png"
    out_path = out_dir / f"{_slug(beat_name)}.png"

    result: dict[str, Any] = {
        "beat_name": beat_name,
        "file": out_path.name,
        "cache_key": key,
        "aspect": aspect,
        "available": False,
        "cached": False,
        "prompt": subject_prompt,
    }

    if use_cache and cached.exists() and cached.stat().st_size > 1024:
        try:
            out_dir.mkdir(parents=True, exist_ok=True)
            out_path.write_bytes(cached.read_bytes())
            result.update(available=True, cached=True)
            print(f"  [cache] {beat_name} -> {out_path.name}", flush=True)
            return result
        except OSError:
            pass

    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            _pacer.wait()
            raw = _generate_once(client, full_prompt, aspect)
            if not raw:
                raise RuntimeError("model returned no image part")
            if not _normalise(raw, out_path, ground=palette.get("ground", "#F6F5F1")):
                raise RuntimeError("image could not be decoded")

            if use_cache:
                try:
                    CACHE_DIR.mkdir(parents=True, exist_ok=True)
                    cached.write_bytes(out_path.read_bytes())
                except OSError:
                    pass

            _pacer.reward()
            result.update(available=True)
            print(f"  [gen]   {beat_name} -> {out_path.name}", flush=True)
            return result
        except Exception as exc:
            message = str(exc)
            rate_limited = "429" in message or "RESOURCE_EXHAUSTED" in message
            transient = rate_limited or any(
                token in message for token in ("503", "500", "UNAVAILABLE", "DEADLINE")
            )
            if rate_limited:
                _pacer.penalise()
            print(
                f"  [warn] Illustration failed for {beat_name} "
                f"(attempt {attempt}/{MAX_ATTEMPTS}): {message[:160]}",
                file=sys.stderr,
                flush=True,
            )
            if attempt < MAX_ATTEMPTS and transient:
                # Exponential backoff with jitter. Quota errors recover on a
                # timescale of seconds, and every retry that succeeds here saves
                # a shot from silently losing its art.
                delay = min(30.0, (2.0 ** attempt) * (3.0 if rate_limited else 1.5))
                delay += random.uniform(0, 1.5)
                print(f"         retrying in {delay:.1f}s", file=sys.stderr, flush=True)
                time.sleep(delay)
            elif attempt < MAX_ATTEMPTS:
                time.sleep(2)
            else:
                result["error"] = message[:300]

    return result


def illustrate_plan(
    plan: dict[str, Any],
    out_dir: Path,
    *,
    budget: int | None = None,
    use_cache: bool = True,
) -> dict[str, Any]:
    """Render every illustration the plan asks for, in parallel.

    Mutates the plan in place: shots whose art could not be produced lose their
    `illustration` key and drop to a text-forward layout, so the renderer never
    reserves space for a plate that does not exist.
    """
    shots = plan.get("shots", []) or []
    palette = plan.get("palette", {}) or {}
    style = plan.get("illustration_style", "") or ""

    wanted = [s for s in shots if isinstance(s.get("illustration"), dict)]
    if budget is not None and budget >= 0:
        wanted = sorted(
            wanted, key=lambda s: s["illustration"].get("priority", 3)
        )[:budget]

    wanted_names = {s["beat_name"] for s in wanted}
    manifest: list[dict[str, Any]] = []

    if not wanted:
        print("  No illustrations requested by the visual plan.")
    else:
        out_dir.mkdir(parents=True, exist_ok=True)
        try:
            client = _image_client()
        except Exception as exc:
            print(f"  [warn] Image model unavailable: {exc}", file=sys.stderr)
            client = None

        if client is None:
            manifest = [
                {
                    "beat_name": s["beat_name"],
                    "available": False,
                    "error": "image client unavailable",
                }
                for s in wanted
            ]
        else:
            print(f"  Rendering {len(wanted)} illustration(s) with {IMAGE_MODEL}...", flush=True)
            workers = max(1, min(MAX_WORKERS, len(wanted)))
            with futures.ThreadPoolExecutor(max_workers=workers) as pool:
                jobs = [
                    pool.submit(
                        render_illustration,
                        client,
                        beat_name=s["beat_name"],
                        subject_prompt=s["illustration"]["prompt"],
                        style_contract=style,
                        palette=palette,
                        out_dir=out_dir,
                        aspect=aspect_for_layout(s.get("layout")),
                        use_cache=use_cache,
                    )
                    for s in wanted
                ]
                manifest = [job.result() for job in jobs]

    by_name = {entry["beat_name"]: entry for entry in manifest}

    for shot in shots:
        illustration = shot.get("illustration")
        if not isinstance(illustration, dict):
            continue

        if shot["beat_name"] not in wanted_names:
            # Trimmed by budget before generation was even attempted.
            shot.pop("illustration", None)
        else:
            entry = by_name.get(shot["beat_name"])
            if entry and entry.get("available"):
                illustration["file"] = entry["file"]
                continue
            shot.pop("illustration", None)

        if shot.get("layout") in {"illustration_full", "illustration_top", "illustration_side"}:
            shot["layout"] = "hero_statement"

    produced = sum(1 for e in manifest if e.get("available"))
    reused = sum(1 for e in manifest if e.get("cached"))
    summary = {
        "requested": len(wanted),
        "produced": produced,
        "from_cache": reused,
        "billed": produced - reused,
        "model": IMAGE_MODEL,
        "illustrations": manifest,
    }
    print(
        f"  Illustrations: {produced}/{len(wanted)} produced "
        f"({reused} from cache, {summary['billed']} billed)"
    )
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Render VisualPlan illustrations")
    parser.add_argument("--plan", required=True, help="Path to VisualPlan JSON")
    parser.add_argument("--out-dir", required=True, help="Directory for rendered PNGs")
    parser.add_argument(
        "--budget",
        type=int,
        default=None,
        help="Cap the number of illustrations generated (cost control)",
    )
    parser.add_argument("--no-cache", action="store_true", help="Bypass the illustration cache")
    parser.add_argument(
        "--write-plan",
        action="store_true",
        help="Write the plan back with resolved illustration files and downgraded layouts",
    )
    args = parser.parse_args()

    plan_path = Path(args.plan)
    with open(plan_path) as f:
        plan = json.load(f)

    summary = illustrate_plan(
        plan,
        Path(args.out_dir),
        budget=args.budget,
        use_cache=not args.no_cache,
    )

    if args.write_plan:
        tmp = plan_path.with_suffix(plan_path.suffix + ".tmp")
        with open(tmp, "w") as f:
            json.dump(plan, f, indent=2)
        os.replace(tmp, plan_path)
        print(f"  Plan updated: {plan_path}")

    print("=== Illustration Summary ===")
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
