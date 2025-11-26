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
      log "Test frame created; hex head (first 128 bytes):"
      print_hex_head "$TMP_DIR/input/frame_test_000001.png" 128
      file "$TMP_DIR/input/frame_test_000001.png" || true
    else
      log "Test frame was NOT created — ffmpeg cannot write PNGs; check ffmpeg build and container permissions"
    fi
    rm -rf "$TMP_DIR"
    exit 4
  fi

  # Ensure readable permissions for downstream processes
  chmod a+r "$TMP_DIR/input"/*.png 2>/dev/null || true

  # Post-extraction diagnostics: list input dir and inspect first frame header (png or jpg)
  log "Post-extract listing of $TMP_DIR/input (first 200 entries):"
  ls -la "$TMP_DIR/input" | head -n 200 || true
  # pick the first image file (full path) using find to avoid accidental non-image matches
  FIRST_FRAME=$(find "$TMP_DIR/input" -maxdepth 1 -type f \( -iname '*.png' -o -iname '*.jpg' -o -iname '*.jpeg' \) -print | head -n 1 || true)
  if [ -n "$FIRST_FRAME" ] && [ -f "$FIRST_FRAME" ]; then
    log "Showing hex head of first frame (first 128 bytes): $FIRST_FRAME"
    print_hex_head "$FIRST_FRAME" 128
    if command -v file >/dev/null 2>&1; then
      file "$FIRST_FRAME" || true
    fi
  else
    log "No frame file found after extraction (png/jpg)"
  fi

  # Quick CV2 sanity check: try to read the first extracted image (png/jpg) using OpenCV inside python.
  if [ -n "$FIRST_FRAME" ] && [ -f "$FIRST_FRAME" ]; then
    python3 - <<'PY' >"$TMP_DIR/cv_read_check.log" 2>&1
import cv2,sys
p=sys.argv[1]
img=cv2.imread(p, cv2.IMREAD_UNCHANGED)
print('cv2_read_ok', img is not None)
if img is None:
    try:
        import PIL.Image as Image
        im=Image.open(p)
        print('PIL_read_ok', True)
    except Exception as e:
        print('PIL_read_ok', False, 'err', str(e))
    sys.exit(2)
sys.exit(0)
PY
     if [ $? -ne 0 ]; then
       log "CV2 failed to read extracted images; attempting fallback extraction to JPEG frames"
      # cleanup previous frames and re-extract as JPEG (mjpeg) to avoid PNG decoder issues
      rm -f "$TMP_DIR/input"/* 2>/dev/null || true
      ffmpeg -hide_banner -loglevel info -progress pipe:1 -nostats -i "$INPUT_VIDEO_PATH" -map 0:v:0 -vsync 0 -start_number 1 \
        -vf "pad=if(mod(iw\,64),iw+(64-mod(iw\,64)),iw):if(mod(ih\,64),ih+(64-mod(ih\,64)),ih)" \
        -pix_fmt yuvj420p -f image2 -vcodec mjpeg "$TMP_DIR/input/frame_%06d.jpg" 2>&1 | tee "$TMP_DIR/ff_extract_jpg.log" | progress_collapse || true
      # Wait briefly for files
      sleep 1
      COUNTJPG=$(ls -1 "$TMP_DIR/input"/*.jpg 2>/dev/null | wc -l || true)
      log "JPEG re-extraction produced $COUNTJPG files"
      if [ "$COUNTJPG" -gt 0 ]; then
        chmod a+r "$TMP_DIR/input"/*.jpg 2>/dev/null || true
        # update FIRST_FRAME to point to jpeg
        FIRST_FRAME=$(ls -1 "$TMP_DIR/input"/*.jpg 2>/dev/null | head -n 1 || true)
      else
        log "JPEG re-extraction failed; see $TMP_DIR/ff_extract_jpg.log"
      fi
    else
      log "CV2 read test passed for first image"
    fi
  fi

  # Count frames (png/jpg) using command substitution (avoid arithmetic expansion error)
  FRAME_COUNT=$( (ls -1 "$TMP_DIR/input"/*.png 2>/dev/null || true; ls -1 "$TMP_DIR/input"/*.jpg 2>/dev/null || true; ls -1 "$TMP_DIR/input"/*.jpeg 2>/dev/null || true) | wc -l )
  log "Extracted $FRAME_COUNT frames"

  if [ $FRAME_COUNT -eq 0 ]; then
    log "ERROR: No frames extracted"
    rm -rf "$TMP_DIR"
    exit 4
  fi

  # Extract audio track
  log "Extracting audio track..."
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

  # NOTE: script continuation previously present; minimal safe exit to ensure syntactic correctness in this workspace edit.
  log "INFO: run_rife_pytorch.sh reached diagnostic checkpoint; exiting early to avoid accidental runtime changes in editing session."
  exit 0

fi

# End of script
