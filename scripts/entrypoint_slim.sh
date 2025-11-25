#!/usr/bin/env bash
# entrypoint_slim.sh
# Optional runtime helper: if DOWNLOAD_MODELS=1 then download models to /workspace/project/models
set -e

if [ "${DOWNLOAD_MODELS:-0}" = "1" ]; then
  echo "DOWNLOAD_MODELS=1 -> fetching models to /workspace/project/models"
  mkdir -p /workspace/project/models
  # Example: download from Backblaze B2 presigned URLs that should be provided via env var MODEL_URLS (JSON array)
  if [ -n "${MODEL_URLS:-}" ]; then
    echo "Using MODEL_URLS to download..."
    python3 - <<'PY'
import os, json, sys, subprocess
urls = json.loads(os.environ.get('MODEL_URLS'))
for u in urls:
    fname = os.path.basename(u.split('?')[0])
    out = '/workspace/project/models/' + fname
    print('Downloading', u, '->', out)
    subprocess.check_call(['wget','-O',out,u])
PY
  else
    echo "No MODEL_URLS set; skipping model download"
  fi
fi

# Execute passed command (default: bash)
exec "$@"

