"""Programmatic ADK invocation used by the dashboard and Cloud Run API."""

from __future__ import annotations

import uuid

from google.adk.runners import InMemoryRunner
from google.genai import types

from .agent import production_agent, root_agent


async def invoke_editorial_director(message: str) -> dict:
    runner = InMemoryRunner(agent=root_agent, app_name="colonyv")
    session_id = uuid.uuid4().hex
    user_id = "colonyv-dashboard"
    await runner.session_service.create_session(
        app_name="colonyv", user_id=user_id, session_id=session_id
    )
    final_text = ""
    events = []
    async for event in runner.run_async(
        user_id=user_id,
        session_id=session_id,
        new_message=types.Content(role="user", parts=[types.Part(text=message)]),
    ):
        events.append({"author": event.author, "final": event.is_final_response()})
        if event.is_final_response() and event.content and event.content.parts:
            final_text = "".join(part.text or "" for part in event.content.parts)
    return {"session_id": session_id, "response": final_text, "events": events}


async def run_production_cycle(message: str, on_event=None) -> dict:
    """Run the production director over one full story cycle.

    Yields control to the caller through ``on_event`` so the dashboard can
    surface each tool invocation, agent decision, and final transcript live.
    """
    runner = InMemoryRunner(agent=production_agent, app_name="colonyv-production")
    session_id = uuid.uuid4().hex
    user_id = "colonyv-dashboard"
    await runner.session_service.create_session(
        app_name="colonyv-production", user_id=user_id, session_id=session_id
    )
    final_text = ""
    events = []

    async for event in runner.run_async(
        user_id=user_id,
        session_id=session_id,
        new_message=types.Content(role="user", parts=[types.Part(text=message)]),
    ):
        record = {
            "author": event.author,
            "final": event.is_final_response(),
            "turn_complete": getattr(event, "turn_complete", False),
        }
        if event.content and event.content.parts:
            record["text"] = "".join(p.text or "" for p in event.content.parts)
            if event.is_final_response():
                final_text = record["text"]
        if on_event:
            await on_event(record)
        events.append(record)

    return {
        "session_id": session_id,
        "response": final_text,
        "events": events,
    }