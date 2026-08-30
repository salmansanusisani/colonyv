"""YouTube publish metadata: description, hashtags and keyword tags.

Before this existed the uploader sent `script["hook"]` as the title, the raw
`script["body"]` as the description and a hardcoded `ai,tech,news,agents` tag
string. Two things were wrong with that:

* `script["body"]` is beat text joined with " | ", so the published description
  was one run-on line with no sources and no call to action.
* There were no hashtags anywhere. YouTube keyword *tags* (`snippet.tags`) are
  not hashtags; the visible ones are parsed out of the description, and YouTube
  surfaces the first three above the title.

Hashtags are derived from what the run actually found - the researched entities,
the run's topic and the story format - so they describe the specific video
rather than repeating one static set forever.

YouTube limits encoded here:
  * more than 15 hashtags causes the upload to be REJECTED, so the cap is hard
  * a hashtag cannot contain spaces or punctuation
  * description max 5000 chars, title max 100
  * `snippet.tags` is limited by total length, not count
"""

from __future__ import annotations

import re

# Well under YouTube's hard limit of 15, which rejects the upload outright.
MAX_HASHTAGS = 8
MAX_DESCRIPTION = 5000
MAX_TITLE = 100
# YouTube rejects tag lists longer than 500 characters.
MAX_TAGS_CHARS = 500

BASE_HASHTAGS = ("TechNews",)
BASE_TAGS = ("ai", "tech", "news", "agents")

# Filler words that waste a hashtag slot. Deliberately conservative: entities are
# proper nouns, so words like "New" must stay or "New York" becomes "#York".
_STOPWORDS = {
    "the", "a", "an", "and", "or", "of", "in", "on", "for", "to", "with",
    "inc", "llc", "ltd", "corp",
}


def slug_hashtag(text: str) -> str:
    """Turn a phrase into a single CamelCase hashtag word.

    "Sinaloa Cartel" -> "SinaloaCartel";  "GPT-4o" -> "GPT4o".
    Returns "" when nothing usable survives.
    """
    if not text:
        return ""
    parts = re.findall(r"[A-Za-z0-9]+", str(text))
    if not parts:
        return ""
    kept = [p for p in parts if p.lower() not in _STOPWORDS] or parts
    out = []
    for part in kept:
        # Preserve existing capitalisation for acronyms (AI, GPU, NVIDIA).
        out.append(part if part.isupper() or not part.islower() else part.capitalize())
    word = "".join(out)
    # A hashtag that is only digits is meaningless.
    return "" if word.isdigit() else word[:60]


def topic_fragments(topic: str) -> list[str]:
    """Split a configured topic into its parts.

    "AI & Machine Learning" -> ["AI", "Machine Learning"], so it becomes
    #AI #MachineLearning instead of one unreadable #AIMachineLearning.
    """
    if not topic:
        return []
    return [p.strip() for p in re.split(r"[&/,+]| and ", str(topic)) if p.strip()]


def build_hashtags(
    entities=None,
    topic: str = "",
    story_format: str = "",
    limit: int = MAX_HASHTAGS,
) -> list[str]:
    """Hashtag words (no leading '#') describing this specific video."""
    candidates: list[str] = []
    for fragment in topic_fragments(topic):
        candidates.append(slug_hashtag(fragment))
    for entity in list(entities or [])[:6]:
        candidates.append(slug_hashtag(entity))
    if story_format and "breaking" in str(story_format).lower():
        candidates.append("BreakingNews")
    candidates.extend(BASE_HASHTAGS)

    seen: set[str] = set()
    tags: list[str] = []
    for word in candidates:
        if not word or len(word) < 2:
            continue
        key = word.lower()
        if key in seen:
            continue
        seen.add(key)
        tags.append(word)
        if len(tags) >= min(limit, 15):
            break
    return tags


def build_keyword_tags(entities=None, topic: str = "", limit_chars: int = MAX_TAGS_CHARS) -> list[str]:
    """`snippet.tags` keywords. These are not hashtags and must not contain '#'."""
    candidates = [*BASE_TAGS]
    candidates.extend(f.lower() for f in topic_fragments(topic))
    candidates.extend(str(e).strip().lower() for e in list(entities or [])[:6])

    seen: set[str] = set()
    tags: list[str] = []
    used = 0
    for raw in candidates:
        tag = re.sub(r"[#<>]", "", str(raw)).strip()
        if not tag or tag in seen:
            continue
        # +1 for the comma the CLI joins on.
        if used + len(tag) + 1 > limit_chars:
            break
        seen.add(tag)
        tags.append(tag)
        used += len(tag) + 1
    return tags


def _source_urls(research=None, story=None, limit: int = 3) -> list[str]:
    urls: list[str] = []
    for holder, key in ((research, "sources"), (story, "sources")):
        for entry in (holder or {}).get(key, []) or []:
            url = entry.get("url") if isinstance(entry, dict) else entry
            if url and url not in urls:
                urls.append(url)
    primary = (research or {}).get("primary_source")
    if primary and primary not in urls:
        urls.insert(0, primary)
    return urls[:limit]


def build_description(
    script: dict,
    research=None,
    story=None,
    topic: str = "",
    hashtags=None,
) -> str:
    """Readable description: body paragraphs, CTA, sources, then hashtags.

    The body arrives as beats joined by " | "; those become real paragraphs.
    The hashtag line is assembled first and always kept, because it is what
    YouTube renders above the title - the body is what gets truncated.
    """
    script = script or {}
    if hashtags is None:
        hashtags = build_hashtags(
            entities=(research or {}).get("entities"),
            topic=topic,
            story_format=script.get("format") or (story or {}).get("recommended_format", ""),
        )

    body = str(script.get("body") or "").strip()
    paragraphs = [p.strip() for p in body.split("|") if p.strip()]

    tail_parts: list[str] = []
    cta = str(script.get("cta") or "").strip()
    if cta:
        tail_parts.append(cta)
    urls = _source_urls(research, story)
    if urls:
        tail_parts.append("Sources:\n" + "\n".join(f"- {u}" for u in urls))
    if hashtags:
        tail_parts.append(" ".join(f"#{h}" for h in hashtags[:MAX_HASHTAGS]))
    tail = "\n\n".join(tail_parts)

    budget = MAX_DESCRIPTION - (len(tail) + 2 if tail else 0)
    head = ""
    for para in paragraphs:
        candidate = f"{head}\n\n{para}" if head else para
        if len(candidate) > budget:
            break
        head = candidate
    if not head and paragraphs:
        head = paragraphs[0][:max(0, budget)]

    description = "\n\n".join(p for p in (head, tail) if p)
    return description[:MAX_DESCRIPTION].strip()


def build_title(script: dict) -> str:
    title = str((script or {}).get("hook") or "").strip() or "AI News Update"
    return title[:MAX_TITLE]
