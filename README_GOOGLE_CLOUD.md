# ColonyV Google Cloud Path

This document describes the qualifying production path for the All Things Agentic Hackathon.

## Required Services

- Gemini 3.5 or newer through Gemini API or Vertex AI
- Google ADK for the Editorial Director
- Cloud Run for the hosted API/dashboard
- Firestore for persistent run state

Cloud Storage and Pub/Sub are the next production additions for asynchronous assets, renders, and events.

## Local Gemini Check

Using the Gemini Developer API:

```bash
export GOOGLE_API_KEY="..."
export COLONYV_GEMINI_MODEL="gemini-3.5-flash"
.venv/bin/python3 scripts/check_gemini.py
```

Using Vertex AI Application Default Credentials:

```bash
gcloud auth application-default login
export GOOGLE_CLOUD_PROJECT="your-project-id"
export GOOGLE_CLOUD_LOCATION="global"
.venv/bin/python3 scripts/check_gemini.py --vertex
```

## ADK Agent

The ADK entry point is:

```text
colonyv_agent/agent.py:root_agent
```

Run the ADK development UI from the repository root:

```bash
.venv/bin/adk web colonyv_agent
```

The Editorial Director has explicit tools for:

- Story rejection
- Research retry or human review
- Render retry
- Publication blocking
- Upload retry

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
