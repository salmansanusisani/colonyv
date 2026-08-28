#!/usr/bin/env python3
"""
Monitor Agent - pulls RSS feeds, scores/ranks stories via LLM.
Uses Groq via LiteLLM for scoring.

Usage:
    python3 monitor.py [--top N] [--seen-file PATH]

Output: JSON array of MonitorOutput objects (schema-validated).
"""

import argparse
import hashlib
import json
import os
import sys
import time
from pathlib import Path

import feedparser
import jsonschema

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
SCHEMA_PATH = PROJECT_ROOT / "contracts" / "monitor_output.schema.json"

DEFAULT_FEEDS = [
    {"url": "https://techcrunch.com/category/artificial-intelligence/feed/", "category": "ai"},
    {"url": "https://www.theverge.com/rss/ai-artificial-intelligence/index.xml", "category": "ai"},
    {"url": "https://feeds.arstechnica.com/arstechnica/technology-lab", "category": "tech"},
    {"url": "https://www.wired.com/feed/rss", "category": "tech"},
    {"url": "https://cointelegraph.com/rss", "category": "crypto"},
    {"url": "https://www.coindesk.com/arc/outboundfeeds/rss/", "category": "crypto"},
    {"url": "https://hnrss.org/best?q=AI+OR+LLM+OR+GPT+OR+crypto+OR+blockchain&count=15", "category": "tech"},
]

FEEDS_PATH = Path(__file__).resolve().parent / "feeds.json"

LLM_MODEL_ID = os.environ.get("COLONYV_GEMINI_MODEL", "gemini-3.5-flash")
LLM_MAX_TOKENS = 4000
MAX_RETRIES = 3


def load_schema():
    with open(SCHEMA_PATH) as f:
        return json.load(f)


def load_seen(path):
    if path.exists():
        with open(path) as f:
            return set(json.load(f))
    return set()

def get_latest_learned_signals() -> str:
    """Read the latest analyst output to inject learned signals into the prompt."""
    try:
        output_dir = PROJECT_ROOT / "output"
        if not output_dir.exists():
            return ""
        dirs = [d for d in output_dir.iterdir() if d.is_dir() and d.name.startswith("202")]
        if not dirs:
            return ""
        latest_dir = sorted(dirs)[-1]
        analyst_file = latest_dir / "analyst_output.json"
        if not analyst_file.exists():
            if len(dirs) > 1:
                latest_dir = sorted(dirs)[-2]
                analyst_file = latest_dir / "analyst_output.json"
        
        if analyst_file.exists():
            with open(analyst_file) as f:
                data = json.load(f)
                adjustments = data.get("recommendations", {}).get("monitor_adjustments", [])
                topics = data.get("recommendations", {}).get("priority_topics", [])
                avoid = data.get("recommendations", {}).get("topics_to_avoid", [])
                
                parts = []
                if adjustments:
                    parts.append("STRATEGIC ADJUSTMENTS: " + ", ".join(adjustments))
                if topics:
                    parts.append("PRIORITY TOPICS: " + ", ".join(topics))
                if avoid:
                    parts.append("TOPICS TO AVOID: " + ", ".join(avoid))
                
                if parts:
                    return "\n\n=== LEARNED SIGNALS FROM PREVIOUS RUNS (CRITICAL TO FOLLOW) ===\n" + "\n".join(parts) + "\n=============================================================\n"
    except Exception as e:
        import sys
        print(f"  [warn] Failed to load learned signals: {e}", file=sys.stderr)
    return ""


def save_seen(path, seen):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(sorted(seen), f, indent=2)


def story_id(title, url):
    raw = f"{title.strip().lower()}|{url.strip().lower()}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def fetch_entries(feeds, max_per_feed=10):
    seen_urls = set()
    entries = []
    for feed_info in feeds:
        url = feed_info["url"]
        if feed_info.get("enabled", True) is False:
            continue
        category = feed_info["category"]
        try:
            d = feedparser.parse(url)
            for entry in d.entries[:max_per_feed]:
                entry_url = entry.get("link", "")
                if entry_url and entry_url not in seen_urls:
                    seen_urls.add(entry_url)
                    entries.append({
                        "title": entry.get("title", "Untitled"),
                        "url": entry_url,
                        "summary": entry.get("summary", "")[:500],
                        "published": entry.get("published", ""),
                        "category": category,
                    })
        except Exception as e:
            print(f"  [warn] Failed to fetch {url}: {e}", file=sys.stderr)
    return entries


def score_all(entries, api_key):
    from colonyv_agent.gemini import generate_json

    entries_text = ""
    for i, e in enumerate(entries):
        entries_text += f"{i+1}. {e['title']}\n"
        entries_text += f"   {e['summary'][:150]}\n"

    learned_signals = get_latest_learned_signals()

    prompt = f"""You are a news story scorer for a tech/AI/crypto video news channel.{learned_signals}

Score these {len(entries)} stories. For EACH story provide:
- relevance (0.0-1.0): fit for tech/AI/crypto audience
- novelty (0.0-1.0): how unique vs routine coverage
- urgency (0.0-1.0): how time-sensitive
- format: one of "stat-heavy explainer", "mechanism-diagram explainer", "breaking news", "deep dive"

Audience topic focus:
{os.environ.get('COLONY_TOPIC_PROMPT', 'General technology, AI, and crypto news')}

Stories:
{entries_text}

Return ONLY a JSON array with exactly {len(entries)} objects. No markdown, no explanation.
Each object must have: i, relevance_score, novelty_score, urgency_score, recommended_format.
Example:
[{{"i": 1, "relevance_score": 0.8, "novelty_score": 0.7, "urgency_score": 0.5, "recommended_format": "deep dive"}}]"""

    for attempt in range(MAX_RETRIES):
        try:
            scores_list = generate_json(prompt)
            if not isinstance(scores_list, list):
                scores_list = [scores_list]

            scored = []
            for s in scores_list:
                if not isinstance(s, dict):
                    continue
                idx = int(s.get("i", 0)) - 1
                if 0 <= idx < len(entries):
                    e = entries[idx]
                    scored.append({
                        "story_id": story_id(e["title"], e["url"]),
                        "title": e["title"],
                        "relevance_score": max(0.0, min(1.0, float(s.get("relevance_score", 0.5)))),
                        "novelty_score": max(0.0, min(1.0, float(s.get("novelty_score", 0.5)))),
                        "urgency_score": max(0.0, min(1.0, float(s.get("urgency_score", 0.5)))),
                        "recommended_format": str(s.get("recommended_format", "stat-heavy explainer")),
                        "sources": [{"url": e["url"], "title": e["title"]}],
                    })
            return scored

        except (json.JSONDecodeError, KeyError, TypeError, ValueError) as e:
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

    print("  [error] All retries exhausted, returning defaults", file=sys.stderr)
    return [{
        "story_id": story_id(e["title"], e["url"]),
        "title": e["title"],
        "relevance_score": 0.5,
        "novelty_score": 0.5,
        "urgency_score": 0.5,
        "recommended_format": "stat-heavy explainer",
        "sources": [{"url": e["url"], "title": e["title"]}],
    } for e in entries]


def validate_output(data, schema):
    try:
        jsonschema.validate(instance=data, schema=schema)
        return True
    except jsonschema.ValidationError as e:
        print(f"  [warn] Schema validation failed: {e.message}", file=sys.stderr)
        return False


def main():
    parser = argparse.ArgumentParser(description="Monitor Agent")
    parser.add_argument("--top", type=int, default=5)
    parser.add_argument("--config", type=str, default=None, help="Path to feeds JSON file")
    parser.add_argument("--seen-file", type=str,
                        default=str(PROJECT_ROOT / "agents" / "monitor" / "seen.json"))
    parser.add_argument("--api-key", type=str,
                        default=os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY", ""))
    args = parser.parse_args()

    if not args.api_key and not os.environ.get("GOOGLE_CLOUD_PROJECT"):
        print("Error: Configure Gemini with GOOGLE_API_KEY or GOOGLE_CLOUD_PROJECT.", file=sys.stderr)
        sys.exit(1)

    schema = load_schema()
    seen = load_seen(Path(args.seen_file))

    # Load feeds from --config flag, then dashboard feeds.json, then defaults
    feeds = DEFAULT_FEEDS
    if args.config and Path(args.config).exists():
        try:
            with open(args.config) as f:
                feeds = json.load(f)
        except Exception:
            pass
    elif FEEDS_PATH.exists():
        try:
            with open(FEEDS_PATH) as f:
                feeds = json.load(f)
        except Exception:
            pass

    topic_prompt = os.environ.get("COLONY_TOPIC_PROMPT", "").strip()
    if topic_prompt:
        import urllib.parse
        encoded_topic = urllib.parse.quote(topic_prompt)
        feeds = [{
            "name": f"Trending: {topic_prompt}",
            "url": f"https://news.google.com/rss/search?q={encoded_topic}",
            "category": "trending",
            "enabled": True
        }]
        print(f"[info] Using exclusive search feed for topic: {topic_prompt}", flush=True)

    print(f"[1/3] Fetching from {len(feeds)} RSS feeds...", flush=True)
    entries = fetch_entries(feeds)
    print(f"  Fetched {len(entries)} unique entries")

    new_entries = [e for e in entries if story_id(e["title"], e["url"]) not in seen][:20]
    print(f"  {len(new_entries)} new stories (after dedup)")

    if not new_entries:
        print("No new stories found.")
        print("[]")
        return

    print(f"[2/3] Scoring {len(new_entries)} stories via single LLM call...")
    all_scored = score_all(new_entries, args.api_key)
    print(f"  Scored {len(all_scored)} stories")

    for s in all_scored:
        s["_combined"] = s["relevance_score"] + s["novelty_score"] + s["urgency_score"]
    all_scored.sort(key=lambda x: x["_combined"], reverse=True)

    top = all_scored[:args.top]

    print(f"[3/3] Validating top {len(top)} stories against schema...")
    valid_results = []
    for s in top:
        result = {k: v for k, v in s.items() if not k.startswith("_")}
        if validate_output(result, schema):
            valid_results.append(result)
            seen.add(s["story_id"])
            print(f"  OK {s['title'][:60]} (rel={s['relevance_score']:.2f} nov={s['novelty_score']:.2f} urg={s['urgency_score']:.2f})")

    save_seen(Path(args.seen_file), seen)
    print(f"\nSaved {len(seen)} seen stories to {args.seen_file}")

    print(f"\n=== Top {len(valid_results)} Stories ===")
    print(json.dumps(valid_results, indent=2))


if __name__ == "__main__":
    main()
