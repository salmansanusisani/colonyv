"""Programmatic ADK invocation used by the dashboard and Cloud Run API."""

from __future__ import annotations

import uuid

from google.adk.runners import InMemoryRunner
from google.genai import types

from .agent import root_agent


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
