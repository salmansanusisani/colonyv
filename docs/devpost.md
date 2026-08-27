# ColonyV — Autonomous Media Orchestrator (Devpost Draft)

**Track:** Taskmaster — All Things Agentic Hackathon

## Tagline
An autonomous editorial newsroom that discovers, verifies, produces, and publishes story-specific short-form video — end to end, driven by a Google ADK Editorial Director on Gemini.

## Summary
ColonyV runs six autonomous agents — Discovery, Research, Scriptwriter, Scene Planner, Visual Producer (Remotion), and Analyst — orchestrated by a Google ADK Editorial Director. It watches RSS feeds, scores stories with Gemini, verifies claims, writes scripts, plans motion-graphics scenes, renders 1080x1920 MP4s, and publishes to YouTube — while editorial gates (story rejection, research retry/stop, render retry, publication blocking, upload retry) keep the loop safe. All run state streams to a live dashboard over WebSocket and persists to Firestore.

## How it works
1. **Discovery Agent** scans feeds and asks Gemini to rank candidates (relevance/novelty/urgency).
2. **ADK Editorial Director** applies a story gate; rejected stories are skipped, accepted ones proceed.
3. **Research Agent** fetches sources, extracts content, and produces verified claims + contradictions with a confidence level. A research gate retries weak evidence (up to 3 passes) or stops.
4. **Scriptwriter Agent** turns research into a beat-split narration script (~80-120 words).
5. **ScenePlanner Agent** picks the best Remotion scene template per beat (stat / diagram / kinetic / image / timeline / quiet) with on-screen headlines and exact figures.
6. **Visual Producer** renders a portrait MP4 via Remotion; a render gate retries once on validation failure.
7. **Publisher Agent** uploads to YouTube only when the publication gate clears unsupported claims and confidence.
8. **Analyst Agent** closes the run with learned signals for the next cycle.

## Tech
- **Google ADK** — Editorial Director agent with an 11-tool suite (6 execution + 5 decision tools)
- **Gemini 3.5** on Vertex AI (ADC auth only; no API keys)
- **Cloud Run** — hosted dashboard + API + async Pub/Sub stage worker
- **Firestore** — persistent run state and live agent activity
- **Remotion** — programmatic 1080x1920 motion graphics
- **Pub/Sub** — asynchronous stage fan-out; each stage is an independent retryable unit
- **YouTube Data API** — final publication

## Autonomy & safety
- Deterministic factory driver + async stage sequencer enforce a validated order
- Editorial gates are hard policy: low-confidence/unsupported content is blocked from public publishing, weak research is retried, failed renders retried
- Human approval only for publication blocks; the rest runs fully unattended

## Demo
- Live dashboard streaming six agent workspaces during an autonomous run
- A full run: discovery → research → script → scene plan → render → publish → analysis
- Rendered portrait videos per story