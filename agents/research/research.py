#!/usr/bin/env python3
"""
Research Agent - crawls source URLs, extracts content, analyzes via LLM.
Self-healing: if extraction fails, retries with different strategies.

Usage:
    python3 research.py --story-json <monitor_output.json>
    echo '{"story_id":"...","title":"...","sources":[...]}' | python3 research.py --stdin

Output: ResearchOutput JSON (schema-validated).
"""

import argparse
import json
import os
import re
import sys
import time
from urllib.parse import urljoin
from pathlib import Path
from typing import Any

import requests
from bs4 import BeautifulSoup
import jsonschema

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
SCHEMA_PATH = PROJECT_ROOT / "contracts" / "research_output.schema.json"

LLM_MODEL_ID = os.environ.get("COLONY_MODEL_ID", "groq/openai/gpt-oss-120b")
LLM_MAX_TOKENS = 4000
MAX_RETRIES = 3
REQUEST_TIMEOUT = 15

HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}


def load_schema():
    with open(SCHEMA_PATH) as f:
        return json.load(f)


# --- Web scraping with self-healing ---

def fetch_html(url: str) -> str | None:
    for attempt in range(3):
        try:
            resp = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT, allow_redirects=True)
            if resp.status_code == 429:
                wait = 5 * (attempt + 1)
                print(f"  [warn] Rate limited (429), waiting {wait}s...", file=sys.stderr)
                time.sleep(wait)
                continue
            if resp.status_code == 403:
                wait = 3 * (attempt + 1)
                print(f"  [warn] Forbidden (403), waiting {wait}s...", file=sys.stderr)
                time.sleep(wait)
                continue
            resp.raise_for_status()
            return resp.text
        except requests.exceptions.ConnectionError:
            wait = 3 * (attempt + 1)
            print(f"  [warn] Connection error, retrying in {wait}s...", file=sys.stderr)
            time.sleep(wait)
        except requests.exceptions.Timeout:
            wait = 3 * (attempt + 1)
            print(f"  [warn] Timeout, retrying in {wait}s...", file=sys.stderr)
            time.sleep(wait)
        except Exception as e:
            print(f"  [warn] Failed to fetch {url}: {e}", file=sys.stderr)
            return None
    print(f"  [warn] Failed to fetch {url} after 3 attempts", file=sys.stderr)
    return None


def extract_editorial_assets(html: str, source_url: str) -> list[dict]:
    """Collect article-provided images with source metadata for later validation."""
    soup = BeautifulSoup(html, "html.parser")
    found = []
    seen = set()
    candidates = []
    for tag in soup.find_all("meta"):
        prop = str(tag.get("property", "")).lower()
        name = str(tag.get("name", "")).lower()
        if prop in {"og:image", "og:image:url"} or name in {"twitter:image", "twitter:image:src"}:
            candidates.append((tag.get("content", ""), "article_image"))
    for image in soup.find_all("img")[:20]:
        candidates.append((image.get("src", ""), "article_image"))
    for raw_url, asset_type in candidates:
        image_url = urljoin(source_url, str(raw_url).strip())
        if not image_url.startswith(("http://", "https://")) or image_url in seen:
            continue
        seen.add(image_url)
        found.append({
            "url": image_url,
            "source_url": source_url,
            "asset_type": asset_type,
            "subject": "article lead image",
            "credit": "Source article",
            "license_note": "Review source terms before publication",
        })
    return found[:6]


EXTRACTION_STRATEGIES = [
    # Strategy 1: article tag
    lambda soup: "\n".join(p.get_text(strip=True) for p in soup.find_all("article")[:1]),
    # Strategy 2: main content area
    lambda soup: "\n".join(p.get_text(strip=True) for p in soup.find_all(["main", "section"])[:1]),
    # Strategy 3: largest div by text length
    lambda soup: max(
        (div.get_text(separator="\n", strip=True) for div in soup.find_all("div")),
        key=len,
        default=""
    ),
    # Strategy 4: all paragraphs
    lambda soup: "\n".join(p.get_text(strip=True) for p in soup.find_all("p")),
    # Strategy 5: body text (fallback)
    lambda soup: soup.get_text(separator="\n", strip=True)[:5000],
]


def extract_content(html: str, strategy_index: int = 0) -> tuple[str, int]:
    """Try extraction strategy. Returns (content, strategy_used)."""
    soup = BeautifulSoup(html, "html.parser")

    # Remove noise
    for tag in soup.find_all(["script", "style", "nav", "header", "footer", "aside", "iframe"]):
        tag.decompose()

    for i in range(strategy_index, len(EXTRACTION_STRATEGIES)):
        try:
            content = EXTRACTION_STRATEGIES[i](soup)
            content = re.sub(r'\n{3,}', '\n\n', content).strip()
            if len(content) > 100:
                return content[:4000], i
        except Exception:
            continue

    return "", len(EXTRACTION_STRATEGIES)


def self_healing_extract(url: str) -> dict[str, Any]:
    """Fetch + extract with self-healing. Returns dict with content, strategy, success."""
    html = fetch_html(url)
    if not html:
        return {"content": "", "strategy": "failed", "success": False, "error": "fetch_failed"}

    content, strategy_idx = extract_content(html, 0)
    assets = extract_editorial_assets(html, url)
    strategy_names = ["article_tag", "main_section", "largest_div", "all_paragraphs", "body_text"]

    if content:
        return {
            "content": content,
            "strategy": strategy_names[strategy_idx],
            "success": True,
            "attempts": strategy_idx + 1,
            "assets": assets,
        }

    # All strategies failed - try fetching raw and sending to LLM
    soup = BeautifulSoup(html, "html.parser")
    raw_text = soup.get_text(separator="\n", strip=True)[:3000]
    if len(raw_text) > 100:
        return {
            "content": raw_text,
            "strategy": "raw_fallback",
            "success": True,
            "attempts": len(EXTRACTION_STRATEGIES) + 1,
            "assets": assets,
        }

    return {"content": "", "strategy": "all_failed", "success": False, "error": "no_content", "assets": assets}


# --- LLM analysis ---

def analyze_sources(story: dict, extracted_articles: list[dict], api_key: str) -> dict | None:
    from strands import Agent
    from strands.models.litellm import LiteLLMModel

    model = LiteLLMModel(
        client_args={"api_key": api_key},
        model_id=LLM_MODEL_ID,
        params={"max_tokens": LLM_MAX_TOKENS},
    )

    sources_text = ""
    for i, article in enumerate(extracted_articles):
        sources_text += f"\n--- Source {i} ({article['outlet']}) ---\n"
        sources_text += f"URL: {article['url']}\n"
        sources_text += f"Extraction strategy: {article['strategy']}\n"
        sources_text += f"Content:\n{article['content'][:2000]}\n"

    prompt = f"""You are a research analyst for a video news channel.

Story: {story.get('title', 'Unknown')}
Story ID: {story.get('story_id', 'unknown')}

Sources analyzed:
{sources_text}

Based on these sources, produce a JSON object with:
1. summary: 2-3 sentence summary of the story
2. claims: array of factual claims, each with:
   - text: the claim
   - source_index: which source (0-based) supports it
   - verified: true if confirmed by 2+ sources
3. contradictions: array of contradictions between sources (empty if none), each with:
   - issue: what contradicts
   - likely_explanation: why
   - resolution_for_script: how scriptwriter should handle
4. confidence: "high" / "medium" / "low"
5. recommended_angle: suggested narrative angle for video
6. what_is_confirmed: array of confirmed facts
7. what_is_uncertain: array of unverified facts
8. publication_date: YYYY-MM-DD of primary source
9. primary_source: URL of primary source
10. secondary_sources: array of secondary source URLs
11. entities: array of named people, companies, products, and locations
12. editorial_assets: array of relevant image objects using source URLs when available. Each object must contain url, source_url, asset_type, subject, credit, and license_note.

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

            return json.loads(text)

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


def sanitize_research_output(analysis: dict, story_id: str, extracted: list[dict], sources: list[dict]) -> dict:
    raw_claims = analysis.get("claims", [])
    sanitized_claims = []
    for c in raw_claims:
        if isinstance(c, dict):
            sanitized_claims.append({
                "text": str(c.get("text", "")),
                "source_index": int(c.get("source_index", 0)),
                "verified": bool(c.get("verified", False)),
            })
        elif isinstance(c, str):
            sanitized_claims.append({
                "text": c,
                "source_index": 0,
                "verified": False,
            })

    raw_contradictions = analysis.get("contradictions", [])
    sanitized_contradictions = []
    for c in raw_contradictions:
        if isinstance(c, dict):
            sanitized_contradictions.append({
                "issue": str(c.get("issue", "")),
                "likely_explanation": str(c.get("likely_explanation", "")),
                "resolution_for_script": str(c.get("resolution_for_script", "")),
            })

    conf = str(analysis.get("confidence", "medium")).lower()
    if conf not in ["high", "medium", "low"]:
        conf = "medium"

    pub_date = str(analysis.get("publication_date", "2026-01-01"))
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", pub_date):
        pub_date = "2026-01-01"

    primary_url = analysis.get("primary_source")
    if not primary_url and sources and isinstance(sources[0], dict):
        primary_url = sources[0].get("url", "")
    if not primary_url:
        primary_url = "https://example.com"

    return {
        "story_id": story_id,
        "summary": str(analysis.get("summary", "")),
        "claims": sanitized_claims,
        "sources": [
            {
                "outlet": str(e.get("outlet", "Unknown")),
                "date": pub_date,
                "role": "primary" if i == 0 else "secondary",
                "url": str(e.get("url", "https://example.com")),
            }
            for i, e in enumerate(extracted)
        ],
        "contradictions": sanitized_contradictions,
        "confidence": conf,
        "recommended_angle": str(analysis.get("recommended_angle", "")),
        "what_is_confirmed": [str(x) for x in analysis.get("what_is_confirmed", [])],
        "what_is_uncertain": [str(x) for x in analysis.get("what_is_uncertain", [])],
        "publication_date": pub_date,
        "primary_source": str(primary_url),
        "secondary_sources": [str(x) for x in analysis.get("secondary_sources", [])],
        "entities": [str(x) for x in analysis.get("entities", []) if x],
        "editorial_assets": [
            {key: value for key, value in asset.items() if value not in (None, "")}
            for asset in analysis.get("editorial_assets", [])
            if isinstance(asset, dict) and asset.get("url")
        ],
    }


def main():
    parser = argparse.ArgumentParser(description="Research Agent")
    parser.add_argument("--story-json", type=str, help="Path to MonitorOutput JSON file")
    parser.add_argument("--stdin", action="store_true", help="Read MonitorOutput from stdin")
    parser.add_argument("--api-key", type=str, default=os.environ.get("COLONY_API_KEY") or os.environ.get("GROQ_API_KEY", ""))
    args = parser.parse_args()

    if not args.api_key:
        print("Error: No API key. Set GROQ_API_KEY or pass --api-key.", file=sys.stderr)
        sys.exit(1)

    schema = load_schema()

    # Load story
    if args.stdin:
        story = json.load(sys.stdin)
    elif args.story_json:
        with open(args.story_json) as f:
            story = json.load(f)
    else:
        print("Error: Provide --story-json or --stdin", file=sys.stderr)
        sys.exit(1)

    story_id = story.get("story_id", "unknown")
    title = story.get("title", "Unknown")
    sources = story.get("sources", [])

    print(f"[1/3] Researching: {title[:60]}")
    print(f"  Story ID: {story_id}")
    print(f"  Sources: {len(sources)}")

    # Extract content from each source
    print(f"[2/3] Extracting content from {len(sources)} sources...")
    extracted = []
    for i, src in enumerate(sources):
        url = src.get("url", "")
        outlet = src.get("title", "Unknown")
        print(f"  Source {i}: {outlet[:50]}...")

        result = self_healing_extract(url)
        if result["success"]:
            print(f"    OK ({result['strategy']}, {result['attempts']} attempts, {len(result['content'])} chars)")
            extracted.append({
                "url": url,
                "outlet": src.get("title", "Unknown"),
                "content": result["content"],
                "strategy": result["strategy"],
                "assets": result.get("assets", []),
            })
        else:
            print(f"    FAILED ({result['error']})")

    if not extracted:
        print("  [warn] No content extracted from any source, using title/summary fallback", file=sys.stderr)
        # Graceful degradation: use the title and summary from monitor data
        extracted = [{
            "url": sources[0].get("url", "") if sources else "",
            "outlet": sources[0].get("title", "Unknown") if sources else "Unknown",
            "content": f"Title: {title}\nSummary: {story.get('summary', title)}",
            "strategy": "title_fallback",
        }]

    # Analyze via LLM
    print(f"[3/3] Analyzing {len(extracted)} sources via LLM...")
    analysis = analyze_sources(story, extracted, args.api_key)

    if not analysis:
        print("  [error] LLM analysis failed.", file=sys.stderr)
        sys.exit(1)

    # Build output
    output = sanitize_research_output(analysis, story_id, extracted, sources)
    extracted_assets = [asset for article in extracted for asset in article.get("assets", [])]
    output["editorial_assets"] = output.get("editorial_assets", []) + extracted_assets
    output["editorial_assets"] = list({asset["url"]: asset for asset in output["editorial_assets"]}.values())[:12]

    # Validate
    if validate_output(output, schema):
        print(f"\n  Confidence: {output['confidence']}")
        print(f"  Claims: {len(output['claims'])}")
        print(f"  Contradictions: {len(output['contradictions'])}")
        print(f"\n{json.dumps(output, indent=2)}")
    else:
        print("  [error] Output failed schema validation.", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
