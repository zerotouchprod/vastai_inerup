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
  # Pad frames to next multiple of 64 (width/height) to match RIFE model internal downsampling expectations
  # Expression: pad=iw+mod(64-iw,64):ih+mod(64-ih,64)
  ffmpeg -v warning -i "$INPUT_VIDEO_PATH" -vf "pad=iw+mod(64-iw\\,64):ih+mod(64-ih\\,64)" -pix_fmt rgb24 -qscale:v 1 "$TMP_DIR/input/frame_%06d.png"
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

    log "[debug] Listing REPO_DIR ($REPO_DIR) up to depth 2 (files/sizes):"
    find "$REPO_DIR" -maxdepth 2 -type f -printf '%s %p\n' 2>/dev/null | sort -rn | head -n 200 || true

    if [ -f "$REPO_DIR/inference_img.py" ]; then
      log "[debug] inference_img.py found — showing head (first 200 lines):"
      sed -n '1,200p' "$REPO_DIR/inference_img.py" 2>/dev/null || true
    else
      log "[debug] inference_img.py NOT found in $REPO_DIR"
      log "[debug] You can fetch it from upstream: https://raw.githubusercontent.com/hzwer/arXiv2020-RIFE/master/inference_img.py"
    fi

    cat > "$TMP_DIR/batch_rife.py" <<'PY'
import sys, os

in_dir = sys.argv[1]
out_dir = sys.argv[2]
factor = float(sys.argv[3])
repo = os.environ.get('REPO_DIR', '/workspace/project/external/RIFE')
model_dir = os.path.join(repo, 'train_log')

# Try importing a model class from common locations
Model = None
try:
    # preferred: trained model wrapper in train_log
    from train_log.RIFE_HDv3 import Model as _Model
    Model = _Model
except Exception:
    try:
        from model.RIFE import Model as _Model
        Model = _Model
    except Exception:
        try:
            from train_log.RIFE_HD import Model as _Model
            Model = _Model
        except Exception:
            Model = None

if Model is None:
    print('No compatible RIFE Model class found (tried train_log.RIFE_HDv3, model.RIFE, train_log.RIFE_HD)')
    sys.exit(2)

# load torch and cv2
import torch
import cv2
import numpy as np

# instantiate and load weights
try:
    model = Model()
except Exception as e:
    print('Failed to instantiate Model:', e)
    sys.exit(2)

# try load_model with common signatures
loaded = False
try:
    model.load_model(model_dir, -1)
    loaded = True
except Exception:
    try:
        model.load_model(model_dir)
        loaded = True
    except Exception as e:
        print('Failed to load model from', model_dir, 'error:', e)
        sys.exit(2)

model.eval()
# call device() method if available (some wrappers expose it)
try:
    model.device()
except Exception:
    pass

device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')

# Process pairs
imgs = sorted([p for p in os.listdir(in_dir) if p.lower().endswith('.png')])
if not os.path.exists(out_dir):
    os.makedirs(out_dir, exist_ok=True)

for i in range(len(imgs)-1):
    a_path = os.path.join(in_dir, imgs[i])
    b_path = os.path.join(in_dir, imgs[i+1])
    try:
        im0 = cv2.imread(a_path, cv2.IMREAD_UNCHANGED)
        im1 = cv2.imread(b_path, cv2.IMREAD_UNCHANGED)
        if im0 is None or im1 is None:
            print('Failed to read input images', a_path, b_path)
            continue
        # convert to torch tensor [1,C,H,W], normalize if uint8
        t0 = torch.tensor(im0.transpose(2,0,1)).to(device).unsqueeze(0)
        t1 = torch.tensor(im1.transpose(2,0,1)).to(device).unsqueeze(0)
        # if uint8 range -> normalize to 0..1
        if t0.dtype == torch.uint8:
            t0 = t0.float() / 255.0
        if t1.dtype == torch.uint8:
            t1 = t1.float() / 255.0
        # call model.inference (signature: (img0, img1) -> mid tensor)
        try:
            mid = model.inference(t0, t1)
        except Exception as e:
            # try alternative signature
            try:
                mid = model.inference(t0, t1, [1])
            except Exception as e2:
                print('Model inference failed for pair', a_path, b_path, 'errors:', e, e2)
                continue
        # mid -> save
        try:
            out_np = (mid[0] * 255.0).clamp(0,255).byte().cpu().numpy().transpose(1,2,0)
        except Exception:
            # maybe already uint8
            out_np = mid[0].byte().cpu().numpy().transpose(1,2,0)
        out_path = os.path.join(out_dir, f'frame_%06d_mid.png' % (i+1))
        cv2.imwrite(out_path, out_np)
    except Exception as e:
        print('Exception processing pair', a_path, b_path, '->', e)

sys.exit(0)
PY

    # run batch script
    PYTHONPATH="$REPO_DIR:$PYTHONPATH" python3 "$TMP_DIR/batch_rife.py" "$TMP_DIR/input" "$TMP_DIR/output" "$FACTOR" >/tmp/batch_rife_run.log 2>&1 || true
    # Consider batch successful ONLY if output PNGs were created (count them explicitly)
    PNG_COUNT=$(find "$TMP_DIR/output" -maxdepth 1 -type f -iname '*.png' -print | wc -l 2>/dev/null || true)
    if [ -n "$PNG_COUNT" ] && [ "$PNG_COUNT" -gt 0 ]; then
      BATCH_OK=1
      log "Batch-runner produced $PNG_COUNT outputs (sample): $(find "$TMP_DIR/output" -maxdepth 1 -type f -iname '*.png' -printf '%f\n' | head -n 5 | tr '\n' ',')"
      # Attempt to assemble produced frames into the final video now (avoid falling back to ffmpeg minterpolate)
      log "Attempting to assemble batch-produced frames into $OUTPUT_VIDEO_PATH"
      FRAMERATE="$TARGET_FPS"
      # Prefer *_out.png, then *_mid.png, then frame_*.png, then glob. Capture ffmpeg output to help debugging.
      ASM_LOG="/tmp/batch_assemble.log"
      rm -f "$ASM_LOG" || true
      if ls "$TMP_DIR/output"/*_out.png >/dev/null 2>&1; then
        IN_PATTERN="$TMP_DIR/output/frame_%06d_out.png"
      elif ls "$TMP_DIR/output"/*_mid.png >/dev/null 2>&1; then
        IN_PATTERN="$TMP_DIR/output/frame_%06d_mid.png"
      elif ls "$TMP_DIR/output"/frame_*.png >/dev/null 2>&1; then
        IN_PATTERN="$TMP_DIR/output/frame_%06d.png"
      else
        IN_PATTERN=""
      fi
      if [ -n "$IN_PATTERN" ]; then
        if [ -f "$TMP_DIR/audio.aac" ]; then
          ffmpeg -v warning -y -framerate "$FRAMERATE" -i "$IN_PATTERN" -i "$TMP_DIR/audio.aac" -c:v libx264 -crf 18 -preset medium -pix_fmt yuv420p -c:a aac -shortest "$OUTPUT_VIDEO_PATH" >"$ASM_LOG" 2>&1
        else
          ffmpeg -v warning -y -framerate "$FRAMERATE" -i "$IN_PATTERN" -c:v libx264 -crf 18 -preset medium -pix_fmt yuv420p "$OUTPUT_VIDEO_PATH" >"$ASM_LOG" 2>&1
        fi
      else
        if [ -f "$TMP_DIR/audio.aac" ]; then
          ffmpeg -v warning -y -framerate "$FRAMERATE" -pattern_type glob -i "$TMP_DIR/output/*.png" -i "$TMP_DIR/audio.aac" -c:v libx264 -crf 18 -preset medium -pix_fmt yuv420p -c:a aac -shortest "$OUTPUT_VIDEO_PATH" >"$ASM_LOG" 2>&1
        else
          ffmpeg -v warning -y -framerate "$FRAMERATE" -pattern_type glob -i "$TMP_DIR/output/*.png" -c:v libx264 -crf 18 -preset medium -pix_fmt yuv420p "$OUTPUT_VIDEO_PATH" >"$ASM_LOG" 2>&1
        fi
      fi
      ASM_RC=$?
      if [ $ASM_RC -eq 0 ] && [ -f "$OUTPUT_VIDEO_PATH" ]; then
        log "Assembled video successfully from batch outputs: $OUTPUT_VIDEO_PATH"
        # Final success
        log "✓ RIFE completed at $(date '+%H:%M:%S')"
        echo ""
        log "Output verified: $OUTPUT_VIDEO_PATH (size: $(stat -c%s "$OUTPUT_VIDEO_PATH") bytes)"
        exit 0
      else
        log "Failed to assemble frames from batch outputs (rc=$ASM_RC). Assembly log follows:";
        sed -n '1,200p' "$ASM_LOG" 2>/dev/null || true
        log "Will fallback to existing logic"
      fi
    else
      log "Batch-runner produced no output PNGs (count=$PNG_COUNT); printing batch log (up to 50KB) for debugging:"
      head -c 50000 "/tmp/batch_rife_run.log" || true
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
        PYTHONPATH="$REPO_DIR:$PYTHONPATH" python3 "$REPO_DIR/inference_img.py" --img "$a" "$b" --ratio 0.5 --model train_log >"$TMP_DIR/rife_pair_$i.log" 2>&1 || true

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
        if [ -f "$TMP_DIR/audio.aac" ]; then
          ffmpeg -v warning -y -framerate "$FRAMERATE" -i "$IN_PATTERN" -i "$TMP_DIR/audio.aac" -c:v libx264 -crf 18 -preset medium -pix_fmt yuv420p -c:a aac -shortest "$OUTPUT_VIDEO_PATH"
        else
          ffmpeg -v warning -y -framerate "$FRAMERATE" -i "$IN_PATTERN" -c:v libx264 -crf 18 -preset medium -pix_fmt yuv420p "$OUTPUT_VIDEO_PATH"
        fi
      elif ls "$TMP_DIR/output"/*_mid.png >/dev/null 2>&1; then
        IN_PATTERN="$TMP_DIR/output/frame_%06d_mid.png"
        log "Using frame pattern: frame_%06d_mid.png"
        FRAMERATE="$TARGET_FPS"
        if [ -f "$TMP_DIR/audio.aac" ]; then
          ffmpeg -v warning -y -framerate "$FRAMERATE" -i "$IN_PATTERN" -i "$TMP_DIR/audio.aac" -c:v libx264 -crf 18 -preset medium -pix_fmt yuv420p -c:a aac -shortest "$OUTPUT_VIDEO_PATH"
        else
          ffmpeg -v warning -y -framerate "$FRAMERATE" -i "$IN_PATTERN" -c:v libx264 -crf 18 -preset medium -pix_fmt yuv420p "$OUTPUT_VIDEO_PATH"
        fi
      elif ls "$TMP_DIR/output"/frame_*.png >/dev/null 2>&1; then
        IN_PATTERN="$TMP_DIR/output/frame_%06d.png"
        log "Using frame pattern: frame_%06d.png"
        FRAMERATE="$TARGET_FPS"
        if [ -f "$TMP_DIR/audio.aac" ]; then
          ffmpeg -v warning -y -framerate "$FRAMERATE" -i "$IN_PATTERN" -i "$TMP_DIR/audio.aac" -c:v libx264 -crf 18 -preset medium -pix_fmt yuv420p -c:a aac -shortest "$OUTPUT_VIDEO_PATH"
        else
          ffmpeg -v warning -y -framerate "$FRAMERATE" -i "$IN_PATTERN" -c:v libx264 -crf 18 -preset medium -pix_fmt yuv420p "$OUTPUT_VIDEO_PATH"
        fi
      else
        # Use glob pattern as last resort
        log "Using glob input pattern for assembly"
        FRAMERATE="$TARGET_FPS"
        if [ -f "$TMP_DIR/audio.aac" ]; then
          ffmpeg -v warning -y -framerate "$FRAMERATE" -pattern_type glob -i "$TMP_DIR/output/*.png" -i "$TMP_DIR/audio.aac" -c:v libx264 -crf 18 -preset medium -pix_fmt yuv420p -c:a aac -shortest "$OUTPUT_VIDEO_PATH"
        else
          ffmpeg -v warning -y -framerate "$FRAMERATE" -pattern_type glob -i "$TMP_DIR/output/*.png" -c:v libx264 -crf 18 -preset medium -pix_fmt yuv420p "$OUTPUT_VIDEO_PATH"
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
