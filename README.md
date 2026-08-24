# Content Ops Agent

Automated video news pipeline for the **Agents for Humans** hackathon (AWS Strands Agents SDK + Bedrock AgentCore). Monitors tech/AI/crypto news, researches stories, writes scripts, renders videos, and publishes to YouTube — all via autonomous agents.

## Build Spec

Full build specification: [CONTENT_AGENT_BUILD_SPEC.md](CONTENT_AGENT_BUILD_SPEC.md)

## Project Structure

```
content-agent/
  producer/          # Remotion video renderer
  agents/            # Agent scripts (monitor, research, scriptwriter, publisher, analyst)
  contracts/         # Shared JSON schemas
  orchestration/     # Strands multi-agent wiring
```

## Quick Start

```bash
# Python dependencies
pip install -r requirements.txt

# Node dependencies (Producer)
cd producer && npm install
```

## Phase Status

- [ ] Phase 0 — Scaffolding + Contracts
- [ ] Phase 0.5 — LLM + Strands Environment Setup
- [ ] Phase 1 — Producer (Remotion renderer)
- [ ] Phase 2 — Monitor Agent
- [ ] Phase 3 — Research Agent
- [ ] Phase 4 — Scriptwriter Agent
- [ ] Phase 5 — One-shot end-to-end pipeline
- [ ] Phase 6 — Publisher Agent
- [ ] Phase 7 — Confidence Gate
- [ ] Phase 8 — Analyst + Strands orchestration
