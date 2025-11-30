#!/usr/bin/env bash
# Temporary helper: upload a produced file to B2 and exit non-zero (intentional failure)
# Usage: FORCE_FILE=/workspace/output/output_interpolated.mp4 B2_BUCKET=... B2_KEY=... ./force_upload_and_fail.sh
set -euo pipefail
log(){ echo "[$(date '+%H:%M:%S')] $*"; }

FILE=${FORCE_FILE:-/workspace/output/output_interpolated.mp4}
B2_BUCKET=${B2_BUCKET:-}
B2_KEY=${B2_KEY:-}
B2_ENDPOINT=${B2_ENDPOINT:-https://s3.us-west-004.backblazeb2.com}
MIN_SIZE=${MIN_SIZE:-51200} # 50KB minimum to consider a valid video

log "Force upload helper starting"
log "File: $FILE"

if [ ! -f "$FILE" ]; then
  log "ERROR: file not found: $FILE"
  echo "{\"status\":\"missing\", \"file\": \"$FILE\"}" > /workspace/force_upload_result.json || true
  exit 2
fi

# check size
size=$(stat -c%s "$FILE" 2>/dev/null || echo 0)
if [ "$size" -lt "$MIN_SIZE" ]; then
  log "ERROR: file too small for reliable upload: ${size} bytes (min=${MIN_SIZE})"
  # Copy to failed dir for manual retrieval
  ts=$(date '+%Y%m%d_%H%M%S')
  faildir="/workspace/force_upload_failed_${ts}"
  mkdir -p "$faildir" || true
  cp -f "$FILE" "$faildir/$(basename "$FILE")" || true
  echo "{\"status\":\"too_small\", \"file\": \"$FILE\", \"size\": $size, \"saved_to\": \"$faildir\"}" > /workspace/force_upload_result.json || true
  log "Saved small file copy to $faildir; not attempting remote upload"
  exit 3
fi

if [ -z "$B2_BUCKET" ]; then
  log "ERROR: B2_BUCKET environment variable not set"
  echo "{\"status\":\"no_bucket\", \"file\": \"$FILE\"}" > /workspace/force_upload_result.json || true
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
# Capture output for diagnostics
UPLOAD_LOG=/workspace/force_upload_upload.log
# Determine object key to upload: prefer B2_OUTPUT_KEY (set by remote_runner) then fallback to B2_KEY (legacy key variable may contain credentials so avoid overwriting it)
OBJ_KEY="${B2_OUTPUT_KEY:-${B2_KEY:-}}"
if [ -z "$OBJ_KEY" ]; then
  BASENAME=$(basename "$FILE")
  TS=$(date '+%Y%m%d_%H%M%S')
  OBJ_KEY="output/${BASENAME%.*}-${TS}.${BASENAME##*.}"
fi

# Determine access/secret keys to pass to upload_b2.py without clobbering B2_KEY used for credentials in env
ACCESS_KEY="${B2_KEY:-${AWS_ACCESS_KEY_ID:-}}"
SECRET_KEY="${B2_SECRET:-${AWS_SECRET_ACCESS_KEY:-}}"

log "Calling upload_b2.py -> bucket=$B2_BUCKET key=$OBJ_KEY endpoint=$B2_ENDPOINT (access_key=${ACCESS_KEY:+set})"
if python3 /workspace/project/upload_b2.py --file "$FILE" --bucket "$B2_BUCKET" --key "$OBJ_KEY" --endpoint "$B2_ENDPOINT" --access-key "$ACCESS_KEY" --secret-key "$SECRET_KEY" >"$UPLOAD_LOG" 2>&1; then
  log "upload_b2.py reported success"
  # upload_b2.py prints JSON to stdout; capture it
  cat "$UPLOAD_LOG" | sed -n '1,200p' || true
  # try to parse JSON and write result manifest
  # Use Python to extract the trailing JSON from the upload log, or emit a minimal manifest
  python3 - <<PY > /workspace/force_upload_result.json 2>/dev/null
import sys, json, re
try:
    s=open('$UPLOAD_LOG').read()
    m=re.search(r'\{.*\}\s*$', s, flags=re.S)
    if m:
        obj=json.loads(m.group(0))
        print(json.dumps(obj))
    else:
        print(json.dumps({'bucket': '$B2_BUCKET', 'key': '$OBJ_KEY'}))
except Exception:
    print(json.dumps({'bucket': '$B2_BUCKET', 'key': '$OBJ_KEY'}))
PY
  # Echo used key for log parsing
  echo "B2_UPLOAD_KEY_USED: s3://$B2_BUCKET/$OBJ_KEY"
  log "Wrote /workspace/force_upload_result.json"
  log "Now exiting with non-zero status as requested (intentional failure)"
  exit 42
else
  rc=$?
  log "upload_b2.py failed (rc=$rc); inspecting log: $UPLOAD_LOG"
  tail -n 200 "$UPLOAD_LOG" | sed -n '1,200p' || true
  # detect credential issues from upload_b2 log
  if grep -Ei "invalid|credential|accesskey|secret" "$UPLOAD_LOG" 2>/dev/null; then
    log "DETECTED: possible credential error in upload_b2.py output. Verify B2_KEY/B2_SECRET or AWS_ACCESS_KEY_ID/AWS_SECRET_ACCESS_KEY are set and correct."
  fi
  # fallback to transfer.sh
  log "Falling back to transfer.sh upload..."
  TRANS_LOG=/workspace/force_upload_transfer.log
  if command -v curl >/dev/null 2>&1; then
    if curl --fail --silent --show-error --upload-file "$FILE" "https://transfer.sh/$(basename "$FILE")" > "$TRANS_LOG" 2>&1; then
      url=$(cat "$TRANS_LOG" | tr -d '\n' || true)
      log "transfer.sh succeeded: $url"
      echo "{\"status\":\"transfer_sh\", \"url\": \"$url\"}" > /workspace/force_upload_result.json || true
      log "Wrote /workspace/force_upload_result.json"
      exit 42
    else
      log "transfer.sh failed: $(tail -n 5 $TRANS_LOG 2>/dev/null || true)"
    fi
  else
    log "curl not available; cannot attempt transfer.sh fallback"
  fi

  # Final fallback: copy file to known failed directory and write manifest
  ts=$(date '+%Y%m%d_%H%M%S')
  faildir="/workspace/force_upload_failed_${ts}"
  mkdir -p "$faildir" || true
  cp -f "$FILE" "$faildir/$(basename "$FILE")" || true
  echo "{\"status\":\"upload_failed\", \"file\": \"$FILE\", \"size\": $size, \"saved_to\": \"$faildir\", \"upload_log\": \"$UPLOAD_LOG\"}" > /workspace/force_upload_result.json || true
  log "Upload failed by upload_b2.py and transfer.sh"
  log "File info: $FILE $size"
  exit 4
fi
