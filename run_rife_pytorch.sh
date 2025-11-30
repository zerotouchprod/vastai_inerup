#!/usr/bin/env bash
# Clean, minimal runner: extract frames, try assembling, fallback to ffmpeg minterpolate.
set -u

log(){ echo "[$(date '+%H:%M:%S')] $*"; }

INFILE=${1:-}
OUTFILE=${2:-}
FACTOR=${3:-2}

if [ -z "$INFILE" ] || [ -z "$OUTFILE" ]; then
  log "Usage: $0 <input-file> <output-file> <factor:int>"
  exit 2
fi

TMP_DIR=$(mktemp -d 2>/dev/null || mktemp -d -t rife_tmp)
[ -d "$TMP_DIR" ] || { log "Failed to create tmp dir"; exit 4; }
log "TMP_DIR=$TMP_DIR"
mkdir -p "$TMP_DIR/input" "$TMP_DIR/output"

# Early one-shot: if requested, upload an existing output file immediately and exit.
# Trigger by setting FORCE_UPLOAD_ON_NEXT_RUN=1 in the job env. A marker file /workspace/.force_upload_ran
# prevents this from running more than once.
# Support triggers via env OR presence of a trigger file in repo/workspace so users who can't set env vars
# can still enable the one-shot by adding a file to the repo (e.g. /workspace/project/.force_upload or /workspace/force_upload_trigger).
if { [ "${FORCE_UPLOAD_ON_NEXT_RUN:-0}" = "1" ] || [ -f /workspace/project/.force_upload ] || [ -f /workspace/.force_upload ] || [ -f /workspace/force_upload_trigger ]; } && [ ! -f /workspace/.force_upload_ran ]; then
  FORCE_UP_FILE="${FORCE_FILE:-/workspace/output/output_interpolated.mp4}"
  if [ -f "$FORCE_UP_FILE" ] && [ -s "$FORCE_UP_FILE" ]; then
    log "FORCE_UPLOAD_ON_NEXT_RUN: found $FORCE_UP_FILE -> running force_upload_and_fail.sh (one-shot)"
    # create marker to avoid re-running on retries
    touch /workspace/.force_upload_ran 2>/dev/null || true
    export FORCE_FILE="$FORCE_UP_FILE"
    export B2_BUCKET="${B2_BUCKET:-}"
    export B2_KEY="${B2_OUTPUT_KEY:-${B2_KEY:-}}"
    /workspace/project/scripts/force_upload_and_fail.sh
    rc=$?
    log "force_upload_and_fail.sh exited with rc=$rc"
    exit $rc
  else
    log "FORCE_UPLOAD_ON_NEXT_RUN enabled but $FORCE_UP_FILE not present; continuing normal run"
  fi
fi

progress_collapse(){
  # Parse either ffmpeg -progress key=value lines OR human stderr lines like:
  # frame= 2868 fps=0.6 q=26.0 size=   89088kB time=00:00:46.71 bitrate=15622.0kbits/s speed=0.01x
  # If TOTAL_FRAMES or TOTAL_DURATION_MS is set in env, compute ETA and append it.
  python3 -u - <<'PY'
import sys, time, os
kv={}
order=[]
def parse_human(line):
    # split by spaces and parse tokens with '='
    res={}
    for tok in line.strip().split():
        if '=' in tok:
            k,v=tok.split('=',1)
            res[k]=v
    return res

TOTAL_FRAMES = int(os.environ.get('TOTAL_FRAMES','0') or 0)
TOTAL_MS = int(os.environ.get('TOTAL_DURATION_MS','0') or 0)

def fmt_s(s):
    try:
        s=int(round(s))
    except Exception:
        return 'unknown'
    h = s//3600
    m = (s%3600)//60
    sec = s%60
    if h>0:
        return f"{h}h{m:02d}m{sec:02d}s"
    if m>0:
        return f"{m}m{sec:02d}s"
    return f"{sec}s"

for raw in sys.stdin:
    line=raw.rstrip('\n')
    if not line:
        continue
    # try key=value single-line progress format first
    if '=' in line and line.strip().count('=')==1 and line.strip().startswith('progress='):
        # simple progress line
        k,v = line.split('=',1)
        kv[k]=v
        if k=='progress':
            parts=[f"{k}={kv.get(k,'')}" for k in order if k!='progress']
            parts.append(f"progress={kv.get('progress','')}")
            print(f"[{time.strftime('%H:%M:%S')}] "+' '.join(parts), flush=True)
            kv.clear(); order=[]
        continue

    # Try to parse ffmpeg -progress key=value blocks
    if '=' in line and ':' not in line:
        # parse all key=value tokens on the line
        toks = [t for t in line.replace('\r',' ').split() if '=' in t]
        if toks:
            for t in toks:
                k,v = t.split('=',1)
                kv[k]=v
                if k not in order:
                    order.append(k)
            # compute summary when we see progress or when human-like lines (frame/time present)
            if 'progress' in kv or 'time' in kv or 'out_time_ms' in kv or 'frame' in kv:
                # Build base parts
                parts=[]
                for k in order:
                    if k in ('progress',):
                        continue
                    parts.append(f"{k}={kv.get(k,'')}")
                # ETA calculation
                eta_str=''
                try:
                    frame = int(float(kv.get('frame','0') or 0))
                except Exception:
                    frame = 0
                fps = 0.0
                try:
                    fps = float(kv.get('fps','0') or 0)
                except Exception:
                    fps = 0.0
                # out_time_ms preferred
                out_ms = 0
                if 'out_time_ms' in kv:
                    try:
                        out_ms = int(kv.get('out_time_ms','0'))
                    except Exception:
                        out_ms = 0
                elif 'time' in kv:
                    # parse HH:MM:SS.ms
                    tstr = kv.get('time','')
                    try:
                        parts_t = tstr.split(':')
                        if len(parts_t)==3:
                            hh=int(parts_t[0]); mm=int(parts_t[1]); ss=float(parts_t[2])
                            out_ms = int((hh*3600+mm*60+ss)*1000)
                    except Exception:
                        out_ms = 0

                if TOTAL_FRAMES>0 and frame>0 and fps>0:
                    rem = max(0, TOTAL_FRAMES - frame)
                    eta_s = rem / max(1e-6, fps)
                    eta_str = fmt_s(eta_s)
                elif TOTAL_MS>0 and out_ms>0:
                    rem_ms = max(0, TOTAL_MS - out_ms)
                    eta_str = fmt_s(rem_ms/1000.0)
                elif fps>0 and frame>0:
                    # unknown total, show instantaneous per-frame ETA ~ 1/fps
                    eta_str = fmt_s( max(0.0, 1.0/fps) )

                if eta_str:
                    parts.append(f"ETA={eta_str}")

                print(f"[{time.strftime('%H:%M:%S')}] "+' '.join(parts), flush=True)
            continue

    # fallback: try to parse human ffmpeg progress lines
    parsed = parse_human(line)
    if parsed:
        # merge parsed tokens into kv and order
        for k,v in parsed.items():
            kv[k]=v
            if k not in order:
                order.append(k)
        # handle same as above
        try:
            frame = int(float(kv.get('frame','0') or 0))
        except Exception:
            frame = 0
        try:
            fps = float(kv.get('fps','0') or 0)
        except Exception:
            fps = 0.0
        eta_str=''
        if TOTAL_FRAMES>0 and frame>0 and fps>0:
            rem = max(0, TOTAL_FRAMES - frame)
            eta_s = rem / max(1e-6, fps)
            eta_str = fmt_s(eta_s)
        if eta_str:
            parsed['ETA']=eta_str
        parts = [f"{k}={v}" for k,v in parsed.items()]
        print(f"[{time.strftime('%H:%M:%S')}] "+' '.join(parts), flush=True)
        continue

    # default: print raw line so errors and other messages are visible
    print(line, flush=True)
PY
}

# Centralized uploader helper: copy final file to /workspace/final_output.mp4 and call container_upload.py
# Placed here so callers later in the script can invoke it without 'command not found'.
maybe_upload_and_finish(){
  local file="$1"
  # Validate file exists and non-empty
  if [ -z "$file" ] || [ ! -f "$file" ] || [ ! -s "$file" ]; then
    log "Cannot upload: file missing or empty: $file"
    return 1
  fi
  # Copy to final location expected by central uploader
  FINAL="/workspace/final_output.mp4"
  cp -f "$file" "$FINAL" 2>/dev/null || { log "Failed to copy $file to $FINAL"; return 1; }
  ls -lh "$FINAL" || true

  # One-shot trigger: if any trigger file present, prefer to upload immediately via container_upload.py
  TRIG_FILES=("/workspace/project/.force_upload" "/workspace/.force_upload" "/workspace/force_upload_trigger")
  TRIG_PRESENT=0
  for tf in "${TRIG_FILES[@]}"; do
    if [ -f "$tf" ]; then
      TRIG_PRESENT=1
      TRIG_PATH="$tf"
      break
    fi
  done
  if [ "$TRIG_PRESENT" -eq 1 ] && [ ! -f /workspace/.force_upload_ran ]; then
    log "Trigger file detected: $TRIG_PATH -> performing triggered upload"
    # try to read bucket/key from trigger file (support JSON or KEY=VALUE)
    TRIG_BUCKET=""
    TRIG_KEY=""
    if [ -s "$TRIG_PATH" ]; then
      # attempt JSON parse first
      TRIG_JSON=$(cat "$TRIG_PATH" 2>/dev/null || true)
      if python3 - <<PY >/dev/null 2>&1
import sys, json
s=sys.stdin.read()
try:
    obj=json.loads(s)
    if isinstance(obj, dict):
        print('OK')
except Exception:
    sys.exit(1)
PY
      then
        TRIG_BUCKET=$(python3 - <<PY
import json,sys
try:
    obj=json.load(sys.stdin)
    print(obj.get('bucket',''))
except Exception:
    pass
PY
"$TRIG_JSON")
        TRIG_KEY=$(python3 - <<PY
import json,sys
try:
    obj=json.load(sys.stdin)
    print(obj.get('key',''))
except Exception:
    pass
PY
"$TRIG_JSON")
      else
        # try simple KEY=VALUE parsing
        TRIG_BUCKET=$(grep -E '^bucket=' "$TRIG_PATH" 2>/dev/null | sed -E "s/^bucket=//" | tr -d '\"' | head -n1 || true)
        TRIG_KEY=$(grep -E '^(key|k)=|^key=' "$TRIG_PATH" 2>/dev/null | sed -E "s/^(key=|k=)//" | tr -d '\"' | head -n1 || true)
      fi
    fi
    # fallback to env if not present in trigger
    BKT="${TRIG_BUCKET:-}"
    if [ -z "$BKT" ]; then
      BKT="${B2_BUCKET:-}"
    fi
    KEYV="${TRIG_KEY:-}"
    if [ -z "$KEYV" ]; then
      KEYV="${B2_OUTPUT_KEY:-${B2_KEY:-}}"
    fi
    if [ -z "$BKT" ]; then
      log "Triggered upload requested but no bucket provided (trigger file or B2_BUCKET). Skipping triggered upload"
    else
      log "Triggered upload -> bucket=$BKT key=${KEYV:-(auto)}"
      # mark ran
      touch /workspace/.force_upload_ran 2>/dev/null || true
      # call uploader
      if python3 /workspace/project/scripts/container_upload.py "$FINAL" "$BKT" "${KEYV:-output/$(basename "$FINAL")}" "${B2_ENDPOINT:-https://s3.us-west-004.backblazeb2.com}"; then
        echo "B2_UPLOAD_KEY_USED: s3://$BKT/${KEYV:-output/$(basename "$FINAL")}" || true
        log "Triggered AUTO_UPLOAD_B2: upload succeeded"
        # Also write result file
        echo "{\"bucket\": \"$BKT\", \"key\": \"${KEYV:-output/$(basename "$FINAL")}\"}" > /workspace/force_upload_result.json || true
      else
        log "Triggered AUTO_UPLOAD_B2: upload failed (see container_upload.py output)"
      fi
    fi
    # continue normal flow (do not exit) after triggered upload
  fi

  # If AUTO_UPLOAD_B2 explicitly disabled, skip running container_upload.py
  if [ "${AUTO_UPLOAD_B2:-1}" != "1" ]; then
    log "AUTO_UPLOAD_B2 not enabled; skipping centralized upload"
    echo "VASTAI_PIPELINE_COMPLETED_SUCCESSFULLY"
    touch /workspace/VASTAI_PIPELINE_COMPLETED_SUCCESSFULLY 2>/dev/null || true
    return 0
  fi

  # Determine bucket/key (prefer B2_OUTPUT_KEY if set)
  B2_BUCKET=${B2_BUCKET:-$(echo)}
  B2_KEY_ENV=${B2_OUTPUT_KEY:-${B2_KEY:-}}
  if [ -z "${B2_BUCKET}" ]; then
    log "AUTO_UPLOAD_B2 enabled but B2_BUCKET not set; skipping upload"
    echo "VASTAI_PIPELINE_COMPLETED_SUCCESSFULLY"
    touch /workspace/VASTAI_PIPELINE_COMPLETED_SUCCESSFULLY 2>/dev/null || true
    return 0
  fi

  # Choose key: prefer explicit B2_OUTPUT_KEY, otherwise fallback to output path
  if [ -n "$B2_KEY_ENV" ]; then
    outkey="$B2_KEY_ENV"
  else
    outkey="output/$(basename "$file")"
  fi

  log "Calling container_upload.py to upload $FINAL -> s3://$B2_BUCKET/$outkey"
  if python3 /workspace/project/scripts/container_upload.py "$FINAL" "$B2_BUCKET" "$outkey" "${B2_ENDPOINT:-https://s3.us-west-004.backblazeb2.com}"; then
    log "AUTO_UPLOAD_B2: upload succeeded"
  else
    log "AUTO_UPLOAD_B2: upload failed (see container_upload.py output)"
  fi
  echo "VASTAI_PIPELINE_COMPLETED_SUCCESSFULLY"
  touch /workspace/VASTAI_PIPELINE_COMPLETED_SUCCESSFULLY 2>/dev/null || true
  return 0
}

# detect fps
FPS_FRAC=$(ffprobe -v error -select_streams v:0 -show_entries stream=r_frame_rate -of default=noprint_wrappers=1:nokey=1 "$INFILE" 2>/dev/null | head -n1 || true)
if [ -z "$FPS_FRAC" ]; then
  ORIG_FPS=24
else
  if echo "$FPS_FRAC" | grep -q '/'; then
    ORIG_FPS=$(awk -F'/' '{printf "%.6f", $1/$2}' <<<"$FPS_FRAC")
  else
    ORIG_FPS=$FPS_FRAC
  fi
fi
TARGET_FPS=$(awk -v o="$ORIG_FPS" -v f="$FACTOR" 'BEGIN{printf "%g", o*f}')
log "orig_fps=$ORIG_FPS target_fps=$TARGET_FPS"

# Auto-detect best ffmpeg encoder: prefer h264_nvenc if available for much faster assembly
FF_ENCODER="libx264"
FF_OPTS='-crf 18 -preset medium -pix_fmt yuv420p'
if command -v ffmpeg >/dev/null 2>&1; then
  if ffmpeg -hide_banner -encoders 2>/dev/null | grep -i -q "h264_nvenc"; then
    FF_ENCODER='h264_nvenc'
    # Use a reasonably fast nvenc preset and VBR_HQ for quality
    FF_OPTS='-preset p6 -rc vbr_hq -cq 19 -b:v 0 -pix_fmt yuv420p'
    log "Using hardware encoder: $FF_ENCODER $FF_OPTS"
    # sanity-check: try a tiny encode to ensure nvenc works with this ffmpeg build
    if ! ffmpeg -hide_banner -loglevel error -f lavfi -i testsrc=duration=0.2:size=64x64:rate=5 -c:v $FF_ENCODER $FF_OPTS -f null - >/dev/null 2>&1; then
      log "h264_nvenc test encode failed; reverting to libx264"
      FF_ENCODER='libx264'
      FF_OPTS='-crf 18 -preset medium -pix_fmt yuv420p'
    fi
  else
    log "Hardware nvenc not found; falling back to libx264"
  fi
else
  log "ffmpeg not found in PATH; encoder selection skipped"
fi

# extract frames padded to 32
log "Extracting frames to $TMP_DIR/input"
ffmpeg -version | head -n 3 || true

# Compute pad sizes (next multiple of 32) using ffprobe to avoid ffmpeg expression parsing issues
WH=$(ffprobe -v error -select_streams v:0 -show_entries stream=width,height -of csv=p=0:s=x "$INFILE" 2>/dev/null || true)
ROT=$(ffprobe -v error -select_streams v:0 -show_entries stream_tags=rotate -of default=nw=1:nk=1 "$INFILE" 2>/dev/null || true)
if [ -z "$WH" ]; then
  log "WARNING: failed to read input width/height, falling back to no-pad extraction"
  PAD_W=""
  PAD_H=""
else
  WIDTH=$(echo "$WH" | cut -d'x' -f1)
  HEIGHT=$(echo "$WH" | cut -d'x' -f2)
  # If rotation is 90 or 270, swap width/height for display-oriented pad
  ROT_N=$(echo "${ROT:-}" | tr -d '\r\n')
  if [ -n "$ROT_N" ]; then
    case "$ROT_N" in
      90|270|-90|-270)
        log "Detected rotation=$ROT_N; swapping width/height for pad calculation"
        tmp="$WIDTH"; WIDTH="$HEIGHT"; HEIGHT="$tmp"
        ;;
    esac
  fi
  PAD_W=$(( ( (WIDTH + 31) / 32 ) * 32 ))
  PAD_H=$(( ( (HEIGHT + 31) / 32 ) * 32 ))
  # ensure pad is not smaller than input (safety check for odd probe results)
  if [ "$PAD_W" -lt "$WIDTH" ] || [ "$PAD_H" -lt "$HEIGHT" ]; then
    log "Computed pad (w=$PAD_W,h=$PAD_H) is smaller than input (w=$WIDTH,h=$HEIGHT); disabling pad"
    PAD_W=""
    PAD_H=""
  else
    log "input_w=$WIDTH input_h=$HEIGHT pad_w=$PAD_W pad_h=$PAD_H"
  fi
fi

# Try a simple PNG extraction first (no progress pipe). Save full log for debugging.
if [ -n "${PAD_W:-}" ] && [ -n "${PAD_H:-}" ]; then
  VF_PAD="pad=${PAD_W}:${PAD_H}"
else
  VF_PAD=""
fi

if [ -n "$VF_PAD" ]; then
  ffmpeg -y -hide_banner -loglevel info -i "$INFILE" -map 0:v:0 -vsync 0 -start_number 1 -vf "$VF_PAD" -f image2 -vcodec png "$TMP_DIR/input/frame_%06d.png" >"$TMP_DIR/ff_extract.log" 2>&1 || true
else
  ffmpeg -y -hide_banner -loglevel info -i "$INFILE" -map 0:v:0 -vsync 0 -start_number 1 -f image2 -vcodec png "$TMP_DIR/input/frame_%06d.png" >"$TMP_DIR/ff_extract.log" 2>&1 || true
fi
RC=${PIPESTATUS[0]:-1}
log "png extract rc=$RC; tail ff_extract.log (head 40):"
sed -n '1,40p' "$TMP_DIR/ff_extract.log" 2>/dev/null || true

# Diagnostic listing
log "Post-extract listing of $TMP_DIR/input (first 200 entries):"
ls -la "$TMP_DIR/input" | head -n 200 || true
FIRST_IMG=$(find "$TMP_DIR/input" -type f \( -iname '*.png' -o -iname '*.jpg' \) -print | head -n1 || true)
if [ -n "$FIRST_IMG" ]; then
  log "First frame: $FIRST_IMG"
  command -v file >/dev/null 2>&1 && file "$FIRST_IMG" || true
  command -v hexdump >/dev/null 2>&1 && hexdump -C -n 128 "$FIRST_IMG" | sed -n '1,20p' || true
else
  log "No image files found in $TMP_DIR/input"
fi

# wait for frames
for i in 1 2 3 4 5; do
  COUNT=$(ls -1 "$TMP_DIR/input"/*.png 2>/dev/null | wc -l || true)
  if [ "$COUNT" -gt 0 ]; then break; fi
  log "waiting for frames... attempt $i: count=$COUNT"
  sleep 1
done

COUNT=$(ls -1 "$TMP_DIR/input"/*.png 2>/dev/null | wc -l || true)
log "extracted_frames=$COUNT"
if [ "$COUNT" -eq 0 ]; then
  log "No frames found from PNG extraction; attempting single-frame extraction test"
  ffmpeg -hide_banner -loglevel info -i "$INFILE" -frames:v 1 -f image2 -vcodec png "$TMP_DIR/input/frame_test_000001.png" 2>&1 | progress_collapse | tee "$TMP_DIR/ff_test_extract.log"
  RC2=${PIPESTATUS[0]:-1}
  log "single-frame extract rc=$RC2"
  if [ -f "$TMP_DIR/input/frame_test_000001.png" ]; then
    log "Single test frame created; showing head:"; if command -v hexdump >/dev/null 2>&1; then hexdump -C -n 128 "$TMP_DIR/input/frame_test_000001.png" | sed -n '1,20p' || true; fi
  else
    log "Single-frame test did NOT create a PNG (rc=$RC2); tail of test log:"; tail -n 200 "$TMP_DIR/ff_test_extract.log" 2>/dev/null || true
  fi

  log "Attempting JPEG re-extraction (mjpeg) to avoid PNG decoder issues"
  rm -f "$TMP_DIR/input"/* || true
  if [ -n "${VF_PAD:-}" ]; then
    ffmpeg -hide_banner -loglevel info -progress pipe:1 -nostats -i "$INFILE" -map 0:v:0 -vsync 0 -start_number 1 -vf "$VF_PAD" -pix_fmt yuvj420p -f image2 -vcodec mjpeg "$TMP_DIR/input/frame_%06d.jpg" 2>&1 | progress_collapse | tee "$TMP_DIR/ff_extract_jpg.log"
  else
    ffmpeg -hide_banner -loglevel info -progress pipe:1 -nostats -i "$INFILE" -map 0:v:0 -vsync 0 -start_number 1 -pix_fmt yuvj420p -f image2 -vcodec mjpeg "$TMP_DIR/input/frame_%06d.jpg" 2>&1 | progress_collapse | tee "$TMP_DIR/ff_extract_jpg.log"
  fi
  RC3=${PIPESTATUS[0]:-1}
  log "jpeg extract rc=$RC3; tail of jpeg extract log:"; tail -n 200 "$TMP_DIR/ff_extract_jpg.log" 2>/dev/null || true
  COUNT=$(ls -1 "$TMP_DIR/input"/*.jpg 2>/dev/null | wc -l || true)
  log "jpeg_extracted_frames=$COUNT"
  if [ "$COUNT" -eq 0 ]; then
    log "JPEG re-extraction also produced zero files; aborting"
    tail -n 400 "$TMP_DIR/ff_extract.log" 2>/dev/null || true
    tail -n 400 "$TMP_DIR/ff_extract_jpg.log" 2>/dev/null || true
    exit 4
  fi
fi

# extract audio (optional)
(log "Extracting audio"; ffmpeg -hide_banner -loglevel info -i "$INFILE" -vn -acodec copy "$TMP_DIR/audio.aac" 2>&1) | progress_collapse | tee "$TMP_DIR/ff_audio.log"

# --- attempt batch-runner BEFORE assembly ---
# ensure REPO_DIR is set for batch runner/model lookup
REPO_DIR="/workspace/project/external/RIFE"
mkdir -p "$REPO_DIR/train_log" 2>/dev/null || true

log "GPU diagnostics (nvidia-smi and torch info)"
if command -v nvidia-smi >/dev/null 2>&1; then
  nvidia-smi -L || true
  nvidia-smi --query-gpu=name,memory.total,memory.free --format=csv,noheader || true
fi
python3 - <<PY 2>/dev/null || true
import torch
print('torch_version=', getattr(torch, '__version__', 'n/a'))
print('cuda_available=', torch.cuda.is_available())
if torch.cuda.is_available():
    print('cuda_count=', torch.cuda.device_count())
    try:
        print('device_name=', torch.cuda.get_device_name(0))
    except Exception as e:
        print('device_name_error', e)
PY

log "Attempting batch-runner for RIFE (GPU accelerated if available)"
BATCH_PY="/workspace/project/batch_rife.py"
if [ -f "$BATCH_PY" ]; then
  log "Found external batch runner: $BATCH_PY"
  (export PYTHONUNBUFFERED=1; export REPO_DIR="$REPO_DIR"; python3 "$BATCH_PY" "$TMP_DIR/input" "$TMP_DIR/output" "$FACTOR") >"$TMP_DIR/batch_rife_run.log" 2>&1 &
  BATCH_PID=$!
  log "batch_rife.py started (pid=$BATCH_PID)"
  # Stream the batch log to stdout in real time so remote logs show progress.
  # Use tail -F to follow across rotations; prefix each line to make it clear in the central log.
  touch "$TMP_DIR/batch_rife_run.log" 2>/dev/null || true
  ( tail -n +1 -F "$TMP_DIR/batch_rife_run.log" 2>/dev/null | while IFS= read -r _line; do printf "[batch_rife] %s\n" "$_line"; done ) &
  TAIL_PID=$!
  # Smart wait/monitor loop
  # RIFE_BATCH_MAX_WAIT: total seconds to allow before considering kill (default 3600)
  # RIFE_BATCH_STALL_TIMEOUT: if log hasn't been updated for this many seconds, consider it stalled (default 300)
  MAX_WAIT=${RIFE_BATCH_MAX_WAIT:-36000}
  STALL_TIMEOUT=${RIFE_BATCH_STALL_TIMEOUT:-300}
  CHECK_INTERVAL=${RIFE_BATCH_CHECK_INTERVAL:-5}
  start_time=$(date +%s)
  last_log_update=$start_time
  log "Monitor: MAX_WAIT=${MAX_WAIT}s STALL_TIMEOUT=${STALL_TIMEOUT}s CHECK_INTERVAL=${CHECK_INTERVAL}s"
  # Ensure log file exists so stat checks work
  touch "$TMP_DIR/batch_rife_run.log" 2>/dev/null || true
  while kill -0 $BATCH_PID 2>/dev/null; do
    sleep $CHECK_INTERVAL
    now=$(date +%s)
    # get last modification time of the log file (portable: use stat -c or python fallback)
    if last_mod=$(stat -c %Y "$TMP_DIR/batch_rife_run.log" 2>/dev/null); then
      :
    else
      # fallback to python if stat -c not available
      last_mod=$(python3 - <<PY 2>/dev/null || true
import os,sys
p=sys.argv[1]
try:
    print(int(os.path.getmtime(p)))
except Exception:
    print(0)
PY
"$TMP_DIR/batch_rife_run.log")
    fi
    # normalize
    last_mod=${last_mod:-0}
    # if log updated recently, treat as activity
    age=$((now - last_mod))
    if [ $age -lt $STALL_TIMEOUT ]; then
      last_log_update=$now
    fi
    elapsed=$((now - start_time))
    since_activity=$((now - last_log_update))
    # periodic status every 60s
    if [ $((elapsed % 60)) -lt $CHECK_INTERVAL ]; then
      log "waiting for batch-runner to finish (pid=$BATCH_PID) elapsed=${elapsed}s since_log_update=${since_activity}s"
    fi
    # kill condition: total elapsed exceeded MAX_WAIT AND log hasn't updated for STALL_TIMEOUT
    if [ $elapsed -ge $MAX_WAIT ] && [ $since_activity -ge $STALL_TIMEOUT ]; then
      log "batch_rife.py appears stalled (elapsed=${elapsed}s since_log_update=${since_activity}s) -> killing pid=$BATCH_PID"
      kill $BATCH_PID 2>/dev/null || true
      break
    fi
  done
  # Wait briefly for process to exit and gather final logs
  sleep 1
  if kill -0 $BATCH_PID 2>/dev/null; then
    log "batch_rife.py still running after monitor requested kill; forcing kill"
    kill -9 $BATCH_PID 2>/dev/null || true
  else
    log "batch_rife.py exited (monitor)"
  fi
  # Stop the tail log streamer if it was started
  if [ -n "${TAIL_PID:-}" ]; then
    kill $TAIL_PID 2>/dev/null || true
    wait $TAIL_PID 2>/dev/null || true
  fi
  log "batch_rife log (tail 200):"
  tail -n 200 "$TMP_DIR/batch_rife_run.log" 2>/dev/null || true
  OUT_COUNT=$(ls -1 "$TMP_DIR/output"/*.png 2>/dev/null | wc -l || true)
  log "Batch-runner produced $OUT_COUNT outputs (sample): $(ls -1 "$TMP_DIR/output" 2>/dev/null | head -n 10 | tr '\n' ',' )"
  if [ "$OUT_COUNT" -gt 0 ]; then
    log "Batch-runner succeeded"
  else
    log "Batch-runner produced no outputs, will fall back to per-pair (inference_img.py)"
    # per-pair fallback: run inference_img.py with exp=1 for each pair
    RIFE_PY="/workspace/project/external/RIFE/inference_img.py"
    if [ -f "$RIFE_PY" ]; then
      log "Using per-pair inference with $RIFE_PY"
      # collect input frames sorted
      mapfile -t FRAMES < <(find "$TMP_DIR/input" -maxdepth 1 -type f \( -iname '*.png' -o -iname '*.jpg' -o -iname '*.jpeg' \) -printf '%P\n' | sort)
      N=${#FRAMES[@]}
      log "Per-pair: discovered $N frames"
      if [ "$N" -lt 2 ]; then
        log "Not enough frames for per-pair inference: $N";
      else
        for ((i=0;i<$N-1;i++)); do
          a="$TMP_DIR/input/${FRAMES[$i]}"
          b="$TMP_DIR/input/${FRAMES[$i+1]}"
          pair_index=$((i+1))
          log "RIFE pair #$pair_index: $a $b -> $TMP_DIR/output/frame_$(printf "%06d" $pair_index)_mid.png"
          # run inference_img.py in TMP_DIR so it writes to ./output
          (cd "$TMP_DIR" && export PYTHONUNBUFFERED=1; timeout 300s python3 "$RIFE_PY" --img "$a" "$b" --exp 1 --model "$REPO_DIR/train_log") >"$TMP_DIR/rife_pair_${pair_index}.log" 2>&1 || true
          # check for expected mid (inference_img writes output/img1.png for exp=1)
          if [ -f "$TMP_DIR/output/img1.png" ]; then
            mv -f "$TMP_DIR/output/img1.png" "$TMP_DIR/output/frame_$(printf "%06d" $pair_index)_mid.png"
            log "Wrote mid for pair $pair_index"
          else
            log "No mid produced for pair $pair_index; see $TMP_DIR/rife_pair_${pair_index}.log"
            tail -n 200 "$TMP_DIR/rife_pair_${pair_index}.log" 2>/dev/null || true
          fi
        done
      fi
    else
      log "Per-pair inference script not found: $RIFE_PY"
    fi
  fi
else
  log "No external batch_rife.py found at $BATCH_PY; skipping batch-runner"
fi

# Helper: format seconds to human HhMmSs
format_seconds(){
  s=$1
  if [ -z "$s" ] || [ "$s" -lt 0 ]; then
    echo "unknown"
    return
  fi
  h=$((s/3600))
  m=$(( (s%3600)/60 ))
  sec=$((s%60))
  if [ $h -gt 0 ]; then
    printf "%dh%02dm%02ds" $h $m $sec
  elif [ $m -gt 0 ]; then
    printf "%dm%02ds" $m $sec
  else
    printf "%ds" $sec
  fi
}

# Start periodic summary: watches logfile and prints percent/fps/ETA every INTERVAL seconds.
start_periodic_summary(){
  local logf="$1"; local total_frames="${2:-0}"; local interval="${3:-30}"
  # ensure log exists
  : > "$logf" 2>/dev/null || true
  (
    while true; do
      sleep "$interval"
      # pick latest human progress line
      line=$(tail -n 400 "$logf" 2>/dev/null | grep -E 'frame=.*time=' | tail -n1 || true)
      [ -z "$line" ] && line=$(tail -n 400 "$logf" 2>/dev/null | grep -E 'time=' | tail -n1 || true)
      # parse fields
      frame=$(echo "$line" | sed -n 's/.*frame=[[:space:]]*\([0-9]*\).*/\1/p' || true)
      fps=$(echo "$line" | sed -n 's/.*fps=\([0-9.]*\).*/\1/p' || true)
      out_time=$(echo "$line" | sed -n 's/.*time=\([0-9:.]*\).*/\1/p' || true)
      size_kb=$(echo "$line" | sed -n 's/.*size=[[:space:]]*\([0-9]*\)kB.*/\1/p' || true)
      frame=${frame:-0}
      fps=${fps:-0}
      size_kb=${size_kb:-0}
      # file size
      outsize=0
      [ -f "$OUTFILE" ] && outsize=$(stat -c %s "$OUTFILE" 2>/dev/null || echo 0)
      # compute ETA
      eta_txt="unknown"
      if [ -n "$total_frames" ] && [ "$total_frames" -gt 0 ] && [ "$frame" -gt 0 ] && awk "BEGIN{print ($fps>0)}" >/dev/null 2>&1; then
        # compute remaining frames
        rem=$(awk -v tf="$total_frames" -v f="$frame" 'BEGIN{r=tf-f; if(r<0) r=0; printf "%d", r}')
        # compute ETA seconds
        if awk "BEGIN{print ($fps>0)}" >/dev/null 2>&1; then
          eta_s=$(awk -v r="$rem" -v fps="$fps" 'BEGIN{ if(fps>0) printf "%d", (r/fps); else print 0 }')
          eta_txt=$(format_seconds "$eta_s")
        fi
      elif [ -n "$out_time" ] && [ -n "${TOTAL_DURATION_MS:-}" ] && [ "$TOTAL_DURATION_MS" -gt 0 ]; then
        # parse out_time into seconds
        IFS=':' read -r hh mm ss <<< "$(echo $out_time | awk -F':' '{print $1" "$2" "$3}')"
        out_s=0
        if [ -n "$ss" ]; then
          out_s=$(awk -v H="$hh" -v M="$mm" -v S="$ss" 'BEGIN{printf "%d", H*3600 + M*60 + S}')
        fi
        rem_ms=$((TOTAL_DURATION_MS - out_s*1000))
        if [ $rem_ms -lt 0 ]; then rem_ms=0; fi
        eta_txt=$(format_seconds $((rem_ms/1000)))
      fi
      pct_txt=""
      if [ -n "$total_frames" ] && [ "$total_frames" -gt 0 ] && [ "$frame" -gt 0 ]; then
        pct=$(awk -v f="$frame" -v tf="$total_frames" 'BEGIN{printf "%.2f", (f/tf*100)}')
        pct_txt="$pct%"
      fi
      # print summary
      summary_parts=()
      [ -n "$pct_txt" ] && summary_parts+=("pct=$pct_txt")
      [ -n "$fps" ] && summary_parts+=("fps=$fps")
      summary_parts+=("ETA=$eta_txt")
      if [ "$outsize" -gt 0 ]; then
        summary_parts+=("size=$(numfmt --to=iec-i --suffix=B $outsize 2>/dev/null || echo ${outsize}B)")
      fi
      log "SUMMARY: ${summary_parts[*]} frame=$frame"
    done
  ) &
  REPORTER_PID=$!
  # Ensure reporter is stopped on exit (use single quotes to defer expansion)
  trap 'kill "$REPORTER_PID" 2>/dev/null || true' EXIT
}

stop_periodic_summary(){
  if [ -n "${REPORTER_PID:-}" ]; then
    kill "$REPORTER_PID" 2>/dev/null || true
    unset REPORTER_PID
  fi
}

# Periodic progress summary reporter: reads ffmpeg tee log and prints compact percent/fps/ETA every INTERVAL seconds.
start_periodic_summary(){
  local logf="$1"; local total_frames="${2:-0}"; local interval="${3:-30}"
  # Background reporter
  (
    while true; do
      sleep "$interval"
      # extract latest ffmpeg human progress line from tee'd log
      line=$(tail -n 200 "$logf" 2>/dev/null | grep -E 'frame=.*time=' | tail -n1 || true)
      if [ -z "$line" ]; then
        line=$(tail -n 200 "$logf" 2>/dev/null | grep -E 'time=' | tail -n1 || true)
      fi
      frame=$(echo "$line" | sed -n 's/.*frame=[[:space:]]*\([0-9]*\).*/\1/p' || true)
      fps=$(echo "$line" | sed -n 's/.*fps=\([0-9.]*\).*/\1/p' || true)
      out_time=$(echo "$line" | sed -n 's/.*time=\([0-9:.]*\).*/\1/p' || true)
      size_kb=$(echo "$line" | sed -n 's/.*size=[[:space:]]*\([0-9]*\)kB.*/\1/p' || true)
      frame=${frame:-0}
      fps=${fps:-0}
      size_kb=${size_kb:-0}
      # file size of output being written
      outsize_bytes=0
      if [ -f "$OUTFILE" ]; then outsize_bytes=$(stat -c %s "$OUTFILE" 2>/dev/null || echo 0); fi
      # compute percent/ETA if total_frames available and fps>0
      pct_str=""
      eta_str=""
      if [ -n "$total_frames" ] && [ "$total_frames" -gt 0 ] && [ "$frame" -gt 0 ]; then
        # ensure numeric fps
        fps_num=0
        fps_num=$(awk 'BEGIN{printf "%f", '$fps'}')
        # percent complete
        pct=$(awk -v f="$frame" -v tf="$total_frames" 'BEGIN{ printf "%.4f", (f/tf)*100 }')
        pct_str="pct=$pct"
        # ETA
        if [ "$fps_num" -gt 0 ]; then
          eta_s=$(awk -v rem="$rem" -v fps="$fps_num" 'BEGIN{ if(fps>0) printf "%d", (rem/fps); else print 0 }')
          eta_str="ETA=$(fmt_s $eta_s)"
        fi
      fi
      # compact summary line
      if [ -n "$pct_str" ] || [ -n "$eta_str" ]; then
        summary=("[summary]")
        [ -n "$pct_str" ] && summary+=("$pct_str")
        [ -n "$eta_str" ] && summary+=("$eta_str")
        [ -n "$fps" ] && [ "$fps" -gt 0 ] && summary+=("fps=$fps")
        # file size (approximate if still encoding)
        if [ "$outsize_bytes" -gt 0 ]; then
          if [ "$outsize_bytes" -lt 1024 ]; then
            summary+=("size=${outsize_bytes}B")
          else
            summary+=("size=$(numfmt --to=iec-i --suffix=B "$outsize_bytes")")
          fi
        fi
        log " ${summary[*]}"
      fi
    done
  ) &
  REPORTER_PID=$!
}

# Attempt assembly: prefer filelist from TMP_DIR/output, else look for mids, else fallback
try_filelist(){
  # Build a filelist of outputs (supports mixed png/jpg). If outputs look like images, prefer image2 assembly.
  FL="$TMP_DIR/filelist.txt"
  rm -f "$FL" || true
  shopt -s nullglob
  files=("$TMP_DIR/output"/*.{png,jpg,jpeg} )
  shopt -u nullglob
  if [ ${#files[@]} -eq 0 ]; then
    return 1
  fi
  # write filelist for debugging/concat fallback
  for f in "${files[@]}"; do
    echo "file '$f'" >>"$FL"
  done
  log "filelist head:"; head -n 20 "$FL" || true

  # Determine if files are image frames (by extension)
  ext="${files[0]##*.}"
  case "${ext,,}" in
    png|jpg|jpeg)
      # Try to detect a numeric frame pattern to use image2
      # Find the first file basename and extract the first numeric substring anywhere in the name
      first=$(basename "${files[0]}")
      num=$(echo "$first" | grep -oE '[0-9]+' | head -n1 || true)
      if [ -n "$num" ]; then
        pad=${#num}
        # build pattern by replacing the first occurrence of the numeric substring with printf-style token
        pattern_name=$(echo "$first" | sed -E "s/${num}/%0${pad}d/1")
        pattern="$TMP_DIR/output/$pattern_name"
        start_number=$((10#$num))
        log "Detected image sequence pattern (numeric group anywhere): $pattern start_number=$start_number pad=$pad"
        # Export total frames/duration to enable ETA calculation in progress_collapse
        TOTAL_FRAMES=$(ls -1 "$TMP_DIR/output"/*.{png,jpg,jpeg} 2>/dev/null | wc -l || echo 0)
        export TOTAL_FRAMES
        if [ -n "$TARGET_FPS" ] && [ "$TARGET_FPS" != "" ] && [ "$TOTAL_FRAMES" -gt 0 ]; then
          TOTAL_DURATION_MS=$(awk -v n=$TOTAL_FRAMES -v f="$TARGET_FPS" 'BEGIN{ if(f>0) printf "%d", (n/f*1000); else print 0 }')
          export TOTAL_DURATION_MS
        fi
        # Print ETA hint so it's visible in logs even if progress lines get interleaved
        if [ -n "${TOTAL_DURATION_MS:-}" ] && [ "$TOTAL_DURATION_MS" -gt 0 ]; then
          now_s=$(date +%s)
          finish_s=$((now_s + TOTAL_DURATION_MS/1000))
          finish_ts=$(date -d "@${finish_s}" '+%H:%M:%S' 2>/dev/null || date -r ${finish_s} '+%H:%M:%S' 2>/dev/null || echo "unknown")
          log "ETA_HINT: TOTAL_FRAMES=${TOTAL_FRAMES} TOTAL_DURATION_MS=${TOTAL_DURATION_MS} approx_finish=${finish_ts}"
        else
          log "ETA_HINT: TOTAL_FRAMES=${TOTAL_FRAMES} TOTAL_DURATION_MS=unknown"
        fi

        # start periodic reporter for assembly
        start_periodic_summary "$TMP_DIR/ff_assemble.log" "$TOTAL_FRAMES" 30
        if [ -f "$TMP_DIR/audio.aac" ]; then
          ffmpeg -hide_banner -loglevel info -y -start_number $start_number -framerate "$TARGET_FPS" -i "$pattern" -i "$TMP_DIR/audio.aac" -c:v "$FF_ENCODER" $FF_OPTS -shortest "$OUTFILE" 2>&1 | progress_collapse | tee "$TMP_DIR/ff_assemble.log"
        else
          ffmpeg -hide_banner -loglevel info -y -start_number $start_number -framerate "$TARGET_FPS" -i "$pattern" -c:v "$FF_ENCODER" $FF_OPTS "$OUTFILE" 2>&1 | progress_collapse | tee "$TMP_DIR/ff_assemble.log"
        fi
        rc=${PIPESTATUS[0]:-1}
        stop_periodic_summary || true
         # enforce minimum size threshold to avoid tiny stub files (e.g., metadata-only) - 50KB
         min_size=51200
         outsiz=$(stat -c %s "$OUTFILE" 2>/dev/null || echo 0)
         if [ $rc -eq 0 ] && [ $outsiz -ge $min_size ]; then
           return 0
         else
           log "Image2 assembly failed or produced too-small output (rc=$rc size=$outsiz) - will try concat fallback"
         fi
      else
        log "Could not find numeric substring in filename '${first}'; will try concat fallback"
      fi
      ;;
    *)
      log "Non-image outputs detected, attempting concat demuxer"
      ;;
  esac

  # Fallback: use concat demuxer (works for video files); we already wrote $FL
  # Export total frames/duration based on filelist to enable ETA
  TOTAL_FRAMES=$(wc -l < "$FL" 2>/dev/null || echo 0)
  export TOTAL_FRAMES
  if [ -n "$TARGET_FPS" ] && [ "$TARGET_FPS" != "" ] && [ "$TOTAL_FRAMES" -gt 0 ]; then
    TOTAL_DURATION_MS=$(awk -v n=$TOTAL_FRAMES -v f="$TARGET_FPS" 'BEGIN{ if(f>0) printf "%d", (n/f*1000); else print 0 }')
    export TOTAL_DURATION_MS
  fi
  # Print ETA hint for concat assembly
  if [ -n "${TOTAL_DURATION_MS:-}" ] && [ "$TOTAL_DURATION_MS" -gt 0 ]; then
    now_s=$(date +%s)
    finish_s=$((now_s + TOTAL_DURATION_MS/1000))
    finish_ts=$(date -d "@${finish_s}" '+%H:%M:%S' 2>/dev/null || date -r ${finish_s} '+%H:%M:%S' 2>/dev/null || echo "unknown")
    log "ETA_HINT: TOTAL_FRAMES=${TOTAL_FRAMES} TOTAL_DURATION_MS=${TOTAL_DURATION_MS} approx_finish=${finish_ts}"
  else
    log "ETA_HINT: TOTAL_FRAMES=${TOTAL_FRAMES} TOTAL_DURATION_MS=unknown"
  fi
  # start periodic reporter for concat assembly
  start_periodic_summary "$TMP_DIR/ff_assemble.log" "$TOTAL_FRAMES" 30
  if [ -f "$TMP_DIR/audio.aac" ]; then
    ffmpeg -hide_banner -loglevel info -y -f concat -safe 0 -i "$FL" -framerate "$TARGET_FPS" -i "$TMP_DIR/audio.aac" -c:v "$FF_ENCODER" $FF_OPTS -shortest "$OUTFILE" 2>&1 | progress_collapse | tee "$TMP_DIR/ff_assemble.log"
  else
    ffmpeg -hide_banner -loglevel info -y -f concat -safe 0 -i "$FL" -framerate "$TARGET_FPS" -c:v "$FF_ENCODER" $FF_OPTS "$OUTFILE" 2>&1 | progress_collapse | tee "$TMP_DIR/ff_assemble.log"
  fi
  rc=${PIPESTATUS[0]:-1}
  stop_periodic_summary || true
  outsiz=$(stat -c %s "$OUTFILE" 2>/dev/null || echo 0)
  if [ $rc -eq 0 ] && [ $outsiz -ge 51200 ]; then
    return 0
  fi
  return 1
}

# If there's a batch runner that wrote to TMP_DIR/output, try filelist assembly
if try_filelist; then
  log "assembled via filelist"
  if [ -s "$OUTFILE" ]; then
    log "OK $OUTFILE"
    maybe_upload_and_finish "$OUTFILE" || exit 0
  fi
fi

# Try assembling mids pattern
if ls "$TMP_DIR/output"/frame_*_mid*.png 1>/dev/null 2>&1; then
  log "Assembling from mids"
  # Detect number of mids per pair (e.g., _mid_01, _mid_02 -> 2)
  mids_per_pair=0
  # Try common pattern for pair 1
  if ls "$TMP_DIR/output"/frame_000001_mid_* 1>/dev/null 2>&1; then
    mids_per_pair=$(ls -1 "$TMP_DIR/output"/frame_000001_mid_* 2>/dev/null | wc -l || true)
  else
    # Fallback: count distinct mid suffixes across files
    mids_per_pair=$(ls -1 "$TMP_DIR/output"/frame_*_mid_* 2>/dev/null | awk -F'_mid_' '{print $2}' | awk -F '.' '{print $1}' | sort -u | wc -l || true)
  fi
  if [ -z "$mids_per_pair" ] || [ "$mids_per_pair" -lt 1 ]; then
    mids_per_pair=1
  fi
  log "Detected mids_per_pair=$mids_per_pair"

  # Count input frames
  IN_COUNT=$(find "$TMP_DIR/input" -maxdepth 1 -type f \( -iname '*.png' -o -iname '*.jpg' -o -iname '*.jpeg' \) | wc -l || true)
  if [ -z "$IN_COUNT" ] || [ "$IN_COUNT" -lt 1 ]; then
    log "No input frames found to interleave with mids; skipping mids assembly"
  else
    # Build a concat filelist that interleaves original frames and mids for each pair
    FL="$TMP_DIR/filelist_mids.txt"
    : > "$FL"
    for i in $(seq 1 $IN_COUNT); do
      # append original frame i (if exists)
      if [ -f "$TMP_DIR/input/frame_$(printf "%06d" $i).png" ]; then
        echo "file '$TMP_DIR/input/frame_$(printf "%06d" $i).png'" >> "$FL"
      elif [ -f "$TMP_DIR/input/frame_$(printf "%06d" $i).jpg" ]; then
        echo "file '$TMP_DIR/input/frame_$(printf "%06d" $i).jpg'" >> "$FL"
      elif [ -f "$TMP_DIR/input/frame_$(printf "%06d" $i).jpeg" ]; then
        echo "file '$TMP_DIR/input/frame_$(printf "%06d" $i).jpeg'" >> "$FL"
      fi
      # for each pair (i -> i+1), append mids (only if not the last original frame)
      if [ $i -lt $IN_COUNT ]; then
        for m in $(seq 1 $mids_per_pair); do
          # try zero-padded two-digit suffix first (01,02), then without padding
          midp="$TMP_DIR/output/frame_$(printf "%06d" $i)_mid_$(printf "%02d" $m).png"
          midp2="$TMP_DIR/output/frame_$(printf "%06d" $i)_mid_$m.png"
          if [ -f "$midp" ]; then
            echo "file '$midp'" >> "$FL"
          elif [ -f "$midp2" ]; then
            echo "file '$midp2'" >> "$FL"
          else
            # try jpg variants
            midj="$TMP_DIR/output/frame_$(printf "%06d" $i)_mid_$(printf "%02d" $m).jpg"
            midj2="$TMP_DIR/output/frame_$(printf "%06d" $i)_mid_$m.jpg"
            [ -f "$midj" ] && echo "file '$midj'" >> "$FL"
            [ -f "$midj2" ] && echo "file '$midj2'" >> "$FL"
          fi
        done
      fi
    done

    log "filelist_mids head:"; head -n 40 "$FL" || true
    # Export total frames/duration for ETA
    TOTAL_FRAMES=$(wc -l < "$FL" 2>/dev/null || echo 0)
    export TOTAL_FRAMES
    if [ -n "$TARGET_FPS" ] && [ "$TARGET_FPS" != "" ] && [ "$TOTAL_FRAMES" -gt 0 ]; then
      TOTAL_DURATION_MS=$(awk -v n=$TOTAL_FRAMES -v f="$TARGET_FPS" 'BEGIN{ if(f>0) printf "%d", (n/f*1000); else print 0 }')
      export TOTAL_DURATION_MS
    fi
    # Print ETA hint for mids assembly
    if [ -n "${TOTAL_DURATION_MS:-}" ] && [ "$TOTAL_DURATION_MS" -gt 0 ]; then
      now_s=$(date +%s)
      finish_s=$((now_s + TOTAL_DURATION_MS/1000))
      finish_ts=$(date -d "@${finish_s}" '+%H:%M:%S' 2>/dev/null || date -r ${finish_s} '+%H:%M:%S' 2>/dev/null || echo "unknown")
      log "ETA_HINT: TOTAL_FRAMES=${TOTAL_FRAMES} TOTAL_DURATION_MS=${TOTAL_DURATION_MS} approx_finish=${finish_ts}"
    else
      log "ETA_HINT: TOTAL_FRAMES=${TOTAL_FRAMES} TOTAL_DURATION_MS=unknown"
    fi
    # start periodic reporter for mids assembly
    start_periodic_summary "$TMP_DIR/ff_assemble_mid.log" "$TOTAL_FRAMES" 30
    if [ -f "$TMP_DIR/audio.aac" ]; then
      ffmpeg -hide_banner -loglevel info -y -f concat -safe 0 -i "$FL" -framerate "$TARGET_FPS" -i "$TMP_DIR/audio.aac" -c:v "$FF_ENCODER" $FF_OPTS -shortest "$OUTFILE" 2>&1 | progress_collapse | tee "$TMP_DIR/ff_assemble_mid.log"
    else
      ffmpeg -hide_banner -loglevel info -y -f concat -safe 0 -i "$FL" -framerate "$TARGET_FPS" -c:v "$FF_ENCODER" $FF_OPTS "$OUTFILE" 2>&1 | progress_collapse | tee "$TMP_DIR/ff_assemble_mid.log"
    fi
    RC_ASM=${PIPESTATUS[0]:-1}
    stop_periodic_summary || true
    min_size=51200
    outsiz=$(stat -c %s "$OUTFILE" 2>/dev/null || echo 0)
    if [ $RC_ASM -eq 0 ] && [ $outsiz -ge $min_size ]; then
      log "OK $OUTFILE"
      maybe_upload_and_finish "$OUTFILE" || exit 0
    else
      log "Assembly from mids failed (rc=$RC_ASM size=$outsiz < $min_size or empty); attempting sequential-assembly fallback"
      # Sequential-assembly fallback: build an ordered image sequence (frame_000001.png, frame_000002.png, ...)
      ASSEM_DIR="$TMP_DIR/assembled_seq"
      rm -rf "$ASSEM_DIR" || true
      mkdir -p "$ASSEM_DIR"
      seq_idx=1
      # Read filelist lines and create symlinks with unified .png names to preserve order
      while IFS= read -r l; do
        # strip leading/trailing and remove "file '...'
        fp=$(echo "$l" | sed -E "s/^file[[:space:]]+'(.*)'\s*$/\1/")
        # skip empty
        [ -z "$fp" ] && continue
        if [ -f "$fp" ] && [ -s "$fp" ]; then
          dest="$ASSEM_DIR/frame_$(printf "%06d" $seq_idx).png"
          # Prefer copy if cp is fast enough; use symlink to save space
          ln -sf "$fp" "$dest" 2>/dev/null || cp -f "$fp" "$dest" 2>/dev/null || true
          seq_idx=$((seq_idx+1))
        else
          log "Skipping missing or empty listed file: $fp"
        fi
      done < "$FL"

      if [ $seq_idx -eq 1 ]; then
        log "Sequential assembly: no valid files found in $FL; cannot assemble from mids"
      else
        log "Sequential assembly: prepared $(($seq_idx-1)) frames in $ASSEM_DIR; attempting ffmpeg image2 assemble"
        # Export total frames/duration for ETA
        TOTAL_FRAMES=$((seq_idx-1))
        export TOTAL_FRAMES
        if [ -n "$TARGET_FPS" ] && [ "$TARGET_FPS" != "" ] && [ "$TOTAL_FRAMES" -gt 0 ]; then
          TOTAL_DURATION_MS=$(awk -v n=$TOTAL_FRAMES -v f="$TARGET_FPS" 'BEGIN{ if(f>0) printf "%d", (n/f*1000); else print 0 }')
          export TOTAL_DURATION_MS
        fi
        # Print ETA hint for sequential assembly
        if [ -n "${TOTAL_DURATION_MS:-}" ] && [ "$TOTAL_DURATION_MS" -gt 0 ]; then
          now_s=$(date +%s)
          finish_s=$((now_s + TOTAL_DURATION_MS/1000))
          finish_ts=$(date -d "@${finish_s}" '+%H:%M:%S' 2>/dev/null || date -r ${finish_s} '+%H:%M:%S' 2>/dev/null || echo "unknown")
          log "ETA_HINT: TOTAL_FRAMES=${TOTAL_FRAMES} TOTAL_DURATION_MS=${TOTAL_DURATION_MS} approx_finish=${finish_ts}"
        else
          log "ETA_HINT: TOTAL_FRAMES=${TOTAL_FRAMES} TOTAL_DURATION_MS=unknown"
        fi
        # start periodic reporter for sequential assembly
        start_periodic_summary "$TMP_DIR/ff_assemble_seq.log" "$TOTAL_FRAMES" 30
        if [ -f "$TMP_DIR/audio.aac" ]; then
          ffmpeg -hide_banner -loglevel info -y -start_number 1 -framerate "$TARGET_FPS" -i "$ASSEM_DIR/frame_%06d.png" -i "$TMP_DIR/audio.aac" -c:v "$FF_ENCODER" $FF_OPTS -shortest "$OUTFILE" 2>&1 | progress_collapse | tee "$TMP_DIR/ff_assemble_seq.log"
        else
          ffmpeg -hide_banner -loglevel info -y -start_number 1 -framerate "$TARGET_FPS" -i "$ASSEM_DIR/frame_%06d.png" -c:v "$FF_ENCODER" $FF_OPTS "$OUTFILE" 2>&1 | progress_collapse | tee "$TMP_DIR/ff_assemble_seq.log"
        fi
        RC_SEQ=${PIPESTATUS[0]:-1}
        stop_periodic_summary || true
        outsiz=$(stat -c %s "$OUTFILE" 2>/dev/null || echo 0)
        if [ $RC_SEQ -eq 0 ] && [ $outsiz -ge $min_size ]; then
          log "OK $OUTFILE (assembled via sequential image list)"
          rm -rf "$ASSEM_DIR" 2>/dev/null || true
          maybe_upload_and_finish "$OUTFILE" || exit 0
        else
          log "Sequential assembly also failed (rc=$RC_SEQ size=$outsiz < $min_size or empty); see $TMP_DIR/ff_assemble_seq.log for details"
        fi
      fi
      # fall through to original minterpolate fallback
    fi
  fi
fi

# Fallback: ffmpeg minterpolate CPU
log "FALLBACK: ffmpeg minterpolate -> $OUTFILE"
# Export TOTAL_DURATION_MS based on input duration so ETA can be calculated (interpolation preserves duration)
DUR_SEC=$(ffprobe -v error -show_entries format=duration -of default=noprint_wrappers=1:nokey=1 "$INFILE" 2>/dev/null || echo 0)
if [ -z "$DUR_SEC" ]; then DUR_SEC=0; fi
TOTAL_DURATION_MS=$(awk -v d="$DUR_SEC" 'BEGIN{ printf "%d", (d*1000) }')
export TOTAL_DURATION_MS
if [ -n "${TOTAL_DURATION_MS:-}" ] && [ "$TOTAL_DURATION_MS" -gt 0 ]; then
  now_s=$(date +%s)
  finish_s=$((now_s + TOTAL_DURATION_MS/1000))
  finish_ts=$(date -d "@${finish_s}" '+%H:%M:%S' 2>/dev/null || date -r ${finish_s} '+%H:%M:%S' 2>/dev/null || echo "unknown")
  log "ETA_HINT: TOTAL_DURATION_MS=${TOTAL_DURATION_MS} approx_finish=${finish_ts} (based on input duration)"
else
  log "ETA_HINT: TOTAL_DURATION_MS=unknown"
fi
start_periodic_summary "$TMP_DIR/ff_fallback.log" "${TOTAL_FRAMES:-0}" 30
ffmpeg -hide_banner -loglevel info -y -i "$INFILE" -vf "minterpolate=fps=$TARGET_FPS:mi_mode=mci:mc_mode=aobmc:me_mode=bidir:vsbmc=1" -pix_fmt yuv420p -c:v "$FF_ENCODER" $FF_OPTS "$OUTFILE" 2>&1 | progress_collapse | tee "$TMP_DIR/ff_fallback.log"
stop_periodic_summary || true

if [ -s "$OUTFILE" ]; then
  log "Success: $OUTFILE"
  # One-shot forced upload helper: if enabled, run scripts/force_upload_and_fail.sh once and exit with its code.
  # Enable by setting FORCE_UPLOAD_ON_NEXT_RUN=1 in the job environment. A marker file /workspace/.force_upload_ran
  # prevents this from running more than once.
  if [ "${FORCE_UPLOAD_ON_NEXT_RUN:-0}" = "1" ] && [ ! -f /workspace/.force_upload_ran ]; then
    log "FORCE_UPLOAD_ON_NEXT_RUN enabled -> running force_upload_and_fail.sh (one-shot)"
    # Export B2 vars if provided by the job (B2_OUTPUT_KEY preferred for key)
    export B2_KEY="${B2_OUTPUT_KEY:-${B2_KEY:-}}"
    export B2_BUCKET="${B2_BUCKET:-}"
    export FORCE_FILE="${FORCE_FILE:-$OUTFILE}"
    # create marker to avoid re-running on retries
    touch /workspace/.force_upload_ran 2>/dev/null || true
    /workspace/project/scripts/force_upload_and_fail.sh
    rc=$?
    log "force_upload_and_fail.sh exited with rc=$rc"
    # Propagate its exit code so the container job fails as intended
    exit $rc
  fi
  maybe_upload_and_finish "$OUTFILE" || exit 0
 else
   log "Failed to produce output"
   tail -n 200 "$TMP_DIR/ff_fallback.log" 2>/dev/null || true
   exit 5
 fi

