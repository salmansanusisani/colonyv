#!/usr/bin/env python3
"""
Analyst Agent - analyzes pipeline output and produces learned signals.

Usage:
    python3 analyst.py --run-dir /path/to/output/run_id
    python3 analyst.py --run-dir /path/to/output/run_id --history /path/to/history.json

Output: AnalystOutput JSON (schema-validated).
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

import jsonschema

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
SCHEMA_PATH = PROJECT_ROOT / "contracts" / "analyst_output.schema.json"

LLM_MODEL_ID = os.environ.get("COLONYV_GEMINI_MODEL", "gemini-3.5-flash")
LLM_MAX_TOKENS = 4000
MAX_RETRIES = 3


def load_schema():
    with open(SCHEMA_PATH) as f:
        return json.load(f)


def collect_run_data(run_dir: Path) -> dict:
    """Collect all data from a pipeline run directory."""
    data = {"run_id": run_dir.name, "stories": []}

    for monitor_file in run_dir.glob("*_monitor.json"):
        story_id = monitor_file.stem.replace("_monitor", "")
        story_data = {"story_id": story_id}

        with open(monitor_file) as f:
            story_data["monitor"] = json.load(f)

        research_file = run_dir / f"{story_id}_research.json"
        if research_file.exists():
            with open(research_file) as f:
                story_data["research"] = json.load(f)

        script_file = run_dir / f"{story_id}_script.json"
        if script_file.exists():
            with open(script_file) as f:
                story_data["script"] = json.load(f)

        video_file = run_dir / f"{story_id}.mp4"
        story_data["rendered"] = video_file.exists()
        story_data["video_size_mb"] = (
            round(video_file.stat().st_size / 1024 / 1024, 1) if video_file.exists() else 0
        )

        data["stories"].append(story_data)

    return data


def analyze_performance(run_data: dict, history: list | None = None) -> dict | None:
    """Use LLM to analyze pipeline performance and produce learned signals."""
    from colonyv_agent.gemini import generate_json

    stories_summary = []
    for s in run_data["stories"]:
        monitor = s.get("monitor", {})
        research = s.get("research", {})
        script = s.get("script", {})
        stories_summary.append({
            "title": monitor.get("title", "Unknown"),
            "relevance": monitor.get("relevance_score", 0),
            "novelty": monitor.get("novelty_score", 0),
            "urgency": monitor.get("urgency_score", 0),
            "confidence": research.get("confidence", "unknown"),
            "num_claims": len(research.get("claims", [])),
            "num_contradictions": len(research.get("contradictions", [])),
            "num_beats": len(script.get("suggested_visual_beats", [])),
            "duration": script.get("estimated_duration", 0),
            "rendered": s.get("rendered", False),
            "video_size_mb": s.get("video_size_mb", 0),
        })

    history_text = ""
    if history:
        history_text = f"\n\nPREVIOUS RUNS ({len(history)} historical runs):"
        for h in history[-5:]:
            history_text += f"\n  Run {h.get('run_id', '?')}: {h.get('stories_analyzed', 0)} stories"
            for sig in h.get("learned_signals", [])[:3]:
                history_text += f"\n    - {sig.get('signal_type')}: {sig.get('description', '')[:80]}"

    prompt = f"""You are a content pipeline analyst. Analyze this pipeline run and produce learned signals.

CURRENT RUN: {run_data['run_id']}
Stories processed: {len(run_data['stories'])}

Story details:
{json.dumps(stories_summary, indent=2)}
{history_text}

Based on this data, produce a JSON object with:

1. learned_signals: array of signals, each with:
   - signal_type: one of "topic_trend", "source_quality", "engagement_pattern", "content_gap", "timing_insight"
   - description: what was learned (NOT raw metrics - interpret them)
   - confidence: "high"/"medium"/"low"
   - actionable: true/false
   - recommended_action: what to do about it

2. recommendations: object with:
   - monitor_adjustments: array of strings (changes to feed selection or scoring)
   - scriptwriter_adjustments: array of strings (changes to script generation)
   - producer_adjustments: array of strings (changes to video rendering)
   - priority_topics: array of strings (topics to prioritize)
   - topics_to_avoid: array of strings (topics to deprioritize)

RULES:
- Do NOT repeat raw metrics. Interpret them into insights.
- Focus on patterns across stories, not individual story stats.
- Be specific and actionable.
- If only 1 story was processed, note that more data is needed for strong signals.

Return ONLY valid JSON (no markdown, no explanation)."""

    for attempt in range(MAX_RETRIES):
        try:
            return generate_json(prompt)

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


def validate_output(data: dict, schema: dict) -> bool:
    try:
        jsonschema.validate(instance=data, schema=schema)
        return True
    except jsonschema.ValidationError as e:
        print(f"  [warn] Schema validation failed: {e.message}", file=sys.stderr)
        return False


def sanitize_analyst_output(analysis: dict, run_id: str, stories_count: int) -> dict:
    if not isinstance(analysis, dict):
        analysis = {}

    valid_signal_types = {"topic_trend", "source_quality", "engagement_pattern", "content_gap", "timing_insight"}
    valid_confidences = {"high", "medium", "low"}

    raw_signals = analysis.get("learned_signals", [])
    if not isinstance(raw_signals, list):
        raw_signals = []

    sanitized_signals = []
    for sig in raw_signals:
        if not isinstance(sig, dict):
            continue
        sig_type = str(sig.get("signal_type", "topic_trend")).lower().replace("-", "_")
        if sig_type not in valid_signal_types:
            sig_type = "topic_trend"

        conf = str(sig.get("confidence", "medium")).lower()
        if conf not in valid_confidences:
            conf = "medium"

        actionable = bool(sig.get("actionable", True))
        desc = str(sig.get("description", "Learned signal from run."))

        sig_obj = {
            "signal_type": sig_type,
            "description": desc,
            "confidence": conf,
            "actionable": actionable,
        }
        if "recommended_action" in sig and sig["recommended_action"]:
            sig_obj["recommended_action"] = str(sig["recommended_action"])

        sanitized_signals.append(sig_obj)

    raw_recs = analysis.get("recommendations", {})
    if not isinstance(raw_recs, dict):
        raw_recs = {}

    def _str_list(val):
        if isinstance(val, list):
            return [str(x) for x in val]
        return [str(val)] if val else []

    sanitized_recs = {
        "monitor_adjustments": _str_list(raw_recs.get("monitor_adjustments")),
        "scriptwriter_adjustments": _str_list(raw_recs.get("scriptwriter_adjustments")),
        "producer_adjustments": _str_list(raw_recs.get("producer_adjustments")),
        "priority_topics": _str_list(raw_recs.get("priority_topics")),
        "topics_to_avoid": _str_list(raw_recs.get("topics_to_avoid")),
    }

    ts = datetime.now().astimezone().isoformat()

    return {
        "run_id": run_id,
        "timestamp": ts,
        "stories_analyzed": stories_count,
        "learned_signals": sanitized_signals,
        "recommendations": sanitized_recs,
    }


def main():
    parser = argparse.ArgumentParser(description="Analyst Agent")
    parser.add_argument("--run-dir", required=True, help="Path to pipeline run output directory")
    parser.add_argument("--history", help="Path to historical analysis JSON file")
    args = parser.parse_args()

    schema = load_schema()
    run_dir = Path(args.run_dir)

    if not run_dir.exists():
        print(f"Error: Run directory not found: {run_dir}", file=sys.stderr)
        sys.exit(1)

    print(f"[1/3] Collecting data from {run_dir.name}...")
    run_data = collect_run_data(run_dir)
    print(f"  Found {len(run_data['stories'])} stories")

    history = None
    if args.history and Path(args.history).exists():
        with open(args.history) as f:
            history = json.load(f)
        print(f"  Loaded {len(history)} historical analyses")

    print(f"[2/3] Analyzing performance...")
    analysis = analyze_performance(run_data, history)

    if not analysis:
        print("  [error] LLM analysis failed.", file=sys.stderr)
        sys.exit(1)

    output = sanitize_analyst_output(analysis, run_dir.name, len(run_data["stories"]))

    print(f"[3/3] Validating...")
    if validate_output(output, schema):
        print(f"  Signals: {len(output['learned_signals'])}")
        for sig in output["learned_signals"]:
            print(f"    [{sig['signal_type']}] {sig['description'][:70]}...")
        print(f"\n{json.dumps(output, indent=2)}")
    else:
        print("  [error] Output failed schema validation.", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
