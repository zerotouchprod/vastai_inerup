#!/usr/bin/env bash
# Build the combined RIFE + Real-ESRGAN RunPod pilot image locally; never pushes or rents a GPU.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

GIT_SHA="${GIT_SHA:-$(git rev-parse HEAD)}"
PIPELINE_VERSION="aividup-rife-esrgan-both-v1"
MANIFEST="runpod/pilot/rife-esrgan/manifest.json"
MODEL_MANIFEST_SHA256="$(sha256sum "$MANIFEST" | cut -d' ' -f1)"
REALESRGAN_X2PLUS_SHA256="$(tr -d '[:space:]' < runpod/pilot/rife-esrgan/realesrgan-x2plus.sha256)"
IMAGE="${IMAGE:-aividup-worker-runpod-rife-esrgan-pilot}"

test "${#REALESRGAN_X2PLUS_SHA256}" -eq 64
exec docker build \
  --file docker/Dockerfile.runpod-rife-esrgan-pilot \
  --build-arg "GIT_SHA=$GIT_SHA" \
  --build-arg "PIPELINE_VERSION=$PIPELINE_VERSION" \
  --build-arg "MODEL_MANIFEST_SHA256=$MODEL_MANIFEST_SHA256" \
  --build-arg "REALESRGAN_X2PLUS_SHA256=$REALESRGAN_X2PLUS_SHA256" \
  --tag "$IMAGE:$GIT_SHA" \
  .
