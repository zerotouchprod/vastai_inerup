#!/usr/bin/env bash
# Builds (and optionally pushes) the AIVIDUP worker image, tagged with the git revision.
#   scripts/build_worker.sh            build only
#   PUSH=1 scripts/build_worker.sh     build + push   (docker login ghcr.io first)
# Env: IMAGE (default ghcr.io/zerotouchprod/aividup-worker)
set -euo pipefail
cd "$(dirname "$0")/.."

IMAGE="${IMAGE:-ghcr.io/zerotouchprod/aividup-worker}"
SHA="$(git rev-parse --short=12 HEAD)"
if [[ -n "$(git status --porcelain -- src RIFEv4.26_0921 pipeline_v2.py scripts/worker_start.sh docker/Dockerfile.worker requirements-worker.txt)" ]]; then
  SHA="${SHA}-dirty"
  echo "WARNING: uncommitted changes in worker files - tagging as ${SHA}; do not deploy this tag" >&2
fi

DOCKER_BUILDKIT=1 docker build -f docker/Dockerfile.worker --build-arg "GIT_SHA=${SHA}" -t "${IMAGE}:${SHA}" .
echo "built ${IMAGE}:${SHA}"

if [[ "${PUSH:-0}" == "1" ]]; then
  [[ "$SHA" == *-dirty ]] && { echo "refusing to push a dirty build" >&2; exit 1; }
  docker push "${IMAGE}:${SHA}"
  echo "pushed ${IMAGE}:${SHA}  <- use this exact tag in the Vast adapter config (never :latest)"
fi
