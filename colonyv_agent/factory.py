from __future__ import annotations

from typing import Any

from colonyv_agent import pipeline_runtime as runtime
from colonyv_agent.stages import MAX_VERIFY_ATTEMPTS
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


class _Context:
    def __init__(self) -> None:
        self.state: dict[str, Any] = {}


def _policy(decision: dict[str, Any]) -> None:
    runtime.log(
        f"[gate] decision={decision.get('decision')} "
        f"next_action={decision.get('next_action')} reason={decision.get('reason')}"
    )


def run_factory(stories: int) -> dict[str, Any]:
    ctx = _Context()
    produced: list[dict[str, Any]] = []
    attempted_story_ids: set[str] = set()
    discovery_passes = 0
    MAX_DISCOVERY_PASSES = 3

    discover = discover_stories(ctx)
    if not discover.get("success"):
        return {"error": discover.get("error", "discovery failed")}
    discovery_passes += 1

    run_dir = ctx.state.get("run_dir")
    
    def get_candidates():
        return [s for s in ctx.state.get("stories", []) if s.get("story_id") and s.get("title") and s.get("story_id") not in attempted_story_ids]

    while len(produced) < stories and discovery_passes <= MAX_DISCOVERY_PASSES:
        candidates = get_candidates()
        
        if not candidates:
            if discovery_passes < MAX_DISCOVERY_PASSES:
                runtime.log("[factory] Candidates exhausted, re-running discovery...")
                discover_stories(ctx)
                discovery_passes += 1
                continue
            else:
                runtime.log("[factory] Candidates exhausted and max discovery passes reached.")
                break

        story = candidates[0]
        attempted_story_ids.add(story["story_id"])

        if len(produced) > 0:
            runtime.reset_activity()
            runtime.activity("monitor", "complete", "Discovery complete")

        if not runtime.checkpoint(f"pending content {story['title'][:40]}"):
            runtime.activity("autonomous", "stopped", "Run stopped by operator")
            return {"stopped": True, "stories_produced": produced,
                    "run_id": ctx.state.get("run_id")}

        gate = evaluate_story_candidate(
            title=story.get("title", ""),
            relevance_score=story.get("relevance_score", 0.0),
            novelty_score=story.get("novelty_score", 0.0),
            urgency_score=story.get("urgency_score", 0.0),
        )
        _policy(gate)
        if gate["decision"] != "continue":
            runtime.activity("research", "skipped", f"Content rejected by gate: {story['title'][:60]}")
            continue

        research = None
        pg_decision = None
        pg_reason = ""
        for attempt in range(1, MAX_VERIFY_ATTEMPTS + 1):
            research = research_story(story["index"], ctx)
            if not research.get("success"):
                pg_decision = "stop"
                pg_reason = research.get("error", "research failed")
                break
                
            research_gate = evaluate_research_gate(
                confidence=research.get("confidence", "low") or "low",
                verified_claims=research.get("verified_claims", 0),
                total_claims=research.get("total_claims", 0),
                contradictions=research.get("contradictions", 0),
                research_attempt=attempt,
                maximum_research_attempts=MAX_VERIFY_ATTEMPTS,
                sources_fetched=int(research.get("sources_fetched", 0)),
            )
            _policy(research_gate)
            if research_gate["decision"] == "retry":
                continue
            elif research_gate["decision"] == "stop":
                pg_decision = "stop"
                pg_reason = research_gate["reason"]
                break

            claims = (ctx.state.get("research") or research).get("claims", []) or []
            contradictions_list = (ctx.state.get("research") or research).get("contradictions", []) or []
            verified_claims_count = sum(1 for c in claims if isinstance(c, dict) and c.get("verified"))
            pg = evaluate_publication_gate(
                confidence=research.get("confidence", "low") or "low",
                unresolved_contradictions=len(contradictions_list),
                unsupported_claims=max(0, len(claims) - verified_claims_count),
                total_claims=len(claims),
            )
            _policy(pg)
            pg_decision = pg["decision"]
            pg_reason = pg["reason"]
            if pg_decision != "publish":
                if attempt < MAX_VERIFY_ATTEMPTS:
                    runtime.log(f"[research] publication gate: {pg_reason} (attempt {attempt}/{MAX_VERIFY_ATTEMPTS})")
                    continue
                else:
                    break
            break

        if pg_decision != "publish" or not research or not research.get("success"):
            runtime.activity("research", "failed", pg_reason or "Verification failed")
            runtime.log(f"[research] verification exhausted; dropping story {story['story_id'][:8]}")
            continue

        if not runtime.checkpoint(f"content '{story['title'][:40]}' research complete"):
            runtime.activity("autonomous", "stopped", "Run stopped by operator")
            return {"stopped": True, "stories_produced": produced,
                    "run_id": ctx.state.get("run_id")}

        script = write_script(ctx)
        if not script.get("success"):
            runtime.activity("script", "failed", script.get("error", "script failed"))
            continue

        plan = direct_visuals(ctx)
        if plan.get("success"):
            runtime.log(
                f"[factory] art direction: {plan['shots']} shots, "
                f"{plan['distinct_layouts']} distinct layouts, "
                f"{plan['illustrations_planned']} illustrations, "
                f"accent={plan.get('accent_role', '')}"
            )
        else:
            runtime.log(
                f"[factory] art direction failed ({plan.get('error')}); "
                "the producer will direct inline"
            )

        render = None
        render_gate: dict[str, Any] | None = None
        for attempt in range(1, 3):
            render = request_render(ctx)
            render_gate = evaluate_render_result(
                success=bool(render.get("success")),
                output_exists=bool(render.get("output_exists")),
                output_size_bytes=int(render.get("output_size_bytes", 0)),
                render_attempt=attempt,
            )
            _policy(render_gate)
            if render_gate["decision"] == "retry":
                continue
            break

        if not render or not render.get("success") or not render.get("output_exists"):
            runtime.activity("render", "failed", "Render failed for this content")
            continue

        if not runtime.checkpoint(f"content '{story['title'][:40]}' rendered"):
            runtime.activity("autonomous", "stopped", "Run stopped by operator")
            return {"stopped": True, "stories_produced": produced,
                    "run_id": ctx.state.get("run_id")}

        if not runtime.checkpoint(f"content '{story['title'][:40]}' ready for publication"):
            runtime.activity("autonomous", "stopped", "Run stopped by operator before publishing")
            return {"stopped": True, "stories_produced": produced,
                    "run_id": ctx.state.get("run_id")}

        ctx.state["publish_privacy"] = "public"

        for upload_attempt in range(1, 4):
            if not runtime.checkpoint(f"upload attempt {upload_attempt}/3"):
                runtime.activity("autonomous", "stopped", "Run stopped by operator before upload")
                return {"stopped": True, "stories_produced": produced,
                        "run_id": ctx.state.get("run_id")}
            upload = publish_to_youtube(ctx)
            if upload.get("skipped"):
                runtime.log(f"[publish] skipping upload ({upload.get('reason')})")
                break
            up = evaluate_upload_result(
                upload.get("success", False), upload.get("video_id", ""), upload_attempt=upload_attempt
            )
            _policy(up)
            if up["decision"] == "complete":
                break
            runtime.log(f"[publish] upload retry {upload_attempt}/3 ({up['reason']})")

        produced.append({
            "story_id": story["story_id"],
            "title": story["title"],
            "script": script,
            "render": render,
            "video": render.get("mp4_path"),
        })
        runtime.log(
            f"[factory] content complete: {story['title'][:60]} -> "
            f"{render.get('mp4_path', 'no video')}"
        )

    if len(produced) == 0:
        return {"error": "No usable candidates were discovered or processed successfully", "run_id": ctx.state.get("run_id")}

    if not runtime.checkpoint("analysis"):
        runtime.activity("autonomous", "stopped", "Run stopped by operator before analysis")
        return {"stopped": True, "stories_produced": produced,
                "run_id": ctx.state.get("run_id")}

    analysis = analyze_performance(ctx) if produced else {"success": False, "error": "no content produced"}

    summary = {
        "run_id": ctx.state.get("run_id"),
        "stories_produced": produced,
        "analysis": analysis.get("analyst") if analysis.get("success") else None,
    }
    return summary


def run_factory_async(stories: int):
    import asyncio

    loop = asyncio.get_running_loop()
    return loop.run_in_executor(None, lambda: run_factory(stories))