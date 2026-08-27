#!/usr/bin/env bash
# Create the Pub/Sub topic + push subscription for the ColonyV async pipeline.
#
# Usage:
#   ./scripts/setup_pubsub.sh PROJECT_ID SERVICE_URL
#   SERVICE_URL is the deployed Cloud Run URL, e.g.
#     https://colonyv-abcdef-uc.a.run.app
set -euo pipefail

PROJECT_ID="${1:?usage: setup_pubsub.sh PROJECT_ID SERVICE_URL}"
SERVICE_URL="${2:?usage: setup_pubsub.sh PROJECT_ID SERVICE_URL}"
TOPIC="colonyv-stages"
PUSH_ENDPOINT="${SERVICE_URL}/api/pubsub/run-stage"

echo "Enabling Pub/Sub API..."
gcloud services enable pubsub.googleapis.com --project="${PROJECT_ID}" -q

echo "Creating topic projects/${PROJECT_ID}/topics/${TOPIC}..."
gcloud pubsub topics create "${TOPIC}" --project="${PROJECT_ID}" \
  || echo "(topic may already exist)"

echo "Creating push subscription .../subscriptions/colonyv-stages-push -> ${PUSH_ENDPOINT}"
gcloud pubsub subscriptions create "colonyv-stages-push" \
  --project="${PROJECT_ID}" \
  --topic="${TOPIC}" \
  --push-endpoint="${PUSH_ENDPOINT}" \
  --ack-deadline=600 \
  --message-retention-duration=1d \
  --expiration-policy=none \
  || echo "(subscription may already exist; re-run to update push endpoint with --update-push-endpoint)"

echo "Done. Topic: ${TOPIC} | Push: ${PUSH_ENDPOINT}"
echo
echo "Grant the runtime service account pubsub publisher on the topic if missing:"
echo "  gcloud pubsub topics add-iam-policy-binding ${TOPIC} \\"
echo "    --project=${PROJECT_ID} \\"
echo "    --member='serviceAccount:colonyv-runtime@${PROJECT_ID}.iam.gserviceaccount.com' \\"
echo "    --role=roles/pubsub.publisher"