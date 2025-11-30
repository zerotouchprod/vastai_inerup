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

progress_collapse(){
  python3 -u - <<'PY'
import sys,time
kv={}
order=[]
for raw in sys.stdin:
    line=raw.strip()
    if not line or '=' not in line: continue
    k,v=line.split('=',1)
    if k not in order: order.append(k)
    kv[k]=v
    if k=='progress':
        parts=[f"{k}={kv.get(k,'')}" for k in order if k!='progress']
        parts.append(f"progress={kv.get('progress','')}")
        print(f"[{time.strftime('%H:%M:%S')}] "+' '.join(parts), flush=True)
        kv.clear(); order=[]
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
        if [ -f "$TMP_DIR/audio.aac" ]; then
          ffmpeg -hide_banner -loglevel info -y -start_number $start_number -framerate "$TARGET_FPS" -i "$pattern" -i "$TMP_DIR/audio.aac" -c:v libx264 -crf 18 -preset medium -pix_fmt yuv420p -shortest "$OUTFILE" 2>&1 | progress_collapse | tee "$TMP_DIR/ff_assemble.log"
        else
          ffmpeg -hide_banner -loglevel info -y -start_number $start_number -framerate "$TARGET_FPS" -i "$pattern" -c:v libx264 -crf 18 -preset medium -pix_fmt yuv420p "$OUTFILE" 2>&1 | progress_collapse | tee "$TMP_DIR/ff_assemble.log"
        fi
        rc=${PIPESTATUS[0]:-1}
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
  if [ -f "$TMP_DIR/audio.aac" ]; then
    ffmpeg -hide_banner -loglevel info -y -f concat -safe 0 -i "$FL" -framerate "$TARGET_FPS" -i "$TMP_DIR/audio.aac" -c:v libx264 -crf 18 -preset medium -pix_fmt yuv420p -shortest "$OUTFILE" 2>&1 | progress_collapse | tee "$TMP_DIR/ff_assemble.log"
  else
    ffmpeg -hide_banner -loglevel info -y -f concat -safe 0 -i "$FL" -framerate "$TARGET_FPS" -c:v libx264 -crf 18 -preset medium -pix_fmt yuv420p "$OUTFILE" 2>&1 | progress_collapse | tee "$TMP_DIR/ff_assemble.log"
  fi
  rc=${PIPESTATUS[0]:-1}
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
    # Run ffmpeg using concat filelist (preserve TARGET_FPS)
    if [ -f "$TMP_DIR/audio.aac" ]; then
      ffmpeg -hide_banner -loglevel info -y -f concat -safe 0 -i "$FL" -framerate "$TARGET_FPS" -i "$TMP_DIR/audio.aac" -c:v libx264 -crf 18 -preset medium -pix_fmt yuv420p -shortest "$OUTFILE" 2>&1 | progress_collapse | tee "$TMP_DIR/ff_assemble_mid.log"
    else
      ffmpeg -hide_banner -loglevel info -y -f concat -safe 0 -i "$FL" -framerate "$TARGET_FPS" -c:v libx264 -crf 18 -preset medium -pix_fmt yuv420p "$OUTFILE" 2>&1 | progress_collapse | tee "$TMP_DIR/ff_assemble_mid.log"
    fi
    RC_ASM=${PIPESTATUS[0]:-1}
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
        if [ -f "$TMP_DIR/audio.aac" ]; then
          ffmpeg -hide_banner -loglevel info -y -start_number 1 -framerate "$TARGET_FPS" -i "$ASSEM_DIR/frame_%06d.png" -i "$TMP_DIR/audio.aac" -c:v libx264 -crf 18 -preset medium -pix_fmt yuv420p -shortest "$OUTFILE" 2>&1 | progress_collapse | tee "$TMP_DIR/ff_assemble_seq.log"
        else
          ffmpeg -hide_banner -loglevel info -y -start_number 1 -framerate "$TARGET_FPS" -i "$ASSEM_DIR/frame_%06d.png" -c:v libx264 -crf 18 -preset medium -pix_fmt yuv420p "$OUTFILE" 2>&1 | progress_collapse | tee "$TMP_DIR/ff_assemble_seq.log"
        fi
        RC_SEQ=${PIPESTATUS[0]:-1}
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
ffmpeg -hide_banner -loglevel info -y -i "$INFILE" -vf "minterpolate=fps=$TARGET_FPS:mi_mode=mci:mc_mode=aobmc:me_mode=bidir:vsbmc=1" -pix_fmt yuv420p -c:v libx264 -crf 18 -preset medium "$OUTFILE" 2>&1 | progress_collapse | tee "$TMP_DIR/ff_fallback.log"

if [ -s "$OUTFILE" ]; then
  log "Success: $OUTFILE"
  maybe_upload_and_finish "$OUTFILE" || exit 0
else
  log "Failed to produce output"
  tail -n 200 "$TMP_DIR/ff_fallback.log" 2>/dev/null || true
  exit 5
fi

