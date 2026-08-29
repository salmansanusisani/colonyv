# ColonyV — Autonomous Media Orchestrator (Devpost Draft)

**Track:** Taskmaster — All Things Agentic Hackathon

## Tagline
An autonomous editorial newsroom that discovers, verifies, designs, produces, and
publishes story-specific short-form video — end to end, driven by a Google ADK
production director on Gemini.

## Summary
ColonyV runs seven autonomous agents — Discovery, Research, Scriptwriter, Art
Director, Visual Producer, Publisher, and Analyst — orchestrated by a Google ADK
production director. It watches feeds, scores stories with Gemini, verifies claims
against sources, writes a script from only what was verified, **designs a bespoke
visual treatment for that specific story**, generates its illustrations, renders a
1080x1920 MP4 with Remotion, and publishes to YouTube. Editorial gates (story
rejection, research retry/stop, render retry, publication verdict, upload retry)
keep the loop safe, and all run state streams to a live dashboard over WebSocket
and persists to Firestore.

## What makes it different
Most generated video is templated: a fixed set of scene layouts with the story's
words dropped in. Every output looks the same.

ColonyV has an **Art Director agent** that designs each episode. It emits a
`VisualPlan` — a validated contract — containing:

- a **concept** for the episode
- a **semantic palette**, where colour carries meaning rather than decoration:
  green for a verified outcome, red for a failure or risk, monochrome when colour
  would be arbitrary
- an **illustration style contract** written for this story
- a **shot list**, each shot choosing from ten composable layouts, with its own
  headline, kicker, emphasised words, type scale, text anchor, camera motion, and
  transition
- a **bespoke illustration brief** per art-bearing shot

The renderer then composes that plan from independent layers — paper, plate, copy,
data, diagram, callouts, brand — rather than selecting a template. Two stories
about the same subject produce genuinely different videos, because the palette,
layouts, and artwork are all decisions rather than defaults.

## How it works
1. **Discovery** scans feeds and asks Gemini to rank candidates on relevance,
   novelty, and urgency.
2. **ADK production director** applies a story gate; rejected stories are skipped.
3. **Research** fetches sources, extracts content, and produces verified claims,
   contradictions, and a confidence level. A research gate retries weak evidence
   up to three passes, or stops.
4. **Scriptwriter** turns verified research into a beat-split narration script,
   using only claims that were verified.
5. **Art Director** designs the episode and emits the `VisualPlan`.
6. **Visual Producer** runs six stages: generate narration, measure real audio
   durations with `ffprobe`, resolve the visual plan, generate illustrations with
   `gemini-2.5-flash-image`, stage brand assets, and render with Remotion. A
   render gate retries once on validation failure.
7. **Publisher** uploads to YouTube with a generated title, description, and tags.
8. **Analyst** closes the run and writes learned signals back into the Discovery
   and Scriptwriter prompts for the next cycle.

## Engineering details worth noting
- **Audio-locked timing.** Narration is generated and measured before any visual
  decision, so shot durations derive from real audio length. Visuals cannot drift
  out of sync.
- **Illustrations are generated at the aspect ratio of the region that displays
  them.** A plate for a side-by-side shot is generated 3:4, a foot band 5:4. This
  removed a whole class of bug where cover-cropping a portrait drawing into a
  narrow column showed a magnified sliver of empty paper.
- **Ground-tone matching.** Generated plates are shifted per-channel onto the
  brand's exact paper colour, and the page's real dot grid is drawn over the top,
  so a drawing sits on the page instead of looking like a pasted rectangle.
- **Content-hash illustration cache.** Re-rendering a video never pays for the
  same image twice; the cache key covers prompt, palette, style contract, aspect,
  model, and post-processing version.
- **Adaptive rate limiting.** The image model's quota is low and reports no
  retry-after hint, so the client learns the sustainable rate: every quota error
  widens the request interval, sustained success narrows it.
- **Graceful degradation everywhere.** If the Art Director fails, the producer
  directs inline. If an illustration fails, that shot downgrades to a typographic
  layout. A missing image never fails a video.

## Tech
- **Google ADK** — production director with a 12-tool suite (7 execution + 5
  decision tools)
- **Gemini 3.5 Flash** on Vertex AI for all reasoning (ADC auth only, no API keys)
- **Gemini 2.5 Flash Image** for illustration generation
- **Remotion 4** + headless Chromium — programmatic 1080x1920 motion graphics
- **Cloud Run** — hosted dashboard, API, and async Pub/Sub stage worker
- **Firestore** — persistent run state and live agent activity
- **Pub/Sub** — asynchronous stage fan-out; each stage is an independent
  retryable unit
- **edge-tts** + `ffprobe` — narration and measurement
- **YouTube Data API v3** — publication

## Autonomy & safety
- A deterministic factory driver and async stage sequencer enforce a validated
  stage order; a stage cannot claim completion without a tool result proving it.
- Research gates retry weak evidence and stop on contradictions; the scriptwriter
  may only use verified claims.
- Every agent boundary is a JSON schema in `contracts/`, validated in tests.
- 65 automated tests cover contract validation, gate policy, runtime
  pause/resume/stop, and the visual system.

## Demo
- Live dashboard streaming seven agent workspaces during an autonomous run
- A full run: discovery → research → script → art direction → illustration →
  render → publish → analysis
- Two videos on different stories, showing that the palette, layouts, and artwork
  differ because the Art Director designed each one
