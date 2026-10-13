#!/usr/bin/env bash
# Redeploy the app node groups of the Virtuozzo environment to the given image tag.
# Usage: JELASTIC_API_URL=... JELASTIC_TOKEN=... JELASTIC_ENV_NAME=... redeploy.sh <tag>
# Uses the Virtuozzo/Jelastic API method environment.control.RedeployContainersByGroup.
# Matchbox, Postgres, Redis and MinIO are not redeployed (rarely change, slow to start).
set -euo pipefail

tag="${1:?image tag required}"
: "${JELASTIC_API_URL:?}" "${JELASTIC_TOKEN:?}" "${JELASTIC_ENV_NAME:?}"

redeploy() {
  local group="$1" response
  echo "Redeploying node group '$group' to tag $tag"
  response=$(curl -fsS --max-time 600 \
    --data-urlencode "envName=$JELASTIC_ENV_NAME" \
    --data-urlencode "session=$JELASTIC_TOKEN" \
    --data-urlencode "nodeGroup=$group" \
    --data-urlencode "tag=$tag" \
    --data-urlencode "useExistingVolumes=true" \
    "${JELASTIC_API_URL%/}/1.0/environment/control/rest/redeploycontainersbygroup")
  # The API answers HTTP 200 with {"result": 0} on success, a non-zero result on failure.
  if ! grep -Eq '"result" *: *0' <<<"$response"; then
    echo "Redeploy of '$group' failed: $response" >&2
    exit 1
  fi
}

# api first: it runs the migrations the worker depends on.
redeploy api
redeploy worker
redeploy web
