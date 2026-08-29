"""Async-friendly, single-stage execution for the ColonyV production pipeline.

Each pipeline stage (monitor, research, script, render, publish, analyst) can be
executed independently given the run's shared state. `run_stage` runs one stage
through the ADK pipeline tools and editorial gates and returns the list of next
stages to schedule. This powers both the synchronous factory driver and the
Pub/Sub-async worker, so a stage can be picked up by a separate Cloud Run
service or job and still follow the exact same policy gates.
"""

from __future__ import annotations

from typing import Any

from colonyv_agent import pipeline_runtime as runtime
from colonyv_agent.tools.editorial import (
    evaluate_publication_gate,
    evaluate_render_result,
    evaluate_research_gate,
    evaluate_story_candidate,
    evaluate_upload_result,
)
from colonyv_agent.tools.pipeline import (
    analyze_performance,
    direct_visuals,
    discover_stories,
    publish_to_youtube,
    request_render,
    research_story,
    write_script,
)

STAGES = ["monitor", "research", "script", "direct", "render", "publish", "analyst"]

MAX_VERIFY_ATTEMPTS = 3


class StageState:
    """Duck-typed ToolContext carrying the run's shared dict state."""

    def __init__(self, state: dict[str, Any] | None = None) -> None:
        self.state: dict[str, Any] = state or {}


def run_stage(
    state: dict[str, Any],
    stage: str,
    story_index: int = 0,
    attempt: int = 1,
) -> dict[str, Any]:
    """Execute one pipeline stage and report what to schedule next.

    Returns {"stage", "decision", "next": [(stage, story_index, attempt)], ...}
    """
    ctx = StageState(state)

    if stage == "monitor":
        discover = discover_stories(ctx)
        if not discover.get("success"):
            return {"stage": stage, "decision": "failed", "error": discover.get("error"),
                    "next": [], "state": state}
        candidates = [
            s for s in state.get("stories", []) if s.get("story_id") and s.get("title")
        ]
        if not candidates:
            return {"stage": stage, "decision": "failed",
                    "error": "No usable candidates were discovered", "next": [], "state": state}
        next_stages = [(s["index"], 1) for s in candidates[: int(state.get("stories_target", 1))]]
        return {"stage": stage, "decision": "continue",
                "story": candidates[0], "next": [("research", s, 1) for s, _ in next_stages],
                "state": state}

    if stage == "research":
        story = state.get("current_story") or state.get("stories", [{}])[story_index]
        gate = evaluate_story_candidate(
            title=story.get("title", ""),
            relevance_score=story.get("relevance_score", 0.0),
            novelty_score=story.get("novelty_score", 0.0),
            urgency_score=story.get("urgency_score", 0.0),
        )
        if gate["decision"] != "continue":
            return {"stage": stage, "decision": "rejected",
                    "story_id": story.get("story_id"),
                    "next": _next_candidate_research(state, story_index), "state": state}
        research = research_story(story_index, ctx)
        if not research.get("success"):
            return {"stage": stage, "decision": "failed",
                    "story_id": story.get("story_id"), "error": research.get("error"),
                    "next": _next_candidate_research(state, story_index), "state": state}
        rg = evaluate_research_gate(
            confidence=research.get("confidence", "low") or "low",
            verified_claims=research.get("verified_claims", 0),
            total_claims=research.get("total_claims", 0),
            contradictions=research.get("contradictions", 0),
            research_attempt=attempt,
            sources_fetched=int(research.get("sources_fetched", 0)),
        )
        if rg["decision"] == "retry":
            return {"stage": stage, "decision": "retry", "next": [("research", story_index, attempt + 1)],
                    "state": state}
        if rg["decision"] == "stop":
            return {"stage": stage, "decision": "stop",
                    "reason": rg["reason"], "next": _next_candidate_research(state, story_index),
                    "state": state}

        # Run the publication gate now, before paying for a script and a render.
        # If the story isn't publishable, re-research it now, or move to the next candidate.
        full_research = ctx.state.get("research") or research
        claims = full_research.get("claims", []) or []
        contradictions_list = full_research.get("contradictions", []) or []
        verified_claims_count = sum(1 for c in claims if isinstance(c, dict) and c.get("verified"))
        pg = evaluate_publication_gate(
            confidence=research.get("confidence", "low") or "low",
            unresolved_contradictions=len(contradictions_list),
            unsupported_claims=max(0, len(claims) - verified_claims_count),
            total_claims=len(claims),
        )
        if pg["decision"] != "publish":
            runtime.log(f"[research] publication gate: {pg['reason']} (attempt {attempt}/{MAX_VERIFY_ATTEMPTS})")
            if attempt < MAX_VERIFY_ATTEMPTS:
                return {"stage": stage, "decision": "reverify",
                        "reason": pg["reason"], "next": [("research", story_index, attempt + 1)],
                        "state": state}
            fallback_next = _next_candidate_research(state, story_index)
            if fallback_next:
                runtime.log(f"[research] verification exhausted; escalating to next candidate {fallback_next}")
                return {"stage": stage, "decision": "escalate", "reason": pg["reason"],
                        "next": fallback_next, "state": state}
            
            discovery_passes = state.get("discovery_passes", 1)
            if discovery_passes < 3:
                runtime.log("[research] all candidates exhausted; re-running discovery")
                state["discovery_passes"] = discovery_passes + 1
                return {"stage": stage, "decision": "escalate", "reason": "out of candidates", "next": [("monitor", 0, 1)], "state": state}

            runtime.log("[research] all candidates exhausted; stopping")
            return {"stage": stage, "decision": "stop", "reason": "exhausted", "next": [], "state": state}
        else:
            state["publish_privacy"] = "public"

        return {"stage": stage, "decision": "continue", "next": [("script", story_index, 1)],
                "state": state}

    if stage == "script":
        script = write_script(ctx)
        if not script.get("success"):
            return {"stage": stage, "decision": "failed", "error": script.get("error"),
                    "next": [], "state": state}
        return {"stage": stage, "decision": "continue", "next": [("direct", story_index, 1)],
                "state": state}

    if stage == "direct":
        plan = direct_visuals(ctx)
        if plan.get("success"):
            return {"stage": stage, "decision": "continue", "next": [("render", story_index, 1)],
                    "state": state}
        # The renderer directs inline as a fallback, so a director failure must
        # not abandon an otherwise good story.
        runtime.log(
            f"[direct] art director failed ({plan.get('error')}); "
            "the producer will direct inline"
        )
        return {"stage": stage, "decision": "fallback", "next": [("render", story_index, 1)],
                "state": state}

    if stage == "render":
        render = request_render(ctx)
        rg = evaluate_render_result(
            success=bool(render.get("success")),
            output_exists=bool(render.get("output_exists")),
            output_size_bytes=int(render.get("output_size_bytes", 0)),
            render_attempt=attempt,
        )
        if rg["decision"] == "retry":
            return {"stage": stage, "decision": "retry", "next": [("render", story_index, attempt + 1)],
                    "state": state}
        if rg["decision"] == "stop" or not render.get("output_exists"):
            return {"stage": stage, "decision": "failed",
                    "reason": rg["reason"], "next": [], "state": state}
        return {"stage": stage, "decision": "continue", "next": [("publish", story_index, 1)],
                "state": state}

    if stage == "publish":
        upload = publish_to_youtube(ctx)
        if upload.get("skipped"):
            return {"stage": stage, "decision": "skipped",
                    "reason": upload.get("reason"), "next": [("analyst", story_index, 1)], "state": state}
        ug = evaluate_upload_result(upload.get("success", False), upload.get("video_id", ""))
        if ug["decision"] == "complete":
            return {"stage": stage, "decision": "complete",
                    "video_id": upload.get("video_id"), "next": [("analyst", story_index, 1)], "state": state}
        if attempt < 3:
            return {"stage": stage, "decision": "retry",
                    "reason": ug["reason"], "next": [("publish", story_index, attempt + 1)], "state": state}
        return {"stage": stage, "decision": "failed",
                "reason": ug["reason"], "next": [], "state": state}

    if stage == "analyst":
        analysis = analyze_performance(ctx)
        return {"stage": stage, "decision": "complete" if analysis.get("success") else "failed",
                "analyst": analysis.get("analyst"), "error": analysis.get("error"),
                "next": [], "state": state}

    return {"stage": stage, "decision": "failed", "error": f"Unknown stage {stage}",
            "next": [], "state": state}


def _next_candidate_research(state: dict[str, Any], story_index: int) -> list[tuple[str, int, int]]:
    """Return the next candidate story's research stage, if any remain."""
    candidates = [
        s for s in state.get("stories", []) if s.get("story_id") and s.get("title")
    ]
    target = int(state.get("stories_target", 1))
    eligible = candidates[:target]
    for cand in eligible:
        if cand.get("index", 0) > story_index:
            return [("research", cand["index"], 1)]
    return []