"""Deterministic editorial decisions exposed as Google ADK tools."""

from __future__ import annotations

from typing import Any


def evaluate_story_candidate(
    title: str,
    relevance_score: float,
    novelty_score: float,
    urgency_score: float,
    minimum_score: float = 0.62,
) -> dict[str, Any]:
    """Decide whether a discovered story deserves further work.

    Args:
        title: Story headline.
        relevance_score: Audience relevance from 0 to 1.
        novelty_score: Story novelty from 0 to 1.
        urgency_score: Time sensitivity from 0 to 1.
        minimum_score: Minimum weighted score required to continue.
    """
    relevance = max(0.0, min(1.0, relevance_score))
    novelty = max(0.0, min(1.0, novelty_score))
    urgency = max(0.0, min(1.0, urgency_score))
    score = round(relevance * 0.5 + novelty * 0.3 + urgency * 0.2, 3)
    proceed = score >= minimum_score and relevance >= 0.55
    return {
        "decision": "continue" if proceed else "stop",
        "story": title,
        "weighted_score": score,
        "reason": (
            "Story clears the editorial relevance and value threshold."
            if proceed
            else "Story is not important enough for the configured audience."
        ),
        "next_action": "research" if proceed else "record_rejection",
    }


def evaluate_research_gate(
    confidence: str,
    verified_claims: int,
    total_claims: int,
    contradictions: int,
    research_attempt: int = 1,
    maximum_research_attempts: int = 3,
) -> dict[str, Any]:
    """Decide whether research can proceed, needs another pass, or must stop."""
    confidence = confidence.lower().strip()
    verified_ratio = verified_claims / max(1, total_claims)
    if confidence == "low" or verified_ratio < 0.4 or contradictions >= 2:
        if research_attempt < maximum_research_attempts:
            return {
                "decision": "retry",
                "reason": "Evidence is weak or contradictory; another research pass is required.",
                "next_action": "research_again",
                "verified_ratio": round(verified_ratio, 3),
            }
        return {
            "decision": "stop",
            "reason": "Evidence remains insufficient after the allowed research attempts.",
            "next_action": "notify_operator",
            "verified_ratio": round(verified_ratio, 3),
        }
    if confidence == "medium" or contradictions:
        return {
            "decision": "continue",
            "reason": "The story is usable; the autonomous policy will publish with uncertainty language.",
            "next_action": "script",
            "verified_ratio": round(verified_ratio, 3),
        }
    return {
        "decision": "continue",
        "reason": "Research is sufficiently verified for autonomous production.",
        "next_action": "script",
        "verified_ratio": round(verified_ratio, 3),
    }


def evaluate_render_result(
    success: bool,
    output_exists: bool,
    output_size_bytes: int,
    render_attempt: int = 1,
    maximum_render_attempts: int = 2,
) -> dict[str, Any]:
    """Decide whether a render succeeded or should be retried."""
    valid = success and output_exists and output_size_bytes >= 100_000
    if valid:
        return {
            "decision": "continue",
            "reason": "Rendered MP4 passed existence and minimum-size checks.",
            "next_action": "publication_gate",
        }
    if render_attempt < maximum_render_attempts:
        return {
            "decision": "retry",
            "reason": "The render failed validation; retry production once with the fallback scene plan.",
            "next_action": "render_again",
        }
    return {
        "decision": "stop",
        "reason": "Rendering failed after the allowed attempts.",
        "next_action": "human_review",
    }


def evaluate_publication_gate(
    confidence: str,
    unresolved_contradictions: int,
    unsupported_claims: int,
    human_approved: bool = False,
) -> dict[str, Any]:
    """Block unsafe publication while allowing autonomous uncertainty handling."""
    confidence = confidence.lower().strip()
    if unsupported_claims > 0 or confidence == "low" or unresolved_contradictions >= 2:
        return {
            "decision": "block",
            "reason": "Public publishing is blocked by unsupported or low-confidence claims.",
            "next_action": "notify_operator",
        }
    return {
        "decision": "publish",
        "reason": "The story satisfies the public publication policy.",
        "next_action": "youtube_upload",
    }


def evaluate_upload_result(
    success: bool,
    video_id: str = "",
    upload_attempt: int = 1,
    maximum_upload_attempts: int = 3,
) -> dict[str, Any]:
    """Decide whether publishing completed or needs retry."""
    if success and video_id:
        return {
            "decision": "complete",
            "reason": "YouTube returned a video identifier.",
            "next_action": "analyze_performance",
            "video_id": video_id,
        }
    if upload_attempt < maximum_upload_attempts:
        return {
            "decision": "retry",
            "reason": "Upload failed; retry using resumable upload state.",
            "next_action": "youtube_upload_again",
        }
    return {
        "decision": "stop",
        "reason": "Publishing failed after the allowed attempts.",
        "next_action": "notify_operator",
    }
