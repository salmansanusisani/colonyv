# BUILD SPEC — Content Ops Agent
### Read this ENTIRE file before writing any code. This is a fresh project — do not reuse, copy, or reference code from any prior "bitcoin-remotion" directory the human may mention. Everything is built from scratch per this spec.

---

## 0. Operating Rules (non-negotiable)

1. **Phase-gated execution.** This file is divided into numbered Phases. Complete ALL tasks in a phase, pass its entire Verify checklist, then **STOP**. Write a short summary of what you built and exact commands the human can run to test it themselves. Do NOT start the next phase until the human explicitly replies "proceed to Phase N" in the terminal. This is the most important rule in this document — violating it defeats the entire point of this spec.
2. **No silent scope changes.** If a task is ambiguous, or you believe a different approach is better than what's written, STOP and explain the tradeoff before writing code. Do not substitute your own design silently.
3. **Free tools only.** Every library/service must be free (open source, or an explicitly-noted free tier). If you think a paid tool is genuinely necessary, stop and ask.
4. **Small, reviewable diffs.** Don't refactor unrelated code while implementing a task.
5. **Show your work.** After each task, report: (a) files changed, (b) exact verify commands run, (c) their output.
6. **This is a hackathon project** ("Agents for Humans" — AWS Strands Agents SDK + Bedrock AgentCore, Professional Agents track). Code should be demo-able, not just technically correct — favor visible, testable output at every phase over invisible infrastructure.
7. **Every design decision below already reflects lessons learned from an earlier prototype.** Don't "simplify" these away — they're there because the naive version was tried and broke. Specifically: per-beat audio (not one big clip + guessed split), an ambient motion layer (not static backgrounds), and a pluggable image layer (not text-only). These are requirements, not nice-to-haves.
8. **Bonus points reminder (human task, not yours):** the hackathon awards bonus points for publishing a build-journey post on builder.aws.com with "Agents for Humans" in the title, submitted before the deadline. This is a human writing/publishing task, not something for you to do — but flag it in your Phase reports if there's a natural "this would make a good build-journey screenshot/moment" opportunity.

---

## 1. Fresh Project Structure

Create this exact layout at the start of Phase 0:

```
content-agent/
  producer/                  # Remotion video renderer (Phase 1)
    src/
      compositions/          # one file per story "template style" (not per-story!)
      components/            # shared: Backdrop, KenBurnsImage, StatReveal, etc.
    public/
      audio/
      sfx/
      images/
    build_video.py           # CLI: takes a ScriptOutput JSON, renders a video
  agents/
    monitor/                 # Phase 2
    research/                # Phase 3
    scriptwriter/             # Phase 4
    publisher/                # Phase 6
    analyst/                  # Phase 8 (stretch)
  contracts/                  # shared JSON schemas (Phase 0)
    monitor_output.schema.json
    research_output.schema.json
    script_output.schema.json
    production_output.schema.json
  orchestration/               # Strands wiring (Phase 8)
  README.md
```

**Key architectural difference from a naive build:** the Producer is a **generic renderer that takes a `ScriptOutput` JSON and produces a video** — it is NOT hardcoded to any one story. Compositions are reusable "styles" (e.g. "stat-heavy explainer," "mechanism-diagram explainer"), not one-off files per news story. Build it generic from the start.

---

## 2. PHASE 0 — Scaffolding + Contracts

**Goal:** Empty-but-real project skeleton, with the JSON contracts formalized as actual schema files (not just described in prose), so every later phase validates against them.

**Do:**
- Create the folder structure above.
- Write JSON Schema files in `contracts/` for `MonitorOutput`, `ResearchOutput`, `ScriptOutput`, `ProductionOutput` (fields listed below — use JSON Schema `required`/`type` properly, not just field names).

```
MonitorOutput: story_id, title, relevance_score (0-1), novelty_score (0-1), urgency_score (0-1), recommended_format, sources[]
ResearchOutput: story_id, summary, claims[], sources[] (each: outlet, date, role, url), contradictions[] (each: issue, likely_explanation, resolution_for_script), confidence, recommended_angle, what_is_confirmed[], what_is_uncertain[], publication_date, primary_source, secondary_sources[]
ScriptOutput: hook, body, cta, estimated_duration, format, claims_used[], claims_not_used[] (optional), suggested_visual_beats[] (each beat: name, narration_text) -- IMPORTANT: body must be pre-split into named beats here, not one paragraph, because Producer needs one narration text per beat to generate per-beat audio (see Phase 1).
ProductionOutput: asset_url, format, duration, brand_validation, render_status
```
- Set up `package.json`/`requirements.txt` scaffolding for both the Node (Remotion) and Python (agents) sides. Don't install Remotion itself yet — that's Phase 1.
- Write a root `README.md` explaining the project in 2-3 sentences and linking to this build spec.

**Verify:**
- [ ] Folder structure matches exactly.
- [ ] All 4 schema files are valid JSON Schema (validate with a JSON Schema linter/library, not just "it's valid JSON").
- [ ] `ScriptOutput` schema's `suggested_visual_beats` field is an array of objects with at minimum `name` and `narration_text` — this is load-bearing for Phase 1, don't skip it.

**STOP. Report structure + schemas. Wait for "proceed to Phase 0.5."**

---

## 2.5. PHASE 0.5 — LLM + Strands Environment Setup

**STATUS: Bedrock is throttled on this AWS account** (new-account daily token quota, `ThrottlingException`, not self-resolving reliably — confirmed via testing). **Groq via LiteLLM is the confirmed-working model provider for this project.** Use this for ALL agent phases (2-8) unless/until Bedrock's quota clears and the human explicitly says to switch back.

**Confirmed working setup (already verified — reference, don't redo unless something breaks):**

```python
import os
from strands import Agent, tool
from strands.models.litellm import LiteLLMModel

model = LiteLLMModel(
    client_args={"api_key": os.environ["GROQ_API_KEY"]},
    model_id="groq/openai/gpt-oss-120b",
    params={"max_tokens": 1000, "temperature": 0.7},
)
agent = Agent(model=model, tools=[...])
```

**Known gotcha (already hit once, will resurface):** Strands' pre-built tools from `strands_tools` that have OPTIONAL parameters (e.g. `current_time`'s `timezone` param) can trigger `Tool call validation failed ... expected string, but got null` on Groq — this is a real Strands+Groq/LiteLLM schema-validation incompatibility, not a mistake in the tool call itself. **Fix pattern:** whenever a built-in tool from `strands_tools` throws this error, replace it with a minimal custom `@tool`-decorated function that has ONLY required parameters, no optional ones. Do this proactively for any new tool that has optional args before it causes a failure, not reactively after.

**Goal:** Confirm the model provider works, verify AWS account setup for later phases, install Strands.

**Do:**
- Confirm an AWS account exists and the $50 hackathon credit request was submitted (human-reported).
- Install Strands: `pip install strands-agents strands-agents-tools 'strands-agents[litellm]'`
- For any new tool with optional parameters, follow the known-gotcha fix pattern above BEFORE testing against Groq, not after hitting the error.
- Skim https://strandsagents.com/docs/examples/ for multi-agent handoff patterns relevant to Phases 2-8.

**Verify:**
- [x] AWS account confirmed active.
- [x] Credit request confirmed submitted.
- [x] Groq via LiteLLM confirmed working end-to-end (multi-tool reasoning, real output) — DONE, verified in a prior session.
- [ ] Report which example(s) from the Strands Examples page look most relevant to Phases 2-8's multi-agent handoff pattern, with a one-line reason each.

**STOP. Report example notes. Wait for "proceed to Phase 1."**

---

## 3. PHASE 1 — Producer (Remotion renderer)

**Goal:** A generic, reusable video renderer. Input: one `ScriptOutput` JSON (conforming to Phase 0's schema). Output: a rendered mp4. No hardcoded story content anywhere in this phase's code.

**Do — audio (fixes sync drift from the start, don't build the naive version):**
- `build_video.py` takes a `ScriptOutput` JSON as its input argument (e.g. `python3 build_video.py path/to/script.json`).
- For EACH beat in `suggested_visual_beats` (plus hook and cta), generate its own separate `edge-tts` narration file. Measure its REAL duration with `ffprobe`. Never estimate/guess a duration from word count — every duration must come from an actual audio measurement. This is the #1 lesson from the prototype: one big clip + guessed internal split caused visible sync drift.
- Write a `timing.json` per render, computed entirely from these real measurements.

**Do — visuals:**
- Build a generic `Backdrop` component with an ambient motion layer from day one: a slow-drifting gradient (position oscillates via `useCurrentFrame()` + `Math.sin`) plus a subtle particle-drift layer (15-25 low-opacity elements, staggered speed/phase). This is not optional polish — build it into the base template now, not bolted on later.
- Build a reusable `KenBurnsImage` component (slow zoom 1.0→1.08 + slight pan) that any beat can optionally use as a background layer, with a dark gradient overlay so text stays legible on top. Beats without an image just show the animated `Backdrop`.
- Build at least 2 generic beat "shapes" as reusable components, driven entirely by props (no hardcoded text): a `StatRevealBeat` (big number + label, for stats/hooks) and a `DiagramBeat` (two-box comparison with an arrow, for "X vs Y" mechanism explanations) and a `KineticTextBeat` (sequential line-by-line text reveal, for narrative beats). A `ScriptOutput`'s beats get mapped to whichever shape fits their content — this mapping logic can be simple (e.g. explicit `beat_type` field you add to the schema) rather than magic.
- Sound effects: keep the pure-Python synthesis approach (whoosh/pop/ding) from the prototype — free, no downloads, no licensing risk. Cue them at beat transitions.

**Do — SFX/audio-visual wiring:**
- Each beat's own `<Audio>` tag lives inside that beat's own `<Sequence>`, using that beat's own measured duration. No shared "one big audio clip spanning multiple Sequences" pattern — that was the prototype's bug.

**Test content for THIS phase:** use the Coldcard hack story's script as your test `ScriptOutput` input (reconstruct it as a valid JSON per the Phase 0 schema) — but the code must not special-case it. If you find yourself writing `if story_id == "coldcard-hack"` anywhere, stop, that's wrong.

**Verify:**
- [ ] `python3 build_video.py <script.json>` runs to completion, zero errors, on a `ScriptOutput` you construct fresh (not copy-pasted from a prior project).
- [ ] Every beat's audio duration in the render log is a real `ffprobe` measurement, not a computed estimate.
- [ ] `npx tsc --noEmit` passes.
- [ ] Rendered video: background is visibly non-static at any random scrub point.
- [ ] At least one beat in the test render uses `KenBurnsImage` (placeholder image is fine — generate simple gradient PNGs with PIL, do not download copyrighted images).
- [ ] Run the SAME script again with a second, different `ScriptOutput` JSON (make up a short 2-beat test story) and confirm it renders correctly with no code changes — this proves genericness.

**STOP. Report the two test renders + how to watch them. Wait for "proceed to Phase 2."**

---

## 4. PHASE 2 — Monitor Agent

**Goal:** Pull real RSS feeds, score/rank stories, output valid `MonitorOutput` JSON.

**Do:**
- `agents/monitor/monitor.py`. Use `feedparser` (free). Pull from 5-10 real tech/AI/crypto RSS feeds (human can supply URLs or you can find well-known ones — ask if unsure).
- Score relevance/novelty/urgency via an LLM call. **Use the confirmed Groq/LiteLLM setup from Phase 0.5** (same `model` object pattern) — do not default to Bedrock, it's throttled on this account.
- Validate output against `contracts/monitor_output.schema.json` before printing/saving it.
- Include basic dedup logic (don't re-surface a story_id already seen in a local "seen stories" file).

**Verify:**
- [ ] Running against LIVE feeds produces valid `MonitorOutput` JSON (schema-validated) for at least 3 real, current stories.
- [ ] Running it twice in a row demonstrably dedupes the second time.
- [ ] Human manually reviews the top-ranked story and confirms it's a reasonable pick.

**STOP. Report output + how to re-run. Wait for "proceed to Phase 3."**

---

## 5. PHASE 3 — Research Agent (self-healing scraper)

**Goal:** Given one story (id/title/URL from Monitor), produce a schema-valid `ResearchOutput` with a real evidence layer, and prove the self-healing recovery path actually works (not just the happy path).

**Do:**
- `agents/research/research.py`. Use `Crawl4AI` (free, self-hosted, Apache 2.0).
- Implement the recovery flow: crawl → extraction succeeds? if not → inspect raw HTML → generate a new extraction strategy (LLM-assisted re-locate) → retry → validate.
- Pull 2+ independent sources per story where possible, and populate `contradictions[]` honestly if sources disagree (don't force a false consensus).
- Validate output against `contracts/research_output.schema.json`.

**Verify:**
- [ ] Happy path: a real, normal article in → valid `ResearchOutput` with real source URLs out.
- [ ] Recovery path: construct ONE deliberately awkward test page (weird markup, JS-rendered content, whatever breaks naive scraping) and prove in logs that the agent detected the failure AND changed its extraction strategy — not just retried the identical request.
- [ ] Human spot-checks one `ResearchOutput`'s claims against its cited sources and confirms accuracy.

**STOP. Report both test cases + logs proving recovery triggered. Wait for "proceed to Phase 4."**

---

## 6. PHASE 4 — Scriptwriter Agent

**Goal:** `ResearchOutput` in → schema-valid `ScriptOutput` out, with `suggested_visual_beats` properly split per Phase 0/1's requirements (this is what makes Phase 1's per-beat audio possible).

**Do:**
- `agents/scriptwriter/scriptwriter.py`. LLM call, brand-voice system prompt.
- Every sentence in the output must trace back to an entry in the input's `claims[]` — populate `claims_used`/`claims_not_used` honestly.
- Output must be schema-valid, including a properly beat-split body (not one paragraph).

**Verify:**
- [ ] Given a real `ResearchOutput` from Phase 3, output is schema-valid.
- [ ] Every `claims_used` entry is traceable to the input.
- [ ] Human reads the script and confirms tone/quality is usable.

**STOP. Report the script. Wait for "proceed to Phase 5."**

---

## 7. PHASE 5 — One-shot end-to-end pipeline

**Goal:** Chain Monitor → Research → Scriptwriter → Producer for ONE real story, manually triggered, proving the whole thing works together — no orchestration framework yet, just calling each script in sequence.

**Do:**
- `run_pipeline.py` at project root: calls each agent in order, passing output → input per the schemas, ending with a real rendered video.

**Verify:**
- [ ] One full run, live/current story, produces a finished mp4 with zero manual JSON editing at any step.
- [ ] This is the actual proof-of-concept moment — treat it as a milestone, not just another task.

**STOP. Report the video + full pipeline log. Wait for "proceed to Phase 6."**

---

## 8. PHASE 6 — Publisher Agent (YouTube only)

**Goal:** Upload the rendered video to YouTube via YouTube Data API v3.

**Do:**
- `agents/publisher/publisher.py`. OAuth setup instructions in README (human has to do the Google Cloud Console part manually — that's expected, flag it clearly).
- Upload as unlisted/private for testing.

**Verify:**
- [ ] One real video uploads successfully.
- [ ] Auth errors are reported clearly, not swallowed.

**STOP. Wait for "proceed to Phase 7."**

---

## 9. PHASE 7 — Confidence Gate

**Goal:** Route based on Research's confidence — high confidence auto-proceeds to Publisher, low confidence/contradictions stop for human review instead of publishing.

**Verify:**
- [ ] High-confidence input → auto-proceeds through to Publisher.
- [ ] Deliberately low-confidence/contradictory input → pipeline halts BEFORE Publisher with a clear explanation why.

**STOP. Wait for "proceed to Phase 8."**

---

## 10. PHASE 8 — Analyst + Strands orchestration (stretch)

**Goal:** Close the loop (performance → learned signals → Monitor/Scriptwriter) and wrap the whole pipeline in Strands, deployable to Bedrock AgentCore.

**Do:**
- Build the Analyst agent per the architecture doc §5.7 (learned signals, not raw metrics).
- Wire Phases 2-6's scripts into actual Strands agent handoffs (not just sequential Python function calls, as in Phase 5's `run_pipeline.py`) — use the patterns identified in Phase 0.5 from the Strands Examples page.
- For AgentCore deployment, follow the official docs exactly, in this order: https://docs.aws.amazon.com/bedrock-agentcore/ (overview) → https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/agentcore-get-started-cli.html (CLI quickstart) → https://aws.github.io/bedrock-agentcore-starter-toolkit/user-guide/runtime/quickstart.html (deploying a Strands agent specifically to AgentCore Runtime).
- Re-derive exact task specifics with the human before starting — real-world results from Phases 2-7 should inform what's worth automating first, don't assume this doc's Phase-8 sketch is still accurate by the time you get here.

**Verify:**
- [ ] Analyst produces learned-signal output (not raw metrics) per architecture doc §5.7's example format.
- [ ] At least Monitor→Research handoff runs as real Strands agents calling each other, not plain sequential script calls.
- [ ] If AgentCore deployment is attempted: agent is reachable/invokable after following the official quickstart, confirmed with a real test invocation.

**STOP. This is the last phase — report full pipeline status and any remaining gaps before considering the project "hackathon-submission-ready."**

---

## 11. What NOT to do, ever, in any phase

- No X/Instagram publishing (YouTube only, for now).
- No podcast clipping or carousel generation (deferred).
- No paid API/service without explicit human sign-off first.
- No skipping the STOP-and-wait checkpoint, even if the next phase seems obvious.
- No copying code from any prior "bitcoin-remotion" prototype — this is a fresh build informed by that prototype's lessons, not a fork of it.
