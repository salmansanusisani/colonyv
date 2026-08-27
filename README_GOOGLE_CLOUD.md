# ColonyV Google Cloud Path

This document describes the qualifying production path for the All Things Agentic Hackathon.

## Required Services

- Gemini 3.5 or newer through Vertex AI (Application Default Credentials only; API keys are disallowed by policy)
- Google ADK for the Editorial Director
- Cloud Run for the hosted API/dashboard
- Firestore for persistent run state

Cloud Storage and Pub/Sub are the next production additions for asynchronous assets, renders, and events.

## Authentication

ColonyV uses Vertex AI with Application Default Credentials (ADC). API keys are **not** used — the organization security policy disallows them. Set up ADC once:

```bash
bash <(curl -sSL https://storage.googleapis.com/cloud-samples-data/adc/setup_adc.sh)
gcloud auth application-default login
```

The service account attached to Cloud Run needs `roles/aiplatform.user` and `roles/datastore.user` (plus Cloud Run invoke). No keys are stored in the image or the repository.

## Local Gemini Check

Using Vertex AI Application Default Credentials:

```bash
gcloud auth application-default login
export GOOGLE_CLOUD_PROJECT="your-project-id"
export GOOGLE_CLOUD_LOCATION="global"
.venv/bin/python3 scripts/check_gemini.py --vertex
```

## ADK Agents

The ADK entry points are:

```text
colonyv_agent/agent.py:root_agent          # interactive Editorial Director (Q&A)
colonyv_agent/agent.py:production_agent    # autonomous production director (full tool suite)
```

Run the ADK development UI from the repository root:

```bash
.venv/bin/adk web colonyv_agent
```

The Editorial Director has explicit tools for:

**Execution tools** (operate the real production agents):
- `discover_stories` — run the monitor agent and rank candidates
- `research_story` — run the research agent over a candidate
- `write_script` — run the scriptwriter agent
- `request_render` — render the story to an MP4 via Remotion
- `publish_to_youtube` — upload the finished video
- `analyze_performance` — run the analyst agent over the run

**Decision tools** (editorial policy gates):
- Story rejection
- Research retry or autonomous stop
- Render retry
- Publication blocking
- Upload retry

## Autonomous Production Runs

The dashboard starts a full autonomous run with:

```text
POST /api/agent/run
```

The deterministic factory driver (`colonyv_agent/factory.py`) operates the ADK
tool suite in a validated order — discovery, story gate, research (with retries),
script, render, publication gate, analyst — while streaming live activity to the
dashboard. Run artifacts (monitor/research/script JSON, MP4) land under
`output/<run_id>/`, and the completed state is persisted to Firestore.

## Cloud Run Deployment

Enable APIs:

```bash
gcloud services enable run.googleapis.com artifactregistry.googleapis.com \
  firestore.googleapis.com aiplatform.googleapis.com
```

Create Firestore in Native mode from the Google Cloud Console or with the current `gcloud firestore databases create` command for your selected region.

Build and deploy:

```bash
gcloud builds submit --tag REGION-docker.pkg.dev/PROJECT_ID/colonyv/colonyv
gcloud run deploy colonyv \
  --image REGION-docker.pkg.dev/PROJECT_ID/colonyv/colonyv \
  --region REGION \
  --platform managed \
  --allow-unauthenticated \
  --set-env-vars GOOGLE_CLOUD_PROJECT=PROJECT_ID,GOOGLE_CLOUD_LOCATION=global,COLONYV_GEMINI_MODEL=gemini-3.5-flash
```

For production, attach a service account with only the permissions ColonyV needs, including Vertex AI User, Cloud Datastore User, and the required Cloud Run permissions. Do not put API keys in the image or source repository.
