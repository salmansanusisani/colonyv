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
4. Require human approval for medium confidence or one unresolved contradiction.
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
