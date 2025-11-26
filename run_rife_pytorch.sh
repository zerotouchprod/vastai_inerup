#!/usr/bin/env bash
# Wrapper to run RIFE (PyTorch) if available in /workspace/project/external/RIFE
# Note: NOT using set -e to allow fallback methods when inference_video.py fails
# Usage: run_rife_pytorch.sh <input> <output> <factor:int (default 2)>

# Function to print with timestamp
log() {
    echo "[$(date '+%H:%M:%S')] $*"
}

# Debug-print wrapper - only prints when VERBOSE is set to 1 (reduces spam and large dumps)
log_debug() {
    if [ "${VERBOSE:-0}" = "1" ]; then
        echo "[$(date '+%H:%M:%S')] $*"
    fi
}

INFILE=${1:-}
OUTFILE=${2:-}
FACTOR=${3:-2}

if [ -z "$INFILE" ] || [ -z "$OUTFILE" ]; then
  log "Usage: $0 <input-file> <output-file> <factor:int (default 2)>"
  exit 2
fi

REPO_DIR="/workspace/project/external/RIFE"
if [ ! -d "$REPO_DIR" ]; then
  log "RIFE repo not found in $REPO_DIR. Place RIFE cloned repo there or adjust Dockerfile.pytorch to clone it."
  exit 3
fi

# RIFE will auto-download models on first run if they don't exist
# Just ensure the train_log directory exists
mkdir -p "$REPO_DIR/train_log"

# Helper: check if dir contains model files
shopt -s nullglob || true
has_models() {
  local d="$1"
  local files=("$d"/*.pkl "$d"/*.pt "$d"/*.pth "$d"/*.bin)
  if [ ${#files[@]} -gt 0 ]; then
    return 0
  else
    return 1
  fi
}

# Debug: print contents of possible model locations and env vars to help diagnostics
log_debug "[debug] STRICT=${STRICT:-<unset>} RIFE_MODEL_URL=${RIFE_MODEL_URL:-<unset>}"
if [ -d "/opt/rife_models" ]; then
  log_debug "[debug] /opt/rife_models exists, listing (top 10):"
  ls -la /opt/rife_models | head -n 20 || true
else
  log_debug "[debug] /opt/rife_models does NOT exist"
fi
if [ -d "/opt/rife_models/train_log" ]; then
  log_debug "[debug] /opt/rife_models/train_log exists, listing (top 10):"
  ls -la /opt/rife_models/train_log | head -n 20 || true
else
  log_debug "[debug] /opt/rife_models/train_log does NOT exist"
fi
if [ -d "$REPO_DIR/train_log" ]; then
  log_debug "[debug] $REPO_DIR/train_log contents (sample):"
  ls -lh "$REPO_DIR/train_log" | head -n 20 || true
else
  log_debug "[debug] $REPO_DIR/train_log does NOT exist (unexpected)"
fi

# If models don't exist, copy from preinstalled location
if ! has_models "$REPO_DIR/train_log"; then
  log "RIFE models not found in train_log, copying from preinstalled location..."

  if [ -d "/opt/rife_models/train_log" ] && has_models "/opt/rife_models/train_log"; then
    mkdir -p "$REPO_DIR/train_log"
    cp -r /opt/rife_models/train_log/* "$REPO_DIR/train_log/"
    log "RIFE model copied successfully (sample listing):"
    ls -lh "$REPO_DIR/train_log" | head -n 20 || true
  else
    log "ERROR: Preinstalled RIFE model not found at /opt/rife_models/train_log/"
    log "Image may need to be rebuilt with RIFE_trained_model_v3.6 included"

    # Check STRICT mode - if false, allow fallback to other methods
    if [ "${STRICT:-false}" = "true" ]; then
      log "STRICT mode enabled — aborting."
      exit 3
    else
      log "Non-strict mode — will exit and allow pipeline to fallback to NCNN/FFmpeg."
      exit 3
    fi
  fi
fi

# If available, collapse ffmpeg -progress key=value blocks into one-line summaries for cleaner logs
progress_collapse() {
  python3 -u - <<'PY'
import sys, time
kv = {}
order = []
for raw in sys.stdin:
    line = raw.strip()
    if not line or '=' not in line:
        continue
    k, v = line.split('=', 1)
    if k not in order:
        order.append(k)
    kv[k] = v
    if k == 'progress':
        parts = [f"{key}={kv.get(key,'')}" for key in order if key != 'progress']
        parts.append(f"progress={kv.get('progress','')}")
        ts = time.strftime('%H:%M:%S')
        print(f"[{ts}] " + ' '.join(parts), flush=True)
        kv.clear()
        order = []
PY
}

# Global helper: deterministic filelist-based assembly usable anywhere in the script
try_filelist_assembly() {
  local src_dir="$1"
  local out_file="$2"
  local fr="$3"
  local flist
  flist="${TMP_DIR:-/tmp}/filelist.txt"
  rm -f "$flist" || true
  (for f in "$src_dir"/*.png; do [ -f "$f" ] || continue; echo "file '$f'"; done) >"$flist"
  if [ ! -s "$flist" ]; then
    return 1
  fi
  log "Using filelist concat assembly (first lines):"
  head -n 20 "$flist" || true
  if [ -f "${TMP_DIR:-/tmp}/audio.aac" ]; then
    (ffmpeg -hide_banner -loglevel info -progress pipe:1 -nostats -y -f concat -safe 0 -i "$flist" -framerate "$fr" -i "${TMP_DIR:-/tmp}/audio.aac" -c:v libx264 -crf 18 -preset medium -pix_fmt yuv420p -c:a aac -shortest "$out_file" 2>&1 | progress_collapse) | tee "${ASM_LOG:-/tmp/batch_assemble.log}"
    return ${PIPESTATUS[0]:-1}
  else
    (ffmpeg -hide_banner -loglevel info -progress pipe:1 -nostats -y -f concat -safe 0 -i "$flist" -framerate "$fr" -c:v libx264 -crf 18 -preset medium -pix_fmt yuv420p "$out_file" 2>&1 | progress_collapse) | tee "${ASM_LOG:-/tmp/batch_assemble.log}"
    return ${PIPESTATUS[0]:-1}
  fi
}

# Frame-by-frame interpolation method (reliable, doesn't require scikit-video)
if [ -f "$REPO_DIR/inference_img.py" ] || [ -f "/workspace/project/rife_interpolate_direct.py" ]; then
  log "Using frame-by-frame RIFE interpolation (factor: $FACTOR)"
  log "Note: inference_video.py disabled (requires unmaintained scikit-video library)"
  echo ""

  # Convert paths to absolute
  INFILE_ABS=$(python3 -c "import os,sys; print(os.path.abspath(sys.argv[1]))" "$INFILE")
  OUTFILE_ABS=$(python3 -c "import os,sys; print(os.path.abspath(sys.argv[1]))" "$OUTFILE")

  INPUT_VIDEO_PATH="$INFILE_ABS"
  OUTPUT_VIDEO_PATH="$OUTFILE_ABS"

  if [ ! -f "$INPUT_VIDEO_PATH" ]; then
    log "ERROR: Input file does not exist: $INPUT_VIDEO_PATH"
    exit 4
  fi

  # Ensure output directory exists
  OUTFILE_DIR=$(dirname "$OUTPUT_VIDEO_PATH")
  mkdir -p "$OUTFILE_DIR"

  log "Input file: $INPUT_VIDEO_PATH"
  log "Output file: $OUTPUT_VIDEO_PATH"
  echo ""

  # Clean up any existing output file to prevent overwrite prompts
  if [ -f "$OUTPUT_VIDEO_PATH" ]; then
    log "Removing existing output file: $OUTPUT_VIDEO_PATH"
    rm -f "$OUTPUT_VIDEO_PATH"
  fi

  # Create temp directory with disk-space check and fallback locations
  TMP_BASE="/tmp"
  MIN_KB=$((200*1024))  # require at least ~200MB free by default
  avail_kb=$(df -k "$TMP_BASE" 2>/dev/null | awk 'END{print $4}')
  if [ -z "$avail_kb" ] || [ "$avail_kb" -lt "$MIN_KB" ]; then
    log "Warning: low free space on $TMP_BASE (available KB: ${avail_kb:-unknown}), trying fallback locations..."
    if [ -d "/workspace" ]; then
      TMP_BASE="/workspace"
    elif [ -d "/var/tmp" ]; then
      TMP_BASE="/var/tmp"
    fi
  fi

  # Try to create temp dir under TMP_BASE; if mktemp with template fails, fallback to plain mktemp
  TMP_DIR=""
  if mkdir -p "$TMP_BASE" 2>/dev/null; then
    TMP_DIR=$(mktemp -d "$TMP_BASE/rife_tmp.XXXXXX" 2>/dev/null || true)
  fi
  if [ -z "$TMP_DIR" ]; then
    TMP_DIR=$(mktemp -d 2>/dev/null || true)
  fi
  if [ -z "$TMP_DIR" ] || [ ! -d "$TMP_DIR" ]; then
    log "ERROR: Failed to create temporary directory (tried: $TMP_BASE and default). Aborting."
    exit 4
  fi
  log "Created temp directory: $TMP_DIR (base: $TMP_BASE)"

  # Create a standalone try_filelist_assembly helper in TMP_DIR to avoid scope/function issues
  cat > "$TMP_DIR/try_filelist_assembly.sh" <<'PY'
#!/usr/bin/env bash
SRC_DIR="$1"
OUT_FILE="$2"
FR="$3"
FLIST="$TMP_DIR/filelist.txt"
rm -f "$FLIST" || true
for f in "$SRC_DIR"/*.png; do
  [ -f "$f" ] || continue
  echo "file '$f'"
done >"$FLIST"
if [ ! -s "$FLIST" ]; then
  exit 1
fi
# print head for remote debugging
head -n 20 "$FLIST" || true
if [ -f "$TMP_DIR/audio.aac" ]; then
  ffmpeg -hide_banner -loglevel info -progress pipe:1 -nostats -y -f concat -safe 0 -i "$FLIST" -framerate "$FR" -i "$TMP_DIR/audio.aac" -c:v libx264 -crf 18 -preset medium -pix_fmt yuv420p -c:a aac -shortest "$OUT_FILE"
  exit $?
else
  ffmpeg -hide_banner -loglevel info -progress pipe:1 -nostats -y -f concat -safe 0 -i "$FLIST" -framerate "$FR" -c:v libx264 -crf 18 -preset medium -pix_fmt yuv420p "$OUT_FILE"
  exit $?
fi
PY
  chmod +x "$TMP_DIR/try_filelist_assembly.sh" || true

  # Get original FPS and calculate target FPS
  log "Getting video FPS..."
  FPS_FRAC=$(ffprobe -v error -select_streams v:0 -show_entries stream=r_frame_rate -of default=noprint_wrappers=1:nokey=1 "$INPUT_VIDEO_PATH" 2>/dev/null | head -1)
  if [ -z "$FPS_FRAC" ]; then
    log "WARNING: Could not detect FPS, using default 24"
    ORIG_FPS="24"
  else
    ORIG_FPS=$(echo "$FPS_FRAC" | awk -F'/' '{if (NF==2) print $1/$2; else print $1}')
  fi
  TARGET_FPS=$(echo "$ORIG_FPS $FACTOR" | awk '{print $1 * $2}')

  log "Original FPS: $ORIG_FPS, Target FPS: $TARGET_FPS, Factor: $FACTOR"

  # Extract frames
  log "Extracting frames..."
  mkdir -p "$TMP_DIR/input" "$TMP_DIR/output"

  # Force 8-bit RGB frames to avoid dtype issues (e.g., numpy.uint16) in RIFE inference
  # Pad frames to next multiple of 64 (width/height) to satisfy some RIFE HD models which expect dims divisible by 64
  # Robust expression using if(mod(...)) to avoid negative-mod behavior
  ffmpeg -hide_banner -loglevel info -progress pipe:1 -nostats -i "$INPUT_VIDEO_PATH" -map 0:v:0 -vsync 0 -start_number 1 \
    -vf "pad=if(mod(iw\,64),iw+(64-mod(iw\,64)),iw):if(mod(ih\,64),ih+(64-mod(ih\,64)),ih)" \
    -pix_fmt rgb24 -f image2 -vcodec png "$TMP_DIR/input/frame_%06d.png" 2>&1 | tee "$TMP_DIR/ff_extract.log" | progress_collapse
   if [ $? -ne 0 ]; then
     log "ERROR: Failed to extract frames"
     log "ffmpeg extraction log (tail 200 lines):"
     tail -n 200 "$TMP_DIR/ff_extract.log" 2>/dev/null || true
     rm -rf "$TMP_DIR"
     exit 4
   fi

  # Wait up to 10s for extracted PNGs to appear (some FS/ffmpeg edgecases may delay visibility)
  FOUND=0
  for try in 1 2 3 4 5 6 7 8 9 10; do
    COUNT=$(ls -1 "$TMP_DIR/input"/*.png 2>/dev/null | wc -l || true)
    if [ "$COUNT" -gt 0 ]; then
      FOUND=1
      break
    fi
    log "Waiting for frames to appear in $TMP_DIR/input (attempt $try): currently $COUNT files"
    ls -la "$TMP_DIR/input" | head -n 50 || true
    sleep 1
  done
  if [ "$FOUND" -eq 0 ]; then
    log "ERROR: No frames became visible in $TMP_DIR/input after extraction"
    ls -la "$TMP_DIR" || true
    log "ffmpeg extraction log (tail 200 lines):"
    tail -n 200 "$TMP_DIR/ff_extract.log" 2>/dev/null || true
    # Try a single-frame extraction with alternative command and log outputs to help debug
    log "Attempting single-frame extraction test into $TMP_DIR/input/frame_test_000001.png"
    ffmpeg -hide_banner -loglevel info -i "$INPUT_VIDEO_PATH" -frames:v 1 -f image2 -vcodec png "$TMP_DIR/input/frame_test_000001.png" 2>&1 | tee "$TMP_DIR/ff_test_extract.log" | progress_collapse
    log "Single-frame extraction log (tail 200 lines):"
    tail -n 200 "$TMP_DIR/ff_test_extract.log" 2>/dev/null || true
    if [ -f "$TMP_DIR/input/frame_test_000001.png" ]; then
      log "Test frame created; hexdump first 128 bytes:"
      hexdump -C -n 128 "$TMP_DIR/input/frame_test_000001.png" | sed -n '1,20p' || true
      file "$TMP_DIR/input/frame_test_000001.png" || true
    else
      log "Test frame was NOT created — ffmpeg cannot write PNGs; check ffmpeg build and container permissions"
    fi
    rm -rf "$TMP_DIR"
    exit 4
  fi

  # Ensure readable permissions for downstream processes
  chmod a+r "$TMP_DIR/input"/*.png 2>/dev/null || true

  # Post-extraction diagnostics: list input dir and inspect first frame header
  log "Post-extract listing of $TMP_DIR/input (first 200 entries):"
  ls -la "$TMP_DIR/input" | head -n 200 || true
  if [ -f "$TMP_DIR/input/frame_000001.png" ]; then
    log "Showing hexdump of first frame (first 128 bytes):"
    hexdump -C -n 128 "$TMP_DIR/input/frame_000001.png" | sed -n '1,20p' || true
    if command -v file >/dev/null 2>&1; then
      file "$TMP_DIR/input/frame_000001.png" || true
    fi
  else
    log "No frame_000001.png found after extraction (unexpected)"
  fi

  # Quick CV2 sanity check: try to read the first extracted PNG using OpenCV inside python.
  if [ -f "$TMP_DIR/input/frame_000001.png" ]; then
    python3 - <<'PY' >"$TMP_DIR/cv_read_check.log" 2>&1
import cv2,sys
img=cv2.imread(sys.argv[1], cv2.IMREAD_UNCHANGED)
print('cv2_read_ok', img is not None)
if img is None:
    sys.exit(2)
sys.exit(0)
PY
    if [ $? -ne 0 ]; then
      log "CV2 failed to read extracted PNGs; attempting fallback extraction to JPEG frames"
      # cleanup previous frames and re-extract as JPEG
      rm -f "$TMP_DIR/input"/* 2>/dev/null || true
      ffmpeg -hide_banner -loglevel info -progress pipe:1 -nostats -i "$INPUT_VIDEO_PATH" -map 0:v:0 -vsync 0 -start_number 1 \
        -vf "pad=if(mod(iw\,64),iw+(64-mod(iw\,64)),iw):if(mod(ih\,64),ih+(64-mod(ih\,64)),ih)" \
        -pix_fmt yuvj420p -f image2 -vcodec mjpeg "$TMP_DIR/input/frame_%06d.jpg" 2>&1 | tee "$TMP_DIR/ff_extract_jpg.log" | progress_collapse || true
      # Wait briefly for files
      sleep 1
      COUNTJPG=$(ls -1 "$TMP_DIR/input"/*.jpg 2>/dev/null | wc -l || true)
      log "JPEG re-extraction produced $COUNTJPG files"
      if [ "$COUNTJPG" -gt 0 ]; then
        # ensure readable
        chmod a+r "$TMP_DIR/input"/*.jpg 2>/dev/null || true
      else
        log "JPEG re-extraction failed; see $TMP_DIR/ff_extract_jpg.log"
      fi
    else
      log "CV2 read test passed for first PNG"
    fi
  fi

  # Count frames
  FRAME_COUNT=$(ls -1 "$TMP_DIR/input"/*.png 2>/dev/null | wc -l)
  log "Extracted $FRAME_COUNT frames"

  if [ $FRAME_COUNT -eq 0 ]; then
    log "ERROR: No frames extracted"
    rm -rf "$TMP_DIR"
    exit 4
  fi

  # Extract audio track
  log "Extracting audio track..."
  # Extract audio with progress reporting (small, but keeps logs consistent)
  AUDIO_RESULT=$(ffmpeg -hide_banner -loglevel info -progress pipe:1 -nostats -i "$INPUT_VIDEO_PATH" -vn -acodec copy "$TMP_DIR/audio.aac" 2>&1 | progress_collapse)
   AUDIO_EXIT=$?
   if [ $AUDIO_EXIT -ne 0 ]; then
     log "Audio extraction failed (exit code: $AUDIO_EXIT)"
     log "Will proceed without audio"
     rm -f "$TMP_DIR/audio.aac"
   elif [ ! -s "$TMP_DIR/audio.aac" ]; then
     log "Audio extraction produced empty file"
     log "Will proceed without audio"
     rm -f "$TMP_DIR/audio.aac"
   else
     log "Audio extracted successfully"
   fi

  # Test which interpolation method works
  log "Testing interpolation methods..."
  echo ""

  # If RIFE scripts aren't present or direct invocation fails, fall back to ffmpeg minterpolate
  log "Attempting to run RIFE PyTorch interpolation if available, otherwise fallback to ffmpeg minterpolate"

  # Prefer repository provided direct interpolation script if exists
  if [ -f "$REPO_DIR/rife_interpolate_direct.py" ]; then
    log "Found rife_interpolate_direct.py — attempting direct interpolation"
    PYTHONPATH="$REPO_DIR:$PYTHONPATH" python3 "$REPO_DIR/rife_interpolate_direct.py" "$TMP_DIR/input" "$TMP_DIR/output" --factor "$FACTOR" || true
  fi

  # Attempt batch-runner: a single Python process that loads model once and processes all pairs.
  BATCH_OK=0
  if command -v python3 >/dev/null 2>&1; then

    # Diagnostic logging to help remote debugging when user can't access container
    log "[debug] Python version: $(python3 --version 2>&1 || true)"
    log "[debug] pip packages (top 20):"
    (python3 -m pip list --format=columns 2>/dev/null | head -n 20) || true
    # environment hints
    log "[debug] Relevant env vars:"
    env | grep -E 'CUDA|CUDA_HOME|LD_LIBRARY_PATH|TORCH|PYTHON' | head -n 50 || true

    # Minimized debug: indicate whether inference_img.py exists (suppress large file listings)
    if [ -f "$REPO_DIR/inference_img.py" ]; then
      log_debug "[debug] inference_img.py found"
    else
      log_debug "[debug] inference_img.py NOT found in $REPO_DIR"
    fi

    # If available, use stdbuf to force line buffering for Python processes (helps in some container log collectors)
    if command -v stdbuf >/dev/null 2>&1; then
      STDOUT_WRAP="stdbuf -oL"
    else
      STDOUT_WRAP=""
    fi

    # Prefer an external batch_rife.py file (easier to edit / test). Check several likely locations and copy
    BATCH_SRC=""
    if [ -f "$REPO_DIR/../batch_rife.py" ]; then
      BATCH_SRC="$REPO_DIR/../batch_rife.py"
    elif [ -f "$REPO_DIR/batch_rife.py" ]; then
      BATCH_SRC="$REPO_DIR/batch_rife.py"
    elif [ -f "/workspace/project/batch_rife.py" ]; then
      BATCH_SRC="/workspace/project/batch_rife.py"
    fi
    if [ -n "$BATCH_SRC" ]; then
      log "Using external batch_rife.py from: $BATCH_SRC"
      cp "$BATCH_SRC" "$TMP_DIR/batch_rife.py" || true
    else
      log "No external batch_rife.py found in expected locations — skipping batch-runner creation"
    fi

    # run batch script
    PYTHONPATH="$REPO_DIR:$PYTHONPATH" $STDOUT_WRAP env PYTHONUNBUFFERED=1 python3 "$TMP_DIR/batch_rife.py" "$TMP_DIR/input" "$TMP_DIR/output" "$FACTOR" 2>&1 | tee "$TMP_DIR/batch_rife_run.log" || true
    # Consider batch successful ONLY if output PNGs were created (count them explicitly)
    PNG_COUNT=$(find "$TMP_DIR/output" -maxdepth 1 -type f -iname '*.png' -print | wc -l 2>/dev/null || true)
    if [ -n "$PNG_COUNT" ] && [ "$PNG_COUNT" -gt 0 ]; then
      BATCH_OK=1
      log "Batch-runner produced $PNG_COUNT outputs (sample): $(find "$TMP_DIR/output" -maxdepth 1 -type f -iname '*.png' -printf '%f\n' | head -n 5 | tr '\n' ',')"
      # Attempt to assemble produced frames into the final video now (avoid falling back to ffmpeg minterpolate)
      log "Attempting to assemble batch-produced frames into $OUTPUT_VIDEO_PATH"
      FRAMERATE="$TARGET_FPS"
      # Try assembly using candidate patterns in order: *_mid -> *_out -> frame_*.png -> glob
      ASM_LOG="/tmp/batch_assemble.log"
      rm -f "$ASM_LOG" || true
      # Ensure a reusable filelist-based assembly function is defined (global scope)
      try_filelist_assembly() {
        local src_dir="$1"
        local out_file="$2"
        local fr="$3"
        local flist="$TMP_DIR/filelist.txt"
        rm -f "$flist" || true
        # create filelist with explicit ordering
        (for f in "$src_dir"/*.png; do [ -f "$f" ] || continue; echo "file '$f'"; done) >"$flist"
        if [ ! -s "$flist" ]; then
          return 1
        fi
        log "Using filelist concat assembly (first lines):"
        head -n 20 "$flist" || true
        if [ -f "$TMP_DIR/audio.aac" ]; then
          (ffmpeg -hide_banner -loglevel info -progress pipe:1 -nostats -y -f concat -safe 0 -i "$flist" -framerate "$fr" -i "$TMP_DIR/audio.aac" -c:v libx264 -crf 18 -preset medium -pix_fmt yuv420p -c:a aac -shortest "$out_file" 2>&1 | progress_collapse) | tee "$ASM_LOG"
          return ${PIPESTATUS[0]:-1}
        else
          (ffmpeg -hide_banner -loglevel info -progress pipe:1 -nostats -y -f concat -safe 0 -i "$flist" -framerate "$fr" -c:v libx264 -crf 18 -preset medium -pix_fmt yuv420p "$out_file" 2>&1 | progress_collapse) | tee "$ASM_LOG"
          return ${PIPESTATUS[0]:-1}
        fi
      }
      ASM_RC=1
      CHOSEN_PATTERN=""
      # helper to run ffmpeg with/without audio
      run_ffmpeg_pattern() {
         local pattern="$1"
         if [ -f "$TMP_DIR/audio.aac" ]; then
           # Pipe ffmpeg progress through collapse filter and tee to ASM_LOG
           (ffmpeg -hide_banner -loglevel info -progress pipe:1 -nostats -v warning -y -framerate "$FRAMERATE" -i "$pattern" -i "$TMP_DIR/audio.aac" -c:v libx264 -crf 18 -preset medium -pix_fmt yuv420p -c:a aac -shortest "$OUTPUT_VIDEO_PATH" 2>&1 | progress_collapse) | tee "$ASM_LOG"
           return ${PIPESTATUS[0]:-1}
         else
           (ffmpeg -hide_banner -loglevel info -progress pipe:1 -nostats -v warning -y -framerate "$FRAMERATE" -i "$pattern" -c:v libx264 -crf 18 -preset medium -pix_fmt yuv420p "$OUTPUT_VIDEO_PATH" 2>&1 | progress_collapse) | tee "$ASM_LOG"
           return ${PIPESTATUS[0]:-1}
         fi
         return $?
       }

      # 1) *_mid.png
      if find "$TMP_DIR/output" -maxdepth 1 -type f -iname '*_mid.png' -print -quit >/dev/null 2>&1; then
        # Build interleaved sequence: input frame1, mid(s)1, input frame2, mid(s)2, ...
        ASMDIR="$TMP_DIR/assembled"
        rm -rf "$ASMDIR" || true
        mkdir -p "$ASMDIR" || true
        NUM_IN=$(ls -1 "$TMP_DIR/input"/*.png 2>/dev/null | wc -l || true)
        idx=1
        if [ "$NUM_IN" -gt 0 ]; then
          i=1
          while [ $i -le $NUM_IN ]; do
            src_in="$TMP_DIR/input/$(printf 'frame_%06d.png' $i)"
            if [ -f "$src_in" ]; then
              dst="$ASMDIR/$(printf 'frame_%06d.png' $idx)"
              cp -f "$src_in" "$dst" || true
              idx=$((idx+1))
            fi
            # copy any mids for this pair, support both frame_x_mid.png and frame_x_mid_01.png variants
            mid_pattern="$TMP_DIR/output/$(printf 'frame_%06d' "$i")_mid"*
            for midf in $mid_pattern; do
              [ -f "$midf" ] || continue
              dst="$ASMDIR/$(printf 'frame_%06d.png' $idx)"
              cp -f "$midf" "$dst" || true
              idx=$((idx+1))
            done
            i=$((i+1))
          done
        fi
        CHOSEN_PATTERN="$ASMDIR/frame_%06d.png"
        # Compute assembled framerate and log diagnostics
        ASSEMBLED_COUNT=$(ls -1 "$ASMDIR"/*.png 2>/dev/null | wc -l || true)
        if [ -n "$NUM_IN" ] && [ "$NUM_IN" -gt 0 ] && [ -n "$ASSEMBLED_COUNT" ] && [ "$ASSEMBLED_COUNT" -gt 0 ]; then
          EXPECTED_APPROX=$(awk -v N="$NUM_IN" -v F="$FACTOR" 'BEGIN{printf("%.0f", N*F)}')
          FRAMERATE=$(awk -v orig="$ORIG_FPS" -v assembled="$ASSEMBLED_COUNT" -v num_in="$NUM_IN" -v factor="$FACTOR" 'BEGIN{ if(num_in>0){ expected=int(num_in*factor+0.5); if(assembled >= expected-2 && assembled <= expected+2) printf("%.6f", orig*factor); else printf("%.6f", orig*(assembled/num_in)); } else printf("%.6f", orig*factor) }')
          log "[debug] assembled_count=$ASSEMBLED_COUNT num_in=$NUM_IN expected_approx=$EXPECTED_APPROX framerate=$FRAMERATE"
        else
          FRAMERATE="$TARGET_FPS"
          log "[debug] assembled_count or num_in missing, using FRAMERATE=$FRAMERATE"
        fi
        # ensure FRAMERATE fallback
        FRAMERATE=${FRAMERATE:-$TARGET_FPS}
        # Try deterministic filelist-based assembly first (preferred)
        if "$TMP_DIR/try_filelist_assembly.sh" "$ASMDIR" "$OUTPUT_VIDEO_PATH" "$FRAMERATE"; then
          ASM_RC=0
        else
          run_ffmpeg_pattern "$CHOSEN_PATTERN"; ASM_RC=$?
        fi
      fi
      # 2) *_out.png (if previous didn't work)
      if [ $ASM_RC -ne 0 ] && find "$TMP_DIR/output" -maxdepth 1 -type f -iname '*_out.png' -print -quit >/dev/null 2>&1; then
        CHOSEN_PATTERN="$TMP_DIR/output/frame_%06d_out.png"
        run_ffmpeg_pattern "$CHOSEN_PATTERN"; ASM_RC=$?
      fi
      # 3) frame_*.png
      if [ $ASM_RC -ne 0 ] && find "$TMP_DIR/output" -maxdepth 1 -type f -iname 'frame_*.png' -print -quit >/dev/null 2>&1; then
        CHOSEN_PATTERN="$TMP_DIR/output/frame_%06d.png"
        run_ffmpeg_pattern "$CHOSEN_PATTERN"; ASM_RC=$?
      fi
      # 4) glob as last resort
      if [ $ASM_RC -ne 0 ]; then
        CHOSEN_PATTERN="glob"
        if [ -f "$TMP_DIR/audio.aac" ]; then
          ffmpeg -v warning -y -framerate "$FRAMERATE" -pattern_type glob -i "$TMP_DIR/output/*.png" -i "$TMP_DIR/audio.aac" -c:v libx264 -crf 18 -preset medium -pix_fmt yuv420p -c:a aac -shortest "$OUTPUT_VIDEO_PATH" >"$ASM_LOG" 2>&1
        else
          ffmpeg -v warning -y -framerate "$FRAMERATE" -pattern_type glob -i "$TMP_DIR/output/*.png" -c:v libx264 -crf 18 -preset medium -pix_fmt yuv420p "$OUTPUT_VIDEO_PATH" >"$ASM_LOG" 2>&1
        fi
        ASM_RC=$?
      fi

      if [ $ASM_RC -eq 0 ] && [ -f "$OUTPUT_VIDEO_PATH" ]; then
        log "Assembled video successfully from batch outputs using pattern: $CHOSEN_PATTERN -> $OUTPUT_VIDEO_PATH"
        # Final success
        log "✓ RIFE completed at $(date '+%H:%M:%S')"
        echo ""
        log "Output verified: $OUTPUT_VIDEO_PATH (size: $(stat -c%s "$OUTPUT_VIDEO_PATH") bytes)"
        exit 0
      else
        log "Failed to assemble frames from batch outputs (rc=$ASM_RC). Assembly log follows":
        sed -n '1,200p' "$ASM_LOG" 2>/dev/null || true
        log "Will fallback to existing logic"
      fi
    else
      log "Batch-runner produced no output PNGs (count=$PNG_COUNT); printing batch log (up to 50KB) for debugging:"
      head -c 50000 "$TMP_DIR/batch_rife_run.log" || true
      log "Listing temp dir contents ($TMP_DIR) for debugging (top 200 entries):"
      find "$TMP_DIR" -maxdepth 3 -printf '%s %p\n' 2>/dev/null | sort -rn | head -n 200 || true
    fi
  fi

  # If batch-runner succeeded, skip per-pair external invocations
  if [ "$BATCH_OK" -eq 1 ]; then
    log "Batch-runner succeeded, skipping per-pair subprocess loop"
  else
    log "Batch-runner not available or failed — falling back to per-pair execution"

    # Emit PyTorch/CUDA diagnostic to logs so we can confirm GPU visibility in remote logs
    if command -v python3 >/dev/null 2>&1; then
      PY_TORCH_INFO=$(python3 - <<'PY'
import sys
try:
    import torch
    info = {
        'torch_version': getattr(torch, '__version__', None),
        'cuda_available': torch.cuda.is_available(),
        'cuda_count': torch.cuda.device_count() if torch.cuda.is_available() else 0,
        'cuda_device_name': torch.cuda.get_device_name(0) if torch.cuda.is_available() and torch.cuda.device_count()>0 else None
    }
    print(info)
except Exception as e:
    print({'error': str(e)})
PY
)
      log "[debug] PyTorch runtime: ${PY_TORCH_INFO}"
    else
      log "[debug] python3 not found - cannot check PyTorch/CUDA status"
    fi

    # Run inference per-pair
    if command -v python3 >/dev/null 2>&1; then
      cd "$REPO_DIR" || true
      NUM_FRAMES=$(ls -1 "$TMP_DIR/input"/*.png 2>/dev/null | wc -l)
      log "Running inference_img.py on $NUM_FRAMES frames (pairwise -> $((NUM_FRAMES-1)) pairs)"
      i=1
      while [ $i -lt $NUM_FRAMES ]; do
        a="$TMP_DIR/input/$(printf 'frame_%06d.png' $i)"
        b="$TMP_DIR/input/$(printf 'frame_%06d.png' $((i+1)))"
        out_mid="$TMP_DIR/output/$(printf 'frame_%06d_mid.png' $i)"
        log "RIFE pair #$i: $a $b -> $out_mid"
        PYTHONPATH="$REPO_DIR:$PYTHONPATH" $STDOUT_WRAP env PYTHONUNBUFFERED=1 python3 "$REPO_DIR/inference_img.py" --img "$a" "$b" --ratio 0.5 --model train_log 2>&1 | tee "$TMP_DIR/rife_pair_$i.log" || true

        # Emit the pair log to stdout for remote debugging
        if [ -f "$TMP_DIR/rife_pair_$i.log" ]; then
          echo "--- RIFE pair log: $TMP_DIR/rife_pair_$i.log (start) ---"
          sed -n '1,200p' "$TMP_DIR/rife_pair_$i.log" 2>/dev/null || true
          echo "--- RIFE pair log: $TMP_DIR/rife_pair_$i.log (end) ---"
        fi

        # Try to locate produced mid-frame in common locations and move it to out_mid
        if [ -f "$REPO_DIR/output.png" ]; then
          mv "$REPO_DIR/output.png" "$out_mid" 2>/dev/null || true
        fi
        if [ -f "output.png" ]; then
          mv "output.png" "$out_mid" 2>/dev/null || true
        fi
        cand=$(find "$REPO_DIR" -maxdepth 1 -type f -iname '*mid*.png' -print -quit 2>/dev/null || true)
        if [ -n "$cand" ] && [ ! -f "$out_mid" ]; then
          mv "$cand" "$out_mid" 2>/dev/null || true
        fi
        if [ ! -f "$out_mid" ]; then
          newest=$(find "$REPO_DIR" -maxdepth 2 -type f -iname '*.png' -printf '%T@ %p\n' 2>/dev/null | sort -nr | head -n 1 | awk '{print $2}' || true)
          if [ -n "$newest" ]; then
            mv "$newest" "$out_mid" 2>/dev/null || true
          fi
        fi

        i=$((i+1))
      done
      log "Pairwise inference attempts finished; output dir listing: $(ls -1 "$TMP_DIR/output" | head -n 20 2>/dev/null || true)"
    fi
  fi

  # If no output file was created by the above RIFE attempts, use ffmpeg minterpolate as a robust fallback
  if [ ! -f "$OUTPUT_VIDEO_PATH" ]; then
    log "No RIFE-produced output detected — using ffmpeg minterpolate fallback to generate $OUTPUT_VIDEO_PATH"
    if [ -f "$TMP_DIR/audio.aac" ]; then
      # Use filter_complex and explicit mapping to avoid option ordering issues
      ffmpeg -v warning -y -i "$INPUT_VIDEO_PATH" -i "$TMP_DIR/audio.aac" \
        -filter_complex "[0:v]minterpolate=fps=$TARGET_FPS:mi_mode=mci:mc_mode=aobmc:me_mode=bidir:vsbmc=1[v]" \
        -map "[v]" -map 1:a -c:v libx264 -crf 18 -preset medium -pix_fmt yuv420p -c:a aac -shortest "$OUTPUT_VIDEO_PATH"
    else
      ffmpeg -v warning -y -i "$INPUT_VIDEO_PATH" \
        -filter_complex "[0:v]minterpolate=fps=$TARGET_FPS:mi_mode=mci:mc_mode=aobmc:me_mode=bidir:vsbmc=1[v]" \
        -map "[v]" -c:v libx264 -crf 18 -preset medium -pix_fmt yuv420p "$OUTPUT_VIDEO_PATH"
    fi
    if [ $? -ne 0 ]; then
      log "ERROR: ffmpeg minterpolate fallback failed"
      rm -rf "$TMP_DIR"
      exit 4
    fi
  fi

  # If RIFE produced frames in TMP_DIR/output but didn't assemble final video, try to assemble now
  if [ ! -f "$OUTPUT_VIDEO_PATH" ] && [ -d "$TMP_DIR/output" ]; then
    # Check for output PNGs
    if ls "$TMP_DIR/output"/*.png >/dev/null 2>&1; then
      log "Found processed frames in $TMP_DIR/output — attempting to assemble into $OUTPUT_VIDEO_PATH"

      # Prefer *_out.png pattern (common in Real-ESRGAN/RIFE outputs), else use frame_ pattern, else glob
      if ls "$TMP_DIR/output"/*_out.png >/dev/null 2>&1; then
        IN_PATTERN="$TMP_DIR/output/frame_%06d_out.png"
        log "Using frame pattern: frame_%06d_out.png"
        FRAMERATE="$TARGET_FPS"
        # ensure FRAMERATE is set (avoid empty value causing ffmpeg to fail)
        FRAMERATE=${FRAMERATE:-$TARGET_FPS}
        # helper: try assembly using explicit filelist for deterministic ordering
        try_filelist_assembly() {
          local src_dir="$1"
          local out_file="$2"
          local fr="$3"
          local flist="$TMP_DIR/filelist.txt"
          rm -f "$flist" || true
          # create filelist with explicit ordering
          (for f in "$src_dir"/*.png; do [ -f "$f" ] || continue; echo "file '$f'"; done) >"$flist"
          if [ ! -s "$flist" ]; then
            return 1
          fi
          log "Using filelist concat assembly (first lines):"; head -n 20 "$flist" || true
          if [ -f "$TMP_DIR/audio.aac" ]; then
            ffmpeg -hide_banner -loglevel info -progress pipe:1 -nostats -y -f concat -safe 0 -i "$flist" -framerate "$fr" -i "$TMP_DIR/audio.aac" -c:v libx264 -crf 18 -preset medium -pix_fmt yuv420p -c:a aac -shortest "$out_file" >"$ASM_LOG" 2>&1
          else
            ffmpeg -hide_banner -loglevel info -progress pipe:1 -nostats -y -f concat -safe 0 -i "$flist" -framerate "$fr" -c:v libx264 -crf 18 -preset medium -pix_fmt yuv420p "$out_file" >"$ASM_LOG" 2>&1
          fi
          return $?
        }
        # Try deterministic filelist-based assembly first (preferred)
        if try_filelist_assembly "$ASMDIR" "$OUTPUT_VIDEO_PATH" "$FRAMERATE"; then
          log "Assembled video successfully from filelist-based assembly: $OUTPUT_VIDEO_PATH"
        else
          # fallback to ffmpeg pattern matching
          ffmpeg -hide_banner -loglevel info -progress pipe:1 -nostats -v warning -y -framerate "$FRAMERATE" -i "$IN_PATTERN" -c:v libx264 -crf 18 -preset medium -pix_fmt yuv420p "$OUTPUT_VIDEO_PATH"
        fi
      elif ls "$TMP_DIR/output"/*_mid.png >/dev/null 2>&1; then
        # If mid files exist (including mid_01 variants), assemble interleaved sequence first
        ASMDIR="$TMP_DIR/assembled"
        rm -rf "$ASMDIR" || true
        mkdir -p "$ASMDIR" || true
        NUM_IN=$(ls -1 "$TMP_DIR/input"/*.png 2>/dev/null | wc -l || true)
        idx=1
        if [ "$NUM_IN" -gt 0 ]; then
          i=1
          while [ $i -le $NUM_IN ]; do
            src_in="$TMP_DIR/input/$(printf 'frame_%06d.png' $i)"
            if [ -f "$src_in" ]; then
              dst="$ASMDIR/$(printf 'frame_%06d.png' $idx)"
              cp -f "$src_in" "$dst" || true
              idx=$((idx+1))
            fi
            # copy any mids for this pair, support both frame_x_mid.png and frame_x_mid_01.png variants
            mid_pattern="$TMP_DIR/output/$(printf 'frame_%06d' "$i")_mid"*
            for midf in $mid_pattern; do
              [ -f "$midf" ] || continue
              dst="$ASMDIR/$(printf 'frame_%06d.png' $idx)"
              cp -f "$midf" "$dst" || true
              idx=$((idx+1))
            done
            i=$((i+1))
          done
        fi
        IN_PATTERN="$ASMDIR/frame_%06d.png"
        log "Using assembled interleaved pattern: frame_%06d.png"
        # Compute assembled framerate using awk (avoid quoting/argv issues) and log diagnostics
        ASSEMBLED_COUNT=$(ls -1 "$ASMDIR"/*.png 2>/dev/null | wc -l || true)
        if [ -n "$NUM_IN" ] && [ "$NUM_IN" -gt 0 ] && [ -n "$ASSEMBLED_COUNT" ] && [ "$ASSEMBLED_COUNT" -gt 0 ]; then
          EXPECTED_APPROX=$(awk -v N="$NUM_IN" -v F="$FACTOR" 'BEGIN{printf("%.0f", N*F)}')
          FRAMERATE=$(awk -v orig="$ORIG_FPS" -v assembled="$ASSEMBLED_COUNT" -v num_in="$NUM_IN" -v factor="$FACTOR" 'BEGIN{ if(num_in>0){ expected=int(num_in*factor+0.5); if(assembled >= expected-2 && assembled <= expected+2) printf("%.6f", orig*factor); else printf("%.6f", orig*(assembled/num_in)); } else printf("%.6f", orig*factor) }')
          log "[debug] assembled_count=$ASSEMBLED_COUNT num_in=$NUM_IN expected_approx=$EXPECTED_APPROX framerate=$FRAMERATE"
        else
          FRAMERATE="$TARGET_FPS"
          log "[debug] assembled_count or num_in missing, using FRAMERATE=$FRAMERATE"
        fi
        # ensure FRAMERATE is set (avoid empty value causing ffmpeg to fail)
        FRAMERATE=${FRAMERATE:-$TARGET_FPS}
        # helper: try assembly using explicit filelist for deterministic ordering
        try_filelist_assembly() {
          local src_dir="$1"
          local out_file="$2"
          local fr="$3"
          local flist="$TMP_DIR/filelist.txt"
          rm -f "$flist" || true
          # create filelist with explicit ordering
          (for f in "$src_dir"/*.png; do [ -f "$f" ] || continue; echo "file '$f'"; done) >"$flist"
          if [ ! -s "$flist" ]; then
            return 1
          fi
          log "Using filelist concat assembly (first lines):"; head -n 20 "$flist" || true
          if [ -f "$TMP_DIR/audio.aac" ]; then
            ffmpeg -hide_banner -loglevel info -progress pipe:1 -nostats -y -f concat -safe 0 -i "$flist" -framerate "$fr" -i "$TMP_DIR/audio.aac" -c:v libx264 -crf 18 -preset medium -pix_fmt yuv420p -c:a aac -shortest "$out_file" >"$ASM_LOG" 2>&1
          else
            ffmpeg -hide_banner -loglevel info -progress pipe:1 -nostats -y -f concat -safe 0 -i "$flist" -framerate "$fr" -c:v libx264 -crf 18 -preset medium -pix_fmt yuv420p "$out_file" >"$ASM_LOG" 2>&1
          fi
          return $?
        }
        # Try deterministic filelist-based assembly first (preferred)
        if "$TMP_DIR/try_filelist_assembly.sh" "$TMP_DIR/assembled" "$OUTPUT_VIDEO_PATH" "$FRAMERATE"; then
          log "Assembled video successfully from filelist-based assembly: $OUTPUT_VIDEO_PATH"
        else
          # fallback to ffmpeg pattern matching
          ffmpeg -hide_banner -loglevel info -progress pipe:1 -nostats -v warning -y -framerate "$FRAMERATE" -i "$IN_PATTERN" -c:v libx264 -crf 18 -preset medium -pix_fmt yuv420p "$OUTPUT_VIDEO_PATH"
        fi
      elif ls "$TMP_DIR/output"/frame_*.png >/dev/null 2>&1; then
        IN_PATTERN="$TMP_DIR/output/frame_%06d.png"
        log "Using frame pattern: frame_%06d.png"
        FRAMERATE="$TARGET_FPS"
        # ensure FRAMERATE is set (avoid empty value causing ffmpeg to fail)
        FRAMERATE=${FRAMERATE:-$TARGET_FPS}
        # helper: try assembly using explicit filelist for deterministic ordering
        try_filelist_assembly() {
          local src_dir="$1"
          local out_file="$2"
          local fr="$3"
          local flist="$TMP_DIR/filelist.txt"
          rm -f "$flist" || true
          # create filelist with explicit ordering
          (for f in "$src_dir"/*.png; do [ -f "$f" ] || continue; echo "file '$f'"; done) >"$flist"
          if [ ! -s "$flist" ]; then
            return 1
          fi
          log "Using filelist concat assembly (first lines):"; head -n 20 "$flist" || true
          if [ -f "$TMP_DIR/audio.aac" ]; then
            ffmpeg -hide_banner -loglevel info -progress pipe:1 -nostats -y -f concat -safe 0 -i "$flist" -framerate "$fr" -i "$TMP_DIR/audio.aac" -c:v libx264 -crf 18 -preset medium -pix_fmt yuv420p -c:a aac -shortest "$out_file" >"$ASM_LOG" 2>&1
          else
            ffmpeg -hide_banner -loglevel info -progress pipe:1 -nostats -y -f concat -safe 0 -i "$flist" -framerate "$fr" -c:v libx264 -crf 18 -preset medium -pix_fmt yuv420p "$out_file" >"$ASM_LOG" 2>&1
          fi
          return $?
        }
        # Try deterministic filelist-based assembly first (preferred)
        if "$TMP_DIR/try_filelist_assembly.sh" "$TMP_DIR/output" "$OUTPUT_VIDEO_PATH" "$FRAMERATE"; then
          log "Assembled video successfully from filelist-based assembly: $OUTPUT_VIDEO_PATH"
        else
          # fallback to ffmpeg pattern matching
          ffmpeg -hide_banner -loglevel info -progress pipe:1 -nostats -v warning -y -framerate "$FRAMERATE" -i "$IN_PATTERN" -c:v libx264 -crf 18 -preset medium -pix_fmt yuv420p "$OUTPUT_VIDEO_PATH"
        fi
      else
        # Use glob pattern as last resort
        log "Using glob input pattern for assembly"
        FRAMERATE="$TARGET_FPS"
        if [ -f "$TMP_DIR/audio.aac" ]; then
          ffmpeg -hide_banner -loglevel info -progress pipe:1 -nostats -v warning -y -framerate "$FRAMERATE" -pattern_type glob -i "$TMP_DIR/output/*.png" -i "$TMP_DIR/audio.aac" -c:v libx264 -crf 18 -preset medium -pix_fmt yuv420p -c:a aac -shortest "$OUTPUT_VIDEO_PATH"
        else
          ffmpeg -hide_banner -loglevel info -progress pipe:1 -nostats -v warning -y -framerate "$FRAMERATE" -pattern_type glob -i "$TMP_DIR/output/*.png" -c:v libx264 -crf 18 -preset medium -pix_fmt yuv420p "$OUTPUT_VIDEO_PATH"
        fi
      fi

      if [ $? -eq 0 ] && [ -f "$OUTPUT_VIDEO_PATH" ]; then
        log "Assembled video successfully: $OUTPUT_VIDEO_PATH"
      else
        log "Failed to assemble frames into video"
      fi
    fi
  fi

  # Final success marker
  log "✓ RIFE completed at $(date '+%H:%M:%S')"
  echo ""

  # Verify final output exists and is non-empty; fail otherwise
  if [ -f "$OUTPUT_VIDEO_PATH" ] && [ -s "$OUTPUT_VIDEO_PATH" ]; then
    log "Output verified: $OUTPUT_VIDEO_PATH (size: $(stat -c%s "$OUTPUT_VIDEO_PATH") bytes)"
    # Normal exit (0)
    exit 0
  else
    log "ERROR: Expected output file missing or empty: $OUTPUT_VIDEO_PATH"
    # Print diagnostics: list output_dir contents and tmp dir
    log "Listing output dir: $(dirname "$OUTPUT_VIDEO_PATH")"
    ls -la "$(dirname "$OUTPUT_VIDEO_PATH")" || true
    log "Listing temp dir: $TMP_DIR"
    ls -la "$TMP_DIR" || true
    # Also search for common video files under workspace to aid debugging
    log "Searching for candidate video files under /workspace (top 50 results)"
    find /workspace -type f \( -iname '*.mp4' -o -iname '*.mkv' -o -iname '*.mov' \) -printf '%s %p\n' 2>/dev/null | sort -rn | head -n 50 || true
    # Non-zero exit to indicate failure to pipeline
    exit 4
  fi

fi
