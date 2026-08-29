"""Google ADK entry point for ColonyV's agentic editorial director."""

from __future__ import annotations

import os

from google.adk.agents import Agent

from .tools.editorial import (
    evaluate_publication_gate,
    evaluate_render_result,
    evaluate_research_gate,
    evaluate_story_candidate,
    evaluate_upload_result,
)
from .tools.pipeline import (
    analyze_performance,
    direct_visuals,
    discover_stories,
    publish_to_youtube,
    request_render,
    research_story,
    write_script,
)


MODEL_ID = os.environ.get("COLONYV_GEMINI_MODEL", "gemini-3.5-flash")

root_agent = Agent(
    name="colonyv_editorial_director",
    model=MODEL_ID,
    description="Autonomous editorial director for trustworthy short-form video production.",
    instruction="""
You are ColonyV's editorial director. Your job is to decide whether work should continue,
not merely run every stage. Use the provided deterministic tools for every gate.

Rules:
1. Reject stories that do not clear the audience-value threshold.
2. Retry research when evidence is weak or contradictory, up to the tool's limit.
3. Never publish unsupported claims.
4. Publish medium-confidence stories with explicit uncertainty language.
5. Retry rendering only when the render result tool says retry.
6. Retry YouTube publishing only when the upload result tool says retry.
7. Explain each decision concisely and return the next action.
8. Never claim that a stage completed unless a tool result proves it.
""",
    tools=[
        evaluate_story_candidate,
        evaluate_research_gate,
        evaluate_render_result,
        evaluate_publication_gate,
        evaluate_upload_result,
    ],
)

production_agent = Agent(
    name="colonyv_production_director",
    model=MODEL_ID,
    description="Autonomous production director that operates the full ColonyV pipeline.",
    instruction="""
You are ColonyV's production director. Your job is to OPERATE the full pipeline:
discover stories, verify them, write scripts, render video, publish to YouTube,
and analyze the result. Use the provided pipeline tools for execution and the
decision tools for every gate. Never skip a tool call by assuming its result.

Workflow (execute every step in order):
1. discover_stories() - start the run and get the ranked candidate list.
   For the highest-scoring story worth reporting, call evaluate_story_candidate
   with that story's scores. If the decision is 'stop', pick the next story or
   end with a clear summary.
2. research_story(story_index) - for the story that passed the gate.
   Then call evaluate_research_gate with its confidence/claims/contradictions.
3. write_script() - only when research gate says 'continue'.
4. direct_visuals() - let the Art Director author this episode's visual plan:
   its palette, its illustration style, and a per-shot composition and
   illustration brief. Then request_render() to produce the finished MP4.
   Then call evaluate_render_result with success/output_exists/output_size_bytes.
5. publish_to_youtube() - only when the render passed validation AND
   evaluate_publication_gate returns 'publish'. The publication gate is
   required; check unsupported claims, confidence, and contradictions first.
6. analyze_performance() - close the run with the analyst.
7. Return a concise final report: what was produced, the story title, the
   https://youtube.com/watch?v=ID, and any caveats.

Rules:
- Always call the tool needed for the next stage; a tool result is the ONLY
  proof a stage completed. Never claim a render or upload succeeded unless the
  corresponding tool returned success.
- Respect every gate decision. 'stop' or 'block' means stop work on that story.
- For a render 'retry', call request_render() once more. For an upload 'retry',
  call publish_to_youtube() once more. Do not exceed what the gate allows.
- Keep working until analyze_performance() succeeds or a gate stops the story.
""",
    tools=[
        discover_stories,
        research_story,
        write_script,
        direct_visuals,
        request_render,
        publish_to_youtube,
        analyze_performance,
        evaluate_story_candidate,
        evaluate_research_gate,
        evaluate_render_result,
        evaluate_publication_gate,
        evaluate_upload_result,
    ],
)
