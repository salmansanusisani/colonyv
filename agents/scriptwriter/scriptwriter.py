#!/usr/bin/env python3
"""
ScriptWriter Agent - converts ResearchOutput into beat-split video script.

Usage:
    python3 scriptwriter.py --research-json <research_output.json>
    echo '{"story_id":"...","summary":"...",...}' | python3 scriptwriter.py --stdin

Output: ScriptOutput JSON (schema-validated).
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path

import jsonschema

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
SCHEMA_PATH = PROJECT_ROOT / "contracts" / "script_output.schema.json"

LLM_MODEL_ID = "groq/openai/gpt-oss-120b"
LLM_MAX_TOKENS = 4000
MAX_RETRIES = 3


def load_schema():
    with open(SCHEMA_PATH) as f:
        return json.load(f)


def sanitize_script_output(script: dict) -> dict:
    if not isinstance(script, dict):
        script = {}

    beats = script.get("suggested_visual_beats", [])
    if not isinstance(beats, list):
        beats = []

    valid_beat_types = {"stat_reveal", "diagram", "kinetic_text", "image", "custom"}
    sanitized_beats = []
    for i, b in enumerate(beats):
        if not isinstance(b, dict):
            b = {}
        name = str(b.get("name") or f"beat_{i+1:02d}")
        text = str(b.get("narration_text", ""))
        beat_type = str(b.get("beat_type", "custom")).replace("-", "_")
        if beat_type not in valid_beat_types:
            beat_type = "custom"

        beat_obj = {
            "name": name,
            "narration_text": text,
            "beat_type": beat_type,
        }
        if "image_url" in b and isinstance(b["image_url"], str) and b["image_url"].startswith("http"):
            beat_obj["image_url"] = b["image_url"]
        sanitized_beats.append(beat_obj)

    if not sanitized_beats:
        sanitized_beats = [{
            "name": "beat_01_main",
            "narration_text": str(script.get("body", "")),
            "beat_type": "custom",
        }]

    claims_used = script.get("claims_used", [])
    if not isinstance(claims_used, list):
        claims_used = [str(claims_used)] if claims_used else []
    claims_not_used = script.get("claims_not_used", [])
    if not isinstance(claims_not_used, list):
        claims_not_used = [str(claims_not_used)] if claims_not_used else []

    try:
        duration = float(script.get("estimated_duration", 35))
    except (ValueError, TypeError):
        duration = 35.0

    return {
        "hook": str(script.get("hook", "")),
        "body": str(script.get("body", "")),
        "cta": str(script.get("cta", "")),
        "estimated_duration": duration,
        "format": str(script.get("format", "stat-heavy explainer")),
        "claims_used": [str(c) for c in claims_used],
        "claims_not_used": [str(c) for c in claims_not_used],
        "suggested_visual_beats": sanitized_beats,
    }


def generate_script(research: dict, api_key: str) -> dict | None:
    from strands import Agent
    from strands.models.litellm import LiteLLMModel

    model = LiteLLMModel(
        client_args={"api_key": api_key},
        model_id=LLM_MODEL_ID,
        params={"max_tokens": LLM_MAX_TOKENS},
    )

    summary = research.get("summary", "")
    claims = research.get("claims", [])
    contradictions = research.get("contradictions", [])
    confidence = research.get("confidence", "medium")
    angle = research.get("recommended_angle", "")
    confirmed = research.get("what_is_confirmed", [])
    uncertain = research.get("what_is_uncertain", [])

    claims_text = "\n".join(
        f"- {c.get('text', '')} (verified: {c.get('verified', False)})"
        for c in claims if isinstance(c, dict)
    )
    contradictions_text = "\n".join(
        f"- {c.get('issue', '')}: {c.get('resolution_for_script', '')}"
        for c in contradictions if isinstance(c, dict)
    ) if contradictions else "None"

    prompt = f"""You are a video scriptwriter for a tech/AI news channel. Write a script for a 30-45 second portrait video (1080x1920).

STORY:
{summary}

RESEARCHED CLAIMS:
{claims_text}

CONTRADICTIONS:
{contradictions_text}

CONFIDENCE: {confidence}
RECOMMENDED ANGLE: {angle}
CONFIRMED FACTS: {', '.join(confirmed)}
UNCERTAIN FACTS: {', '.join(uncertain)}

INSTRUCTIONS:
Write a script with exactly these parts:
1. HOOK (1-2 sentences): Attention-grabbing opener. Max 20 words.
2. BODY (3-5 beats): Each beat covers one key point. Each beat is 2-4 sentences. Total body 120-200 words.
3. CTA (1 sentence): Subscribe/follow call-to-action. Max 15 words.

CRITICAL RULES:
- Total script word count: 80-120 words
- Use US English, no markdown, no special characters
- Do NOT hallucinate stats. Only use claims from the research above.
- The body beats will be rendered as separate visual scenes
- Keep total video under 60 seconds: 3-4 seconds hook, 20-30 seconds body, 5 seconds CTA
- Max 3 visual beats in the body

Return a JSON object with:
- hook: string (opening line)
- body: string (full body text, beats separated by " | " delimiter)
- cta: string (closing call-to-action)
- estimated_duration: number (total seconds, 25-40)
- format: string (e.g. "stat-heavy explainer", "mechanism-diagram explainer", "news brief")
- claims_used: array of strings (which claims from research are used)
- claims_not_used: array of strings (which claims were excluded)
- suggested_visual_beats: array of objects, each with:
  - name: string (e.g. "beat_01_overview")
  - narration_text: string (the narration for this beat)
  - beat_type: one of "stat_reveal", "diagram", "kinetic_text", "image", "custom"

Return ONLY valid JSON (no markdown, no explanation)."""

    for attempt in range(MAX_RETRIES):
        try:
            agent = Agent(model=model, tools=[])
            result = agent(prompt)
            text = str(result).strip()

            if "```" in text:
                parts = text.split("```")
                text = parts[1]
                if text.startswith("json"):
                    text = text[4:]
                text = text.strip()

            raw_dict = json.loads(text)
            return sanitize_script_output(raw_dict)

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


def count_words(text: str) -> int:
    return len(text.split())


def main():
    parser = argparse.ArgumentParser(description="ScriptWriter Agent")
    parser.add_argument("--research-json", type=str, help="Path to ResearchOutput JSON file")
    parser.add_argument("--stdin", action="store_true", help="Read ResearchOutput from stdin")
    parser.add_argument("--api-key", type=str, default=os.environ.get("GROQ_API_KEY", ""))
    args = parser.parse_args()

    if not args.api_key:
        print("Error: No API key. Set GROQ_API_KEY or pass --api-key.", file=sys.stderr)
        sys.exit(1)

    schema = load_schema()

    if args.stdin:
        research = json.load(sys.stdin)
    elif args.research_json:
        with open(args.research_json) as f:
            research = json.load(f)
    else:
        print("Error: Provide --research-json or --stdin", file=sys.stderr)
        sys.exit(1)

    story_id = research.get("story_id", "unknown")
    title = research.get("summary", "Unknown")[:60]

    print(f"[1/2] Generating script for: {title}...")
    script = generate_script(research, args.api_key)

    if not script:
        print("  [error] LLM script generation failed.", file=sys.stderr)
        sys.exit(1)

    # Count words
    hook_words = count_words(script.get("hook", ""))
    body_words = count_words(script.get("body", ""))
    cta_words = count_words(script.get("cta", ""))
    total = hook_words + body_words + cta_words

    beats = script.get("suggested_visual_beats", [])

    print(f"[2/2] Validating...")
    print(f"  Hook: {hook_words} words")
    print(f"  Body: {body_words} words")
    print(f"  CTA: {cta_words} words")
    print(f"  Total: {total} words (target: 150-250)")
    print(f"  Beats: {len(beats)}")
    print(f"  Format: {script.get('format', 'N/A')}")
    print(f"  Duration: {script.get('estimated_duration', 'N/A')}s")

    if validate_output(script, schema):
        print(f"\n{json.dumps(script, indent=2)}")
    else:
        print("  [error] Output failed schema validation.", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
