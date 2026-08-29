#!/usr/bin/env python3
"""
ArtDirector Agent - authors the per-story visual plan that drives the renderer.

This replaces the legacy ScenePlanner, whose only creative act was picking one of
six hardcoded Remotion templates per beat. The Art Director instead writes a real
art-direction document:

  * a visual concept for the story
  * a semantic palette (green = verified, red = failure, topic hue, or mono)
  * an illustration style contract reused by every shot for visual coherence
  * a shot list: layout, on-screen copy, data, nodes, annotations, and a bespoke
    illustration prompt per shot

The renderer composes each shot from a layer library, so structure varies per
story instead of snapping to a fixed template.

Usage:
    python3 artdirector.py --script-json <script_output.json> [--research-json <research_output.json>]
    echo '{...}' | python3 artdirector.py --stdin

Output: VisualPlan JSON on stdout under "=== Visual Plan ===" (schema-validated).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

SCHEMA_PATH = PROJECT_ROOT / "contracts" / "visual_plan.schema.json"

MAX_RETRIES = 3

HOOK_BEAT = "__hook__"
OUTRO_BEAT = "__outro__"

# --- Brand constants. Ground and ink are fixed so the channel reads as one
# --- identity; only the accent carries story meaning.
BRAND_GROUND = "#F6F5F1"
BRAND_INK = "#14150F"

SEMANTIC_ACCENTS = {
    "verified": "#1F9D55",   # confirmed, shipped, funded, working
    "alert": "#D14343",      # failed, breached, banned, lost, sued
    "neutral": "#14150F",    # colour carries no meaning: stay mono
}

LAYOUTS = {
    "hero_statement",
    "illustration_full",
    "illustration_top",
    "illustration_side",
    "data_readout",
    "node_flow",
    "timeline_rail",
    "compare_two_up",
    "quote_block",
    "outro_brand",
}

# Only these layouts have an illustration slot in the renderer. Diagram layouts
# are deliberately art-free: a node chain or a timeline rail is already a drawing,
# and overlaying a second one reads as clutter.
#
# Requests for art on any other layout are dropped before generation, because an
# illustration that no layout can display is pure wasted spend.
ART_LAYOUTS = {
    "illustration_full",
    "illustration_top",
    "illustration_side",
    "data_readout",
    "quote_block",
}

MOTION_LANGUAGES = {"precise", "energetic", "calm", "urgent"}
TYPE_SCALES = {"xl", "lg", "md", "sm"}
TEXT_ANCHORS = {"top", "center", "bottom"}
ILLO_MOTIONS = {"still", "drift", "push_in", "pull_out", "parallax"}
TRANSITIONS = {"cut", "dot_wipe", "rule_wipe", "slide", "fade"}
NODE_STATES = {"neutral", "good", "bad"}
ANNOTATION_POSITIONS = {
    "top_left", "top_right", "mid_left", "mid_right", "bottom_left", "bottom_right",
}
ACCENT_ROLES = {"verified", "alert", "neutral", "topic"}

HEX_RE = re.compile(r"^#[0-9a-fA-F]{6}$")

# The style contract is the single most load-bearing string in the visual system.
# It is what makes six independently generated illustrations look like one video.
DEFAULT_STYLE_CONTRACT = (
    "Technical editorial illustration: a precision instruction manual crossed with Swiss graphic design. "
    "Ground is warm paper white, covered edge to edge in a faint regular grid of small evenly spaced "
    "perforation dots, like pegboard. Linework is crisp, uniform weight, near-black, drafted with ruler "
    "and compass. Flat vector. No gradients, no soft shadows, no glow, no 3D render, no photography. "
    "Shapes are mostly unfilled white with sparing flat warm-grey fills for depth. Calm, intelligent, "
    "diagrammatic, like a beautiful patent drawing."
)


def load_schema() -> dict:
    with open(SCHEMA_PATH) as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Sanitising. The renderer must never receive a malformed plan, so every field
# is coerced to something drawable and out-of-range values fall back to a sane
# default rather than rejecting the whole plan.
# ---------------------------------------------------------------------------

def _clean_str(value: Any, limit: int) -> str:
    """Clean prose for on-screen display.

    Underscores are deliberately preserved: beat identifiers flow through the
    same plan document, and stripping them silently breaks the join against the
    narration units.
    """
    if not isinstance(value, str):
        value = "" if value is None else str(value)
    value = re.sub(r"[*`]+", "", value)          # markdown emphasis
    value = re.sub(r"^\s*#+\s*", "", value)      # markdown heading marker
    value = re.sub(r"\s+", " ", value).strip()
    return value[:limit]


def _clean_ident(value: Any, limit: int) -> str:
    """Clean an identifier without touching its structural characters."""
    if not isinstance(value, str):
        value = "" if value is None else str(value)
    return re.sub(r"\s+", " ", value).strip()[:limit]


# The director writes in natural design vocabulary rather than our enum tokens.
# Mapping the near-misses preserves its intent instead of silently defaulting.
_ALIASES: dict[str, str] = {
    # type_scale
    "large": "lg", "x_large": "xl", "extra_large": "xl", "huge": "xl", "display": "xl",
    "medium": "md", "regular": "md", "normal": "md", "small": "sm", "tiny": "sm",
    # text_anchor
    "top_left": "top", "top_right": "top", "top_center": "top", "upper": "top",
    "center_left": "center", "center_right": "center", "center_center": "center",
    "middle": "center", "mid": "center",
    "bottom_left": "bottom", "bottom_right": "bottom", "bottom_center": "bottom",
    "lower": "bottom",
    # transition_in
    "slide_up": "slide", "slide_down": "slide", "slide_left": "slide",
    "slide_right": "slide", "push": "slide",
    "fade_in": "fade", "dissolve": "fade", "crossfade": "fade",
    "zoom_in": "cut", "zoom": "cut", "none": "cut", "hard_cut": "cut",
    "wipe": "rule_wipe", "line_wipe": "rule_wipe", "dots": "dot_wipe",
    # node / event state
    "active": "neutral", "default": "neutral", "info": "neutral",
    "accent": "good", "positive": "good", "success": "good", "confirmed": "good",
    "verified": "good", "up": "good",
    "negative": "bad", "failure": "bad", "failed": "bad", "risk": "bad",
    "warning": "bad", "alert": "bad", "down": "bad",
    # illustration motion
    "static": "still", "none_motion": "still", "float": "drift", "pan": "drift",
    "zoom_out": "pull_out", "dolly_in": "push_in", "dolly_out": "pull_out",
    # motion_language
    "dynamic": "energetic", "fast": "energetic", "quiet": "calm", "slow": "calm",
    "tense": "urgent", "clinical": "precise", "technical": "precise",
}


def _enum(value: Any, allowed: set[str], default: str) -> str:
    text = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
    if text in allowed:
        return text
    mapped = _ALIASES.get(text)
    if mapped in allowed:
        return mapped
    return default


def _hex(value: Any, default: str) -> str:
    text = str(value or "").strip()
    if text.startswith("#") and len(text) == 4:  # expand #abc
        text = "#" + "".join(ch * 2 for ch in text[1:])
    return text if HEX_RE.match(text) else default


def _sanitize_palette(raw: Any) -> dict[str, Any]:
    raw = raw if isinstance(raw, dict) else {}
    role = _enum(raw.get("accent_role"), ACCENT_ROLES, "neutral")

    if role in SEMANTIC_ACCENTS:
        # Semantic roles own their hue. The director may not redefine what
        # "verified" looks like, or the channel loses its visual grammar.
        accent = SEMANTIC_ACCENTS[role]
    else:
        accent = _hex(raw.get("accent"), BRAND_INK)

    return {
        "ground": _hex(raw.get("ground"), BRAND_GROUND),
        "ink": _hex(raw.get("ink"), BRAND_INK),
        "accent": accent,
        "accent_role": role,
        "accent_rationale": _clean_str(raw.get("accent_rationale"), 200),
    }


def _sanitize_illustration(raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    prompt = _clean_str(raw.get("prompt"), 700)
    if len(prompt) < 20:
        return None
    try:
        priority = int(raw.get("priority", 3))
    except (TypeError, ValueError):
        priority = 3
    return {
        "prompt": prompt,
        "priority": max(1, min(5, priority)),
        "motion": _enum(raw.get("motion"), ILLO_MOTIONS, "push_in"),
    }


def _sanitize_data(raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    value = _clean_str(raw.get("value"), 24)
    if not value or not re.search(r"\d", value):
        return None
    out: dict[str, Any] = {"value": value}
    for key, limit in (("prefix", 4), ("suffix", 12), ("label", 60)):
        text = _clean_str(raw.get(key), limit)
        if text:
            out[key] = text
    trend = _enum(raw.get("trend"), {"up", "down", "flat"}, "")
    if trend:
        out["trend"] = trend
    return out


def _sanitize_items(raw: Any, label_limit: int, extra_key: str, extra_limit: int, cap: int) -> list[dict]:
    if not isinstance(raw, list):
        return []
    items = []
    for entry in raw[:cap]:
        if not isinstance(entry, dict):
            if isinstance(entry, str) and entry.strip():
                entry = {"label": entry}
            else:
                continue
        label = _clean_str(entry.get("label"), label_limit)
        if not label:
            continue
        item: dict[str, Any] = {
            "label": label,
            "state": _enum(entry.get("state"), NODE_STATES, "neutral"),
        }
        extra = _clean_str(entry.get(extra_key), extra_limit)
        if extra:
            item[extra_key] = extra
        items.append(item)
    return items


def _sanitize_annotations(raw: Any) -> list[dict]:
    if not isinstance(raw, list):
        return []
    out = []
    for entry in raw[:3]:
        if isinstance(entry, str):
            entry = {"text": entry}
        if not isinstance(entry, dict):
            continue
        text = _clean_str(entry.get("text"), 40)
        if not text:
            continue
        out.append({
            "text": text,
            "at": _enum(entry.get("at"), ANNOTATION_POSITIONS, "mid_right"),
            "state": _enum(entry.get("state"), NODE_STATES, "neutral"),
        })
    return out


def _sanitize_shot(raw: Any, index: int, fallback_name: str) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None

    beat_name = _clean_ident(raw.get("beat_name"), 120) or fallback_name
    layout = _enum(raw.get("layout"), LAYOUTS, "hero_statement")

    shot: dict[str, Any] = {
        "beat_name": beat_name,
        "layout": layout,
        "type_scale": _enum(raw.get("type_scale"), TYPE_SCALES, "lg"),
        "text_anchor": _enum(raw.get("text_anchor"), TEXT_ANCHORS, "top"),
        "transition_in": _enum(raw.get("transition_in"), TRANSITIONS, "rule_wipe"),
    }

    headline = _clean_str(raw.get("headline"), 80)
    if headline:
        shot["headline"] = headline
    kicker = _clean_str(raw.get("kicker"), 28)
    if kicker:
        shot["kicker"] = kicker

    emphasis = raw.get("emphasis_words")
    if isinstance(emphasis, list):
        words = [_clean_str(w, 30) for w in emphasis[:4]]
        words = [w for w in words if w]
        if words:
            shot["emphasis_words"] = words

    illustration = _sanitize_illustration(raw.get("illustration"))
    if illustration:
        shot["illustration"] = illustration

    data = _sanitize_data(raw.get("data"))
    if data:
        shot["data"] = data

    nodes = _sanitize_items(raw.get("nodes"), 48, "detail", 64, 4)
    if nodes:
        shot["nodes"] = nodes

    events = _sanitize_items(raw.get("events"), 48, "marker", 16, 4)
    if events:
        shot["events"] = events

    annotations = _sanitize_annotations(raw.get("annotations"))
    if annotations:
        shot["annotations"] = annotations

    # Repair layouts whose required payload the LLM omitted, so the renderer
    # never has to draw an empty diagram.
    if layout == "data_readout" and "data" not in shot:
        shot["layout"] = "hero_statement"
    if layout in {"node_flow", "compare_two_up"} and len(nodes) < 2:
        shot["layout"] = "illustration_top" if illustration else "hero_statement"
    if layout == "timeline_rail" and len(events) < 2:
        shot["layout"] = "illustration_top" if illustration else "hero_statement"
    if layout in {"illustration_full", "illustration_top", "illustration_side"} and not illustration:
        shot["layout"] = "hero_statement"

    # Drop art the renderer has nowhere to put. Done after the layout repairs
    # above so a shot that was just promoted into an art layout keeps its plate.
    if shot.get("illustration") and shot["layout"] not in ART_LAYOUTS:
        shot.pop("illustration", None)

    return shot


def sanitize_visual_plan(
    plan: Any,
    beat_names: list[str],
    *,
    illustration_budget: int,
) -> dict[str, Any] | None:
    """Coerce the LLM response into a renderable, schema-valid VisualPlan."""
    if not isinstance(plan, dict):
        return None

    palette = _sanitize_palette(plan.get("palette"))

    style = _clean_str(plan.get("illustration_style"), 900)
    if len(style) < 80:
        style = DEFAULT_STYLE_CONTRACT

    raw_shots = plan.get("shots")
    if not isinstance(raw_shots, list):
        return None

    expected = [HOOK_BEAT, *beat_names, OUTRO_BEAT]

    def _key(name: str) -> str:
        return re.sub(r"[^a-z0-9]+", "", str(name).lower())

    shots_by_name: dict[str, dict] = {}
    loose_index: dict[str, dict] = {}
    positional: list[dict] = []
    for i, raw in enumerate(raw_shots):
        shot = _sanitize_shot(raw, i, expected[i] if i < len(expected) else f"shot_{i:02d}")
        if not shot:
            continue
        # Keep the first plan for a given narration unit; duplicates would
        # silently overwrite timing.
        shots_by_name.setdefault(shot["beat_name"], shot)
        loose_index.setdefault(_key(shot["beat_name"]), shot)
        positional.append(shot)

    # Rebuild in narration order and synthesise anything the director skipped,
    # because every narration unit must have exactly one shot or audio desyncs.
    # Names are matched exactly, then loosely, then by position, so a small
    # naming drift from the model does not throw away its art direction.
    ordered: list[dict[str, Any]] = []
    for i, name in enumerate(expected):
        shot = shots_by_name.get(name) or loose_index.get(_key(name))
        if shot is None and i < len(positional):
            candidate = positional[i]
            if candidate["beat_name"] not in expected:
                shot = candidate
        if shot is None:
            shot = {
                "beat_name": name,
                "layout": "outro_brand" if name == OUTRO_BEAT else "hero_statement",
                "type_scale": "xl" if name == HOOK_BEAT else "lg",
                "text_anchor": "center" if name == HOOK_BEAT else "top",
                "transition_in": "cut" if name == HOOK_BEAT else "rule_wipe",
            }
        shot = {**shot, "beat_name": name}
        ordered.append(shot)

    # The outro is the brand moment; force it regardless of what the LLM said.
    ordered[-1]["layout"] = "outro_brand"
    ordered[-1].pop("illustration", None)

    _apply_illustration_budget(ordered, illustration_budget)

    return {
        "concept": _clean_str(plan.get("concept"), 240) or "Editorial explainer",
        "palette": palette,
        "illustration_style": style,
        "motion_language": _enum(plan.get("motion_language"), MOTION_LANGUAGES, "precise"),
        "shots": ordered,
    }


def _apply_illustration_budget(shots: list[dict[str, Any]], budget: int) -> None:
    """Keep only the highest-priority illustrations, in place.

    Image generation is the dominant cost of a run, so the director's priority
    field decides which shots earn art. Shots that lose their illustration fall
    back to a text-forward layout instead of rendering an empty plate.
    """
    if budget < 0:
        return

    candidates = [s for s in shots if s.get("illustration")]
    if len(candidates) <= budget:
        return

    ranked = sorted(
        enumerate(candidates),
        key=lambda pair: (pair[1]["illustration"].get("priority", 3), pair[0]),
    )
    for _, shot in ranked[budget:]:
        shot.pop("illustration", None)
        if shot["layout"] in {"illustration_full", "illustration_top", "illustration_side"}:
            shot["layout"] = "hero_statement"


# ---------------------------------------------------------------------------
# Prompting
# ---------------------------------------------------------------------------

def _story_signals(research: dict) -> str:
    """Surface the outcome-shaped facts the director needs to pick an accent."""
    confirmed = research.get("what_is_confirmed") or []
    uncertain = research.get("what_is_uncertain") or []
    entities = research.get("entities") or []
    parts = []
    if confirmed:
        parts.append("CONFIRMED: " + "; ".join(str(c) for c in confirmed[:5]))
    if uncertain:
        parts.append("UNCERTAIN: " + "; ".join(str(u) for u in uncertain[:4]))
    if entities:
        parts.append("ENTITIES: " + ", ".join(str(e) for e in entities[:10]))
    conf = research.get("confidence")
    if conf:
        parts.append(f"RESEARCH CONFIDENCE: {conf}")
    return "\n".join(parts) if parts else "No additional research signals."


def build_prompt(script: dict, research: dict, illustration_budget: int) -> str:
    beats = [b for b in script.get("suggested_visual_beats", []) if isinstance(b, dict)]

    lines = [f'  - beat_name: "{HOOK_BEAT}"  (the opening hook)',
             f'    narration: "{script.get("hook", "")}"']
    for b in beats:
        lines.append(f'  - beat_name: "{b.get("name", "")}"')
        lines.append(f'    narration: "{b.get("narration_text", "")}"')
    lines.append(f'  - beat_name: "{OUTRO_BEAT}"  (the closing call to action)')
    lines.append(f'    narration: "{script.get("cta", "")}"')
    narration_units = "\n".join(lines)

    return f"""You are the Art Director for COLONY V, a channel of illustrated portrait
(1080x1920) news explainers. You do NOT pick from a menu of templates. You design
this specific episode: you choose its palette, its illustration style, and a shot
list that composes layers.

STORY CONCEPT
{research.get('summary', '')}

RECOMMENDED ANGLE: {research.get('recommended_angle', '')}

{_story_signals(research)}

NARRATION UNITS (one shot per unit, in this exact order, using these exact beat_name values):
{narration_units}

=== HOUSE STYLE (non-negotiable) ===
The channel looks like a beautiful technical manual: warm paper-white ground
covered in a faint pegboard dot grid, near-black drafted linework, and exactly ONE
accent colour used on at most 15% of the frame. Everything else is black and white.
Restraint is the aesthetic. Colour is information, never decoration.

=== YOUR DECISIONS ===

1. concept — one sentence describing the visual through-line of THIS episode.

2. palette.accent_role — pick from the story's actual meaning:
   - "verified" if the story is about something confirmed, shipped, funded, proven, working
   - "alert" if it is about failure, breach, ban, loss, lawsuit, risk, collapse
   - "topic" ONLY if the subject genuinely owns a colour in the reader's mind
     (a brand identity, a physical material). Then also give palette.accent as hex.
   - "neutral" if colour would carry no information. This is a valid, strong choice.
   Explain the pick in palette.accent_rationale.
   Do not set palette.ground or palette.ink; the house owns those.

3. illustration_style — one paragraph, max 700 characters, appended to EVERY
   illustration prompt in this video. This is what makes separately generated
   images look like one film. Describe medium, linework, fill behaviour, mood.
   Never mention specific subjects here.

4. motion_language — "precise", "energetic", "calm", or "urgent".

5. shots — one per narration unit, same order, same beat_name.
   Choose the layout that the CONTENT demands:
   - "hero_statement"    a bold typographic statement, no art
   - "illustration_full"  full-bleed art, text overlaid in a safe area
   - "illustration_top"   art in the upper region, text below
   - "illustration_side"  art on one side, text on the other
   - "data_readout"       a figure is the point; requires `data`
   - "node_flow"          a mechanism or causal chain; requires 2-4 `nodes`
   - "compare_two_up"     two things set against each other; requires 2 `nodes`
   - "timeline_rail"      a sequence of dates or steps; requires 2-4 `events`
   - "quote_block"        a direct quotation or official statement
   - "outro_brand"        reserved for "{OUTRO_BEAT}"
   VARY the layouts. Repeating one layout across every shot is a failure.

   Per shot also give:
   - headline: SHORT on-screen text, max 8 words. NOT the narration. It is a
     caption that reinforces the spoken line, never a transcript of it.
   - kicker: optional 1-3 word eyebrow label. Write something specific to this
     story; generic labels like "KEY TAKEAWAY" or "DATA POINT" are forbidden.
   - emphasis_words: up to 4 words inside your headline to tint with the accent.
   - type_scale, text_anchor, transition_in.
   - data / nodes / events / annotations where the layout requires them. Every
     figure and label must come verbatim from the narration. Invent nothing.

6. illustration — you have a budget of {illustration_budget} illustrations for this
   whole video.

   ONLY these layouts can display an illustration:
     illustration_full, illustration_top, illustration_side, data_readout, quote_block
   Do NOT attach an illustration to hero_statement, node_flow, compare_two_up,
   timeline_rail or outro_brand. Those layouts have no art slot and the drawing
   would be discarded. A node chain or timeline is already a diagram; adding a
   second drawing to it is clutter.

   Spend the budget on the shots that gain the most from art. For each:
   - prompt: describe SUBJECT and COMPOSITION only. Give a concrete visual
     METAPHOR for the idea, not a literal newsroom photo. Reserve empty negative
     space where the headline will sit (say where).
     The prompt must NEVER ask for text, letters, numbers or labels in the image,
     and must not name a subject that invites lettering. Do not write prompts
     containing brand names, product names, round names, plaques, signs, banners,
     book covers, screens showing words, or "labelled" anything. Describe form and
     relationship instead: shapes, scale, direction, containment, balance.
   - priority: 1 is most important. Used if the budget has to be trimmed.
   - motion: "still", "drift", "push_in", "pull_out", or "parallax".

Return ONLY a JSON object:
{{"concept": "...",
 "palette": {{"accent_role": "...", "accent": "#RRGGBB", "accent_rationale": "..."}},
 "illustration_style": "...",
 "motion_language": "...",
 "shots": [{{"beat_name": "...", "layout": "...", "kicker": "...", "headline": "...",
             "emphasis_words": ["..."], "type_scale": "...", "text_anchor": "...",
             "transition_in": "...",
             "illustration": {{"prompt": "...", "priority": 1, "motion": "..."}},
             "data": {{"value": "...", "prefix": "...", "suffix": "...", "label": "..."}},
             "nodes": [{{"label": "...", "detail": "...", "state": "..."}}],
             "events": [{{"label": "...", "marker": "...", "state": "..."}}],
             "annotations": [{{"text": "...", "at": "...", "state": "..."}}]}}]}}

Omit any optional key a shot does not need. No markdown, no commentary."""


def generate_visual_plan(
    script: dict,
    research: dict,
    *,
    illustration_budget: int,
) -> dict | None:
    from colonyv_agent.gemini import generate_json

    beat_names = [
        str(b.get("name", ""))
        for b in script.get("suggested_visual_beats", [])
        if isinstance(b, dict) and b.get("name")
    ]
    prompt = build_prompt(script, research, illustration_budget)

    for attempt in range(MAX_RETRIES):
        try:
            # Art direction wants variance so consecutive episodes do not
            # converge on one look; facts are already fixed upstream.
            raw = generate_json(prompt, temperature=0.85)
            plan = sanitize_visual_plan(
                raw, beat_names, illustration_budget=illustration_budget
            )
            if plan:
                return plan
            print(f"  [warn] Plan unusable on attempt {attempt + 1}", file=sys.stderr)
        except (json.JSONDecodeError, KeyError, TypeError) as e:
            print(f"  [warn] Parse error attempt {attempt + 1}: {e}", file=sys.stderr)
        except Exception as e:
            err = str(e)
            if "429" in err or "RATE_LIMIT" in err.upper():
                wait = 30 * (attempt + 1)
                print(f"  [warn] Rate limited, waiting {wait}s...", file=sys.stderr)
                time.sleep(wait)
                continue
            print(f"  [warn] LLM error attempt {attempt + 1}: {e}", file=sys.stderr)
        if attempt < MAX_RETRIES - 1:
            time.sleep(5)

    return None


def fallback_visual_plan(script: dict, illustration_budget: int) -> dict:
    """Deterministic plan so a director outage degrades instead of failing.

    Still varies layout by beat content, so the fallback is not a single template
    repeated down the video.
    """
    beats = [b for b in script.get("suggested_visual_beats", []) if isinstance(b, dict)]

    shots: list[dict[str, Any]] = [{
        "beat_name": HOOK_BEAT,
        "layout": "hero_statement",
        "type_scale": "xl",
        "text_anchor": "center",
        "transition_in": "cut",
        "headline": _clean_str(script.get("hook", ""), 80),
    }]

    for i, beat in enumerate(beats):
        narration = str(beat.get("narration_text", ""))
        figure = re.search(r"(\$?\d[\d,.]*\s*(?:%|million|billion|trillion|k)?)", narration)
        if figure and i % 2 == 0:
            layout = "data_readout"
            payload: dict[str, Any] = {"data": {"value": figure.group(1).strip()[:24]}}
        else:
            layout = "hero_statement"
            payload = {}
        shots.append({
            "beat_name": str(beat.get("name", f"beat_{i + 1:02d}")),
            "layout": layout,
            "type_scale": "lg",
            "text_anchor": "top",
            "transition_in": "rule_wipe",
            "headline": _clean_str(narration, 80),
            **payload,
        })

    shots.append({
        "beat_name": OUTRO_BEAT,
        "layout": "outro_brand",
        "type_scale": "lg",
        "text_anchor": "center",
        "transition_in": "fade",
        "headline": _clean_str(script.get("cta", ""), 80),
    })

    return {
        "concept": "Fallback editorial explainer (art director unavailable)",
        "palette": {
            "ground": BRAND_GROUND,
            "ink": BRAND_INK,
            "accent": SEMANTIC_ACCENTS["neutral"],
            "accent_role": "neutral",
            "accent_rationale": "Art director unavailable; defaulting to monochrome.",
        },
        "illustration_style": DEFAULT_STYLE_CONTRACT,
        "motion_language": "precise",
        "shots": shots,
    }


def validate_plan(plan: dict, schema: dict) -> bool:
    try:
        import jsonschema
        jsonschema.validate(instance=plan, schema=schema)
        return True
    except ImportError:
        return True
    except Exception as e:
        print(f"  [warn] Schema validation failed: {e}", file=sys.stderr)
        return False


def main() -> int:
    parser = argparse.ArgumentParser(description="ArtDirector Agent")
    parser.add_argument("--script-json", help="Path to ScriptOutput JSON")
    parser.add_argument("--research-json", help="Path to ResearchOutput JSON (optional but recommended)")
    parser.add_argument("--stdin", action="store_true", help="Read ScriptOutput from stdin")
    parser.add_argument(
        "--illustrations",
        type=int,
        default=int(os.environ.get("COLONYV_ILLUSTRATION_BUDGET", "4")),
        help="Maximum generated illustrations for this video (cost control)",
    )
    parser.add_argument(
        "--allow-fallback",
        action="store_true",
        help="Emit the deterministic plan instead of failing when the director errors",
    )
    args = parser.parse_args()

    if args.stdin:
        script = json.load(sys.stdin)
    elif args.script_json:
        with open(args.script_json) as f:
            script = json.load(f)
    else:
        print("Error: provide --script-json or --stdin", file=sys.stderr)
        return 2

    research: dict = {}
    if args.research_json:
        try:
            with open(args.research_json) as f:
                research = json.load(f)
        except (OSError, json.JSONDecodeError) as e:
            print(f"  [warn] Could not read research JSON: {e}", file=sys.stderr)

    budget = max(0, args.illustrations)
    beats = len(script.get("suggested_visual_beats", []) or [])
    print(f"[1/2] Directing {beats + 2} shots (illustration budget: {budget})...")

    plan = generate_visual_plan(script, research, illustration_budget=budget)
    if not plan:
        if not args.allow_fallback:
            print("Error: Art direction failed.", file=sys.stderr)
            return 1
        print("  [warn] Falling back to deterministic plan", file=sys.stderr)
        plan = fallback_visual_plan(script, budget)

    if not validate_plan(plan, load_schema()):
        print("Error: VisualPlan failed schema validation.", file=sys.stderr)
        return 1

    illustrated = sum(1 for s in plan["shots"] if s.get("illustration"))
    layouts = [s["layout"] for s in plan["shots"]]
    print("[2/2] Plan ready")
    print(f"  Concept: {plan['concept']}")
    print(f"  Accent:  {plan['palette']['accent']} ({plan['palette']['accent_role']})")
    print(f"  Motion:  {plan['motion_language']}")
    print(f"  Shots:   {len(plan['shots'])} | distinct layouts: {len(set(layouts))}")
    print(f"  Layouts: {' -> '.join(layouts)}")
    print(f"  Illustrations: {illustrated}/{budget}")

    print("=== Visual Plan ===")
    print(json.dumps(plan, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
