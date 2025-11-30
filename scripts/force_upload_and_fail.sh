#!/usr/bin/env bash
# Temporary helper: upload a produced file to B2 and exit non-zero (intentional failure)
# Usage: FORCE_FILE=/workspace/output/output_interpolated.mp4 B2_BUCKET=... B2_KEY=... ./force_upload_and_fail.sh
set -euo pipefail
log(){ echo "[$(date '+%H:%M:%S')] $*"; }

FILE=${FORCE_FILE:-/workspace/output/output_interpolated.mp4}
B2_BUCKET=${B2_BUCKET:-}
B2_KEY=${B2_KEY:-}
B2_ENDPOINT=${B2_ENDPOINT:-https://s3.us-west-004.backblazeb2.com}

log "Force upload helper starting"
log "File: $FILE"

if [ ! -f "$FILE" ]; then
  log "ERROR: file not found: $FILE"
  exit 2
fi
if [ -z "$B2_BUCKET" ]; then
  log "ERROR: B2_BUCKET environment variable not set"
  exit 3
fi

# If B2_KEY not provided, derive a reasonable default
if [ -z "$B2_KEY" ]; then
  BASENAME=$(basename "$FILE")
  TIMESTAMP=$(date '+%Y%m%d_%H%M%S')
  B2_KEY="output/${BASENAME%.*}-${TIMESTAMP}.${BASENAME##*.}"
fi

log "Uploading $FILE -> s3://$B2_BUCKET/$B2_KEY (endpoint=$B2_ENDPOINT)"
# Reuse existing uploader script. It returns non-zero on failure.
if python3 /workspace/project/scripts/container_upload.py "$FILE" "$B2_BUCKET" "$B2_KEY" "$B2_ENDPOINT"; then
  log "AUTO_UPLOAD_B2: upload succeeded"
  echo "B2_UPLOAD_KEY_USED: s3://$B2_BUCKET/$B2_KEY"
  # create marker so pipeline watchers can pick it up if needed
  echo "{\"bucket\": \"$B2_BUCKET\", \"key\": \"$B2_KEY\"}" > /workspace/force_upload_result.json || true
  log "Wrote /workspace/force_upload_result.json"
  log "Now exiting with non-zero status as requested (intentional failure)"
  exit 42
else
  log "AUTO_UPLOAD_B2: upload failed"
  exit 4
fi

