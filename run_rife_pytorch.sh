#!/usr/bin/env bash
# Wrapper to run RIFE (PyTorch) if available in /workspace/project/external/RIFE
# Note: NOT using set -e to allow fallback methods when inference_video.py fails
# Usage: run_rife_pytorch.sh <input> <output> <factor>

# Function to print with timestamp
log() {
    echo "[$(date '+%H:%M:%S')] $*"
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
log "[debug] STRICT=${STRICT:-<unset>} RIFE_MODEL_URL=${RIFE_MODEL_URL:-<unset>}"
if [ -d "/opt/rife_models" ]; then
  log "[debug] /opt/rife_models exists, listing:"
  ls -la /opt/rife_models || true
else
  log "[debug] /opt/rife_models does NOT exist"
fi
if [ -d "/opt/rife_models/train_log" ]; then
  log "[debug] /opt/rife_models/train_log exists, listing:"
  ls -la /opt/rife_models/train_log || true
else
  log "[debug] /opt/rife_models/train_log does NOT exist"
fi
if [ -d "$REPO_DIR/train_log" ]; then
  log "[debug] $REPO_DIR/train_log contents (before copy):"
  ls -la "$REPO_DIR/train_log" || true
else
  log "[debug] $REPO_DIR/train_log does NOT exist (unexpected)"
fi

# If models don't exist, copy from preinstalled location
if ! has_models "$REPO_DIR/train_log"; then
  log "RIFE models not found in train_log, copying from preinstalled location..."

  if [ -d "/opt/rife_models/train_log" ] && has_models "/opt/rife_models/train_log"; then
    mkdir -p "$REPO_DIR/train_log"
    cp -r /opt/rife_models/train_log/* "$REPO_DIR/train_log/"
    log "RIFE model copied successfully (sample listing):"
    ls -lh "$REPO_DIR/train_log" | head -20 || true
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

  # Ensure cleanup on exit
  trap 'rc=$?; rm -rf "${TMP_DIR}" >/dev/null 2>&1 || true; exit $rc' EXIT

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
  ffmpeg -v warning -i "$INPUT_VIDEO_PATH" -pix_fmt rgb24 -qscale:v 1 "$TMP_DIR/input/frame_%06d.png"
  if [ $? -ne 0 ]; then
    log "ERROR: Failed to extract frames"
    rm -rf "$TMP_DIR"
    exit 4
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
  AUDIO_RESULT=$(ffmpeg -v warning -i "$INPUT_VIDEO_PATH" -vn -acodec copy "$TMP_DIR/audio.aac" 2>&1)
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

