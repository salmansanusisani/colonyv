"""Publish metadata: hashtags, description shape and YouTube's hard limits.

Previously the uploader sent the raw pipe-joined `script["body"]` as the
description with a static `ai,tech,news,agents` tag string and no hashtags at
all, so every video carried identical, non-descriptive metadata.
"""

import re

import pytest

from colonyv_agent import publishing

SCRIPT = {
    "hook": "Could Mexican cartels and Cambodian scammers be linked through crypto?",
    "body": "First beat about the investigation. | Second beat about laundering. | Third beat on uncertainty.",
    "cta": "Follow the channel for updates.",
    "format": "deep dive",
}
RESEARCH = {
    "entities": ["Sinaloa Cartel", "Cambodia", "Mexico"],
    "primary_source": "https://example.com/story",
    "sources": [{"url": "https://example.com/story"}, {"url": "https://example.com/second"}],
}


def test_hashtags_describe_the_actual_story():
    tags = publishing.build_hashtags(
        entities=RESEARCH["entities"], topic="Cryptocurrency", story_format="deep dive"
    )
    assert "SinaloaCartel" in tags  # multi-word entity became one CamelCase tag
    assert "Cryptocurrency" in tags
    assert "TechNews" in tags
    assert all(" " not in t and "#" not in t for t in tags)


def test_topic_with_ampersand_splits_into_readable_tags():
    tags = publishing.build_hashtags(topic="AI & Machine Learning")
    assert "AI" in tags and "MachineLearning" in tags
    assert "AIMachineLearning" not in tags


def test_breaking_news_format_adds_its_own_tag():
    assert "BreakingNews" in publishing.build_hashtags(story_format="breaking news")
    assert "BreakingNews" not in publishing.build_hashtags(story_format="deep dive")


def test_hashtags_are_deduped_case_insensitively():
    tags = publishing.build_hashtags(entities=["Mexico", "mexico", "MEXICO"], topic="Mexico")
    assert sum(1 for t in tags if t.lower() == "mexico") == 1


def test_never_exceeds_youtube_hashtag_ceiling():
    """>15 hashtags makes YouTube reject the upload outright."""
    tags = publishing.build_hashtags(
        entities=[f"Entity{i}" for i in range(40)], topic="A & B & C & D", limit=99
    )
    assert len(tags) <= 15


def test_slug_hashtag_edge_cases():
    assert publishing.slug_hashtag("GPT-4o") == "GPT4o"
    assert publishing.slug_hashtag("the new report") == "NewReport"
    assert publishing.slug_hashtag("2026") == ""
    assert publishing.slug_hashtag("") == ""
    assert publishing.slug_hashtag("!!!") == ""


def test_slug_hashtag_preserves_proper_nouns_and_acronyms():
    """A too-aggressive stopword list would turn "New York" into "#York"."""
    assert publishing.slug_hashtag("New York") == "NewYork"
    assert publishing.slug_hashtag("NVIDIA") == "NVIDIA"
    assert publishing.slug_hashtag("Sinaloa Cartel") == "SinaloaCartel"
    assert publishing.slug_hashtag("OpenAI Inc") == "OpenAI"


def test_description_has_paragraphs_cta_sources_and_hashtags():
    desc = publishing.build_description(SCRIPT, research=RESEARCH, topic="Cryptocurrency")
    assert " | " not in desc  # the run-on pipe line is gone
    assert "First beat about the investigation." in desc
    assert "Second beat about laundering." in desc
    assert SCRIPT["cta"] in desc
    assert "https://example.com/story" in desc
    assert desc.rstrip().endswith("#TechNews") or "#Cryptocurrency" in desc
    # YouTube shows the first three description hashtags above the title.
    assert len(re.findall(r"#\w+", desc)) >= 3


def test_description_keeps_hashtags_when_body_is_huge():
    """The body is what gets truncated - the hashtag line must survive."""
    script = {**SCRIPT, "body": " | ".join(["x" * 400] * 40)}
    desc = publishing.build_description(script, research=RESEARCH, topic="Cryptocurrency")
    assert len(desc) <= publishing.MAX_DESCRIPTION
    assert "#Cryptocurrency" in desc
    assert "Sources:" in desc


def test_title_is_clamped_to_100_chars():
    long_hook = {"hook": "y" * 400}
    assert len(publishing.build_title(long_hook)) == 100
    assert publishing.build_title({}) == "AI News Update"


def test_keyword_tags_never_contain_hashes_or_blow_the_length_limit():
    tags = publishing.build_keyword_tags(
        entities=["#weird tag", *[f"entity number {i}" for i in range(60)]], topic="Crypto"
    )
    assert all("#" not in t for t in tags)
    assert len(",".join(tags)) <= publishing.MAX_TAGS_CHARS


def test_uploader_clamps_surplus_hashtags_defensively():
    """Even a bad caller must not get the upload rejected."""
    import importlib.util
    from pathlib import Path

    path = Path(__file__).resolve().parent.parent / "agents" / "publisher" / "youtube.py"
    spec = importlib.util.spec_from_file_location("yt_pub", path)
    yt = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(yt)

    desc = "body\n\n" + " ".join(f"#Tag{i}" for i in range(30))
    title, out_desc, tags = yt._enforce_youtube_limits("t" * 300, desc, ["#bad", "ok", "ok"])

    assert len(title) == 100
    assert len(re.findall(r"#\w+", out_desc)) <= 15
    assert tags == ["bad", "ok"]  # '#' stripped, duplicate dropped
