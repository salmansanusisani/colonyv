"""Tests for the Art Director agent and the illustration engine.

These cover the failure modes that actually broke the visual system in practice:
identifier mangling during sanitisation, the model answering in its own design
vocabulary rather than our enum tokens, illustrations being requested for layouts
that cannot display them, and budget enforcement.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _load(name: str, relative: str):
    spec = importlib.util.spec_from_file_location(name, PROJECT_ROOT / relative)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


artdirector = _load("artdirector", "agents/artdirector/artdirector.py")
illustrate = _load("illustrate", "producer/illustrate.py")


HOOK = artdirector.HOOK_BEAT
OUTRO = artdirector.OUTRO_BEAT


def _script(beats=("beat_01_alpha", "beat_02_beta")):
    return {
        "hook": "A hook line.",
        "body": "Body.",
        "cta": "Subscribe for more.",
        "estimated_duration": 30,
        "format": "news brief",
        "claims_used": [],
        "suggested_visual_beats": [
            {"name": name, "narration_text": f"Narration for {name}."} for name in beats
        ],
    }


# --------------------------------------------------------------------------
# Contract
# --------------------------------------------------------------------------

def test_visual_plan_schema_exists_and_is_valid_json_schema():
    schema = json.loads((PROJECT_ROOT / "contracts" / "visual_plan.schema.json").read_text())
    assert schema["title"] == "VisualPlan"
    assert "shots" in schema["required"]


def test_fallback_plan_validates_against_schema():
    jsonschema = pytest.importorskip("jsonschema")
    schema = json.loads((PROJECT_ROOT / "contracts" / "visual_plan.schema.json").read_text())
    plan = artdirector.fallback_visual_plan(_script(), 4)
    jsonschema.validate(instance=plan, schema=schema)


# --------------------------------------------------------------------------
# Sanitisation
# --------------------------------------------------------------------------

def test_beat_identifiers_survive_sanitisation():
    """Underscores must not be stripped from beat names.

    Regression test: treating '_' as a markdown character turned '__hook__' into
    'hook' and 'beat_01_alpha' into 'beat01alpha', so no shot ever matched its
    narration unit and every shot was silently replaced by a default.
    """
    raw = {
        "concept": "c",
        "palette": {"accent_role": "alert"},
        "illustration_style": "s" * 120,
        "shots": [
            {"beat_name": HOOK, "layout": "hero_statement", "headline": "Hook headline"},
            {"beat_name": "beat_01_alpha", "layout": "data_readout",
             "headline": "Alpha", "data": {"value": "42"}},
            {"beat_name": "beat_02_beta", "layout": "node_flow", "headline": "Beta",
             "nodes": [{"label": "One"}, {"label": "Two"}]},
            {"beat_name": OUTRO, "layout": "outro_brand", "headline": "Sub"},
        ],
    }
    plan = artdirector.sanitize_visual_plan(
        raw, ["beat_01_alpha", "beat_02_beta"], illustration_budget=4
    )
    assert plan is not None
    assert [s["beat_name"] for s in plan["shots"]] == [
        HOOK, "beat_01_alpha", "beat_02_beta", OUTRO
    ]
    # The director's authored copy survived rather than being defaulted away.
    assert plan["shots"][0]["headline"] == "Hook headline"
    assert plan["shots"][1]["layout"] == "data_readout"
    assert plan["shots"][2]["layout"] == "node_flow"


@pytest.mark.parametrize(
    "given,expected",
    [
        ("large", "lg"),
        ("medium", "md"),
        ("x_large", "xl"),
    ],
)
def test_type_scale_aliases(given, expected):
    shot = artdirector._sanitize_shot(
        {"beat_name": "b", "layout": "hero_statement", "type_scale": given}, 0, "b"
    )
    assert shot["type_scale"] == expected


@pytest.mark.parametrize(
    "given,expected",
    [("bottom_center", "bottom"), ("top_left", "top"), ("middle", "center")],
)
def test_text_anchor_aliases(given, expected):
    shot = artdirector._sanitize_shot(
        {"beat_name": "b", "layout": "hero_statement", "text_anchor": given}, 0, "b"
    )
    assert shot["text_anchor"] == expected


@pytest.mark.parametrize(
    "given,expected", [("slide_up", "slide"), ("fade_in", "fade"), ("zoom_in", "cut")]
)
def test_transition_aliases(given, expected):
    shot = artdirector._sanitize_shot(
        {"beat_name": "b", "layout": "hero_statement", "transition_in": given}, 0, "b"
    )
    assert shot["transition_in"] == expected


def test_semantic_roles_own_their_hue():
    """A semantic role may not be recoloured, or the visual grammar breaks."""
    palette = artdirector._sanitize_palette(
        {"accent_role": "verified", "accent": "#123456"}
    )
    assert palette["accent"] == artdirector.SEMANTIC_ACCENTS["verified"]

    palette = artdirector._sanitize_palette({"accent_role": "alert", "accent": "#123456"})
    assert palette["accent"] == artdirector.SEMANTIC_ACCENTS["alert"]

    # 'topic' is the one role that may introduce its own hue.
    palette = artdirector._sanitize_palette({"accent_role": "topic", "accent": "#123456"})
    assert palette["accent"] == "#123456"


def test_ground_and_ink_are_brand_constants():
    palette = artdirector._sanitize_palette(
        {"accent_role": "neutral", "ground": "#FF0000", "ink": "#00FF00"}
    )
    # The director is allowed to state them, but they are validated hex; the
    # important guarantee is that omitting them yields the brand values.
    palette = artdirector._sanitize_palette({"accent_role": "neutral"})
    assert palette["ground"] == artdirector.BRAND_GROUND
    assert palette["ink"] == artdirector.BRAND_INK


# --------------------------------------------------------------------------
# Layout repair
# --------------------------------------------------------------------------

def test_data_layout_without_data_falls_back():
    shot = artdirector._sanitize_shot(
        {"beat_name": "b", "layout": "data_readout"}, 0, "b"
    )
    assert shot["layout"] == "hero_statement"


def test_node_layout_with_one_node_falls_back():
    shot = artdirector._sanitize_shot(
        {"beat_name": "b", "layout": "node_flow", "nodes": [{"label": "only"}]}, 0, "b"
    )
    assert shot["layout"] == "hero_statement"


def test_illustration_layout_without_illustration_falls_back():
    shot = artdirector._sanitize_shot(
        {"beat_name": "b", "layout": "illustration_full"}, 0, "b"
    )
    assert shot["layout"] == "hero_statement"


def test_illustration_dropped_for_layouts_that_cannot_display_it():
    """Art on a diagram layout is money spent on a plate nothing will render."""
    for layout, payload in (
        ("node_flow", {"nodes": [{"label": "a"}, {"label": "b"}]}),
        ("compare_two_up", {"nodes": [{"label": "a"}, {"label": "b"}]}),
        ("timeline_rail", {"events": [{"label": "a"}, {"label": "b"}]}),
        ("hero_statement", {}),
    ):
        shot = artdirector._sanitize_shot(
            {
                "beat_name": "b",
                "layout": layout,
                "illustration": {"prompt": "A concrete visual metaphor drawn flat."},
                **payload,
            },
            0,
            "b",
        )
        assert shot["layout"] == layout
        assert "illustration" not in shot, f"{layout} kept an unusable illustration"


def test_illustration_kept_for_art_layouts():
    shot = artdirector._sanitize_shot(
        {
            "beat_name": "b",
            "layout": "illustration_top",
            "illustration": {"prompt": "A concrete visual metaphor drawn flat."},
        },
        0,
        "b",
    )
    assert shot["illustration"]["prompt"]


# --------------------------------------------------------------------------
# Budget
# --------------------------------------------------------------------------

def test_illustration_budget_keeps_highest_priority():
    shots = [
        {"beat_name": "a", "layout": "illustration_top",
         "illustration": {"prompt": "p", "priority": 4}},
        {"beat_name": "b", "layout": "illustration_top",
         "illustration": {"prompt": "p", "priority": 1}},
        {"beat_name": "c", "layout": "illustration_top",
         "illustration": {"prompt": "p", "priority": 2}},
    ]
    artdirector._apply_illustration_budget(shots, 2)
    kept = [s["beat_name"] for s in shots if s.get("illustration")]
    assert kept == ["b", "c"]
    # The shot that lost its art must not keep an art-only layout.
    assert shots[0]["layout"] == "hero_statement"


def test_zero_budget_removes_all_illustrations():
    shots = [
        {"beat_name": "a", "layout": "illustration_full",
         "illustration": {"prompt": "p", "priority": 1}},
    ]
    artdirector._apply_illustration_budget(shots, 0)
    assert "illustration" not in shots[0]
    assert shots[0]["layout"] == "hero_statement"


# --------------------------------------------------------------------------
# Missing / extra shots
# --------------------------------------------------------------------------

def test_missing_shots_are_synthesised_for_every_narration_unit():
    """Every narration unit needs exactly one shot or audio desynchronises."""
    raw = {
        "concept": "c",
        "palette": {"accent_role": "neutral"},
        "illustration_style": "s" * 120,
        "shots": [{"beat_name": HOOK, "layout": "hero_statement"}],
    }
    plan = artdirector.sanitize_visual_plan(
        raw, ["beat_01_alpha", "beat_02_beta"], illustration_budget=0
    )
    assert [s["beat_name"] for s in plan["shots"]] == [
        HOOK, "beat_01_alpha", "beat_02_beta", OUTRO
    ]


def test_outro_is_always_brand_layout():
    raw = {
        "concept": "c",
        "palette": {"accent_role": "neutral"},
        "illustration_style": "s" * 120,
        "shots": [
            {"beat_name": HOOK, "layout": "hero_statement"},
            {"beat_name": OUTRO, "layout": "data_readout", "data": {"value": "9"}},
        ],
    }
    plan = artdirector.sanitize_visual_plan(raw, [], illustration_budget=0)
    assert plan["shots"][-1]["layout"] == "outro_brand"


def test_duplicate_beat_names_do_not_collide():
    raw = {
        "concept": "c",
        "palette": {"accent_role": "neutral"},
        "illustration_style": "s" * 120,
        "shots": [
            {"beat_name": "beat_01_alpha", "layout": "hero_statement", "headline": "first"},
            {"beat_name": "beat_01_alpha", "layout": "quote_block", "headline": "second"},
        ],
    }
    plan = artdirector.sanitize_visual_plan(raw, ["beat_01_alpha"], illustration_budget=0)
    matching = [s for s in plan["shots"] if s["beat_name"] == "beat_01_alpha"]
    assert len(matching) == 1
    assert matching[0]["headline"] == "first"


# --------------------------------------------------------------------------
# Illustration engine
# --------------------------------------------------------------------------

def test_aspect_ratio_is_chosen_per_layout():
    """A plate must be generated at the shape of the region that will show it."""
    assert illustrate.aspect_for_layout("illustration_full") == "9:16"
    assert illustrate.aspect_for_layout("illustration_side") == "3:4"
    assert illustrate.aspect_for_layout("illustration_top") == "1:1"
    assert illustrate.aspect_for_layout("data_readout") == "5:4"
    assert illustrate.aspect_for_layout("unknown_layout") == illustrate.DEFAULT_ASPECT


def test_prompt_asserts_no_text_at_both_ends():
    prompt = illustrate.build_prompt(
        "A stack of sheets.",
        style_contract="S" * 120,
        palette={"accent_role": "neutral", "ground": "#F6F5F1", "ink": "#14150F"},
    )
    assert prompt.startswith(illustrate.NO_TEXT_LEAD)
    assert illustrate.NO_TEXT_CLAUSE in prompt


def test_neutral_role_requests_monochrome():
    prompt = illustrate.build_prompt(
        "Subject.",
        style_contract="S" * 120,
        palette={"accent_role": "neutral", "ground": "#F6F5F1", "ink": "#14150F"},
    )
    assert "strictly monochrome" in prompt


def test_accent_role_requests_single_accent():
    prompt = illustrate.build_prompt(
        "Subject.",
        style_contract="S" * 120,
        palette={
            "accent_role": "alert",
            "accent": "#D14343",
            "ground": "#F6F5F1",
            "ink": "#14150F",
        },
    )
    assert "#D14343" in prompt
    assert "15%" in prompt


def test_cache_key_is_sensitive_to_prompt_and_aspect():
    a = illustrate.cache_key("prompt one", "9:16")
    b = illustrate.cache_key("prompt two", "9:16")
    c = illustrate.cache_key("prompt one", "3:4")
    assert len({a, b, c}) == 3


def test_ground_tone_matching_hits_the_target():
    Image = pytest.importorskip("PIL.Image", reason="Pillow required").Image
    from PIL import Image as PILImage

    # A warm-white plate with a dark mark, as the model tends to produce.
    plate = PILImage.new("RGB", (160, 240), (243, 232, 208))
    for x in range(60, 100):
        for y in range(90, 150):
            plate.putpixel((x, y), (20, 20, 18))

    before = illustrate._sample_ground_tone(plate)
    assert before != (246, 245, 241)

    fixed = illustrate._match_ground(plate, "#F6F5F1")
    after = illustrate._sample_ground_tone(fixed)
    assert after == (246, 245, 241)


def test_ground_matching_ignores_implausible_deltas():
    """A plate whose border is not ground must be left alone, not wrecked."""
    from PIL import Image as PILImage

    dark = PILImage.new("RGB", (80, 120), (10, 10, 10))
    result = illustrate._match_ground(dark, "#F6F5F1")
    assert illustrate._sample_ground_tone(result) == illustrate._sample_ground_tone(dark)


def test_illustrate_plan_drops_art_when_no_client(tmp_path, monkeypatch):
    """A failed illustration downgrades its shot rather than failing the video."""
    monkeypatch.setattr(
        illustrate, "_image_client", lambda: (_ for _ in ()).throw(RuntimeError("no creds"))
    )
    plan = {
        "palette": {"accent_role": "neutral"},
        "illustration_style": "s" * 120,
        "shots": [
            {"beat_name": "a", "layout": "illustration_full",
             "illustration": {"prompt": "p", "priority": 1}},
            {"beat_name": "b", "layout": "hero_statement", "headline": "kept"},
        ],
    }
    summary = illustrate.illustrate_plan(plan, tmp_path, budget=4)
    assert summary["produced"] == 0
    assert "illustration" not in plan["shots"][0]
    assert plan["shots"][0]["layout"] == "hero_statement"
    assert plan["shots"][1]["headline"] == "kept"
