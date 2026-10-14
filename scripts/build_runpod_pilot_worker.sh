#!/usr/bin/env bash
# Build the RIFE-only pilot image locally. Never pushes or creates a Runpod resource.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

GIT_SHA="${GIT_SHA:-$(git rev-parse HEAD)}"
PIPELINE_VERSION="aividup-rife-interp-v1"
MANIFEST="runpod/pilot/rife-v4.26/manifest.json"
MODEL_MANIFEST_SHA256="$(sha256sum "$MANIFEST" | cut -d' ' -f1)"
IMAGE="${IMAGE:-aividup-worker-runpod-rife-pilot}"

exec docker build \
  --file docker/Dockerfile.runpod-pilot \
  --build-arg "GIT_SHA=$GIT_SHA" \
  --build-arg "PIPELINE_VERSION=$PIPELINE_VERSION" \
  --build-arg "MODEL_MANIFEST_SHA256=$MODEL_MANIFEST_SHA256" \
  --tag "$IMAGE:$GIT_SHA" \
  .
