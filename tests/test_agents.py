"""Unit tests for agents, schema sanitizers, and pipeline components."""
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from agents.research.research import sanitize_research_output, validate_output as validate_research, load_schema as load_research_schema
from agents.scriptwriter.scriptwriter import sanitize_script_output, validate_output as validate_script, load_schema as load_script_schema
from agents.analyst.analyst import sanitize_analyst_output, validate_output as validate_analyst, load_schema as load_analyst_schema
from agents.pipeline import get_python_exec as pipeline_get_py
from dashboard.app import get_python_exec as dashboard_get_py


def test_python_exec_resolution():
    py1 = pipeline_get_py()
    py2 = dashboard_get_py()
    assert py1 == py2
    assert isinstance(py1, str)
    assert len(py1) > 0


def test_research_sanitizer():
    schema = load_research_schema()
    analysis_raw = {
        "summary": "Raw summary text",
        "claims": ["Unstructured string claim", {"text": "Valid claim", "source_index": "0", "verified": True}],
        "contradictions": [{"issue": "Date mismatch", "likely_explanation": "Typo", "resolution_for_script": "Use primary"}],
        "confidence": "HIGH",
        "publication_date": "2026-08-23",
    }
    extracted = [{"outlet": "TechCrunch", "url": "https://techcrunch.com/article", "content": "body", "strategy": "article_tag"}]
    sources = [{"title": "TechCrunch", "url": "https://techcrunch.com/article"}]

    sanitized = sanitize_research_output(analysis_raw, "story_123", extracted, sources)
    assert sanitized["story_id"] == "story_123"
    assert sanitized["confidence"] == "high"
    assert len(sanitized["claims"]) == 2
    assert sanitized["claims"][0]["verified"] is False
    assert sanitized["claims"][1]["verified"] is True
    assert validate_research(sanitized, schema) is True


def test_scriptwriter_sanitizer():
    schema = load_script_schema()
    raw_script = {
        "hook": "Check this out!",
        "body": "Beat 1 text | Beat 2 text",
        "cta": "Subscribe for more",
        "estimated_duration": "40",
        "format": "stat-heavy explainer",
        "claims_used": "Claim A",
        "suggested_visual_beats": [
            {"name": "beat_01", "narration_text": "Beat 1 text", "beat_type": "stat-reveal"},
            {"narration_text": "Beat 2 text", "beat_type": "invalid_type"}
        ]
    }

    sanitized = sanitize_script_output(raw_script)
    assert sanitized["hook"] == "Check this out!"
    assert sanitized["estimated_duration"] == 40.0
    assert isinstance(sanitized["claims_used"], list)
    assert sanitized["suggested_visual_beats"][0]["beat_type"] == "stat_reveal"
    assert sanitized["suggested_visual_beats"][1]["beat_type"] == "custom"
    assert sanitized["suggested_visual_beats"][1]["name"] == "beat_02"
    assert validate_script(sanitized, schema) is True


def test_analyst_sanitizer():
    schema = load_analyst_schema()
    raw_analyst = {
        "learned_signals": [
            {
                "signal_type": "topic-trend",
                "description": "AI agent news performs well.",
                "confidence": "HIGH",
                "actionable": "true",
            }
        ],
        "recommendations": {
            "priority_topics": ["agents", "llms"],
        }
    }

    sanitized = sanitize_analyst_output(raw_analyst, "run_20260823", 2)
    assert sanitized["run_id"] == "run_20260823"
    assert sanitized["stories_analyzed"] == 2
    assert sanitized["learned_signals"][0]["signal_type"] == "topic_trend"
    assert sanitized["learned_signals"][0]["confidence"] == "high"
    assert sanitized["learned_signals"][0]["actionable"] is True
    assert validate_analyst(sanitized, schema) is True


if __name__ == "__main__":
    for name, func in list(globals().items()):
        if name.startswith("test_") and callable(func):
            try:
                func()
                print(f"  PASS: {name}")
            except Exception as e:
                print(f"  FAIL: {name} - {e}")
    print("Done.")
