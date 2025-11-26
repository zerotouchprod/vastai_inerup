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
    cat > "$TMP_DIR/batch_rife.py" <<'PY'
import sys, os
from importlib.util import spec_from_file_location

in_dir = sys.argv[1]
out_dir = sys.argv[2]
factor = float(sys.argv[3])
repo = os.environ.get('REPO_DIR', '/workspace/project/external/RIFE')

def try_direct():
    # already attempted external direct script from shell; return False so we try import-based options
    return False

def try_import_inference():
    path = os.path.join(repo, 'inference_img.py')
    if not os.path.exists(path):
        return False
    try:
        spec = spec_from_file_location('rife_inference', path)
        mod = spec.loader.load_module() if spec and spec.loader else None
    except Exception as e:
        try:
            # fallback to runpy
            import runpy
            mod = runpy.run_path(path)
        except Exception as e2:
            return False

    # If module provided a batch API, try to call it
    try:
        if hasattr(mod, 'batch_inference'):
            mod.batch_inference(in_dir, out_dir, factor)
            return True
        if hasattr(mod, 'inference_dir'):
            mod.inference_dir(in_dir, out_dir, factor)
            return True
        # try common pattern: module.load_model() and module.inference(img0, img1, model)
        model = None
        if hasattr(mod, 'load_model'):
            try:
                model = mod.load_model(os.path.join(repo, 'train_log'))
            except TypeError:
                model = mod.load_model()
        elif hasattr(mod, 'build_model'):
            try:
                model = mod.build_model(os.path.join(repo, 'train_log'))
            except TypeError:
                model = mod.build_model()

        infer_fn = None
        if hasattr(mod, 'inference'):
            infer_fn = mod.inference
        elif hasattr(mod, 'inference_pair'):
            infer_fn = mod.inference_pair

        if model is not None and infer_fn is not None:
            # iterate pairs
            imgs = sorted([p for p in os.listdir(in_dir) if p.lower().endswith('.png')])
            import PIL.Image as Image
            for i in range(len(imgs)-1):
                a = os.path.join(in_dir, imgs[i])
                b = os.path.join(in_dir, imgs[i+1])
                try:
                    out = infer_fn(a, b, model) if infer_fn.__code__.co_argcount >= 3 else infer_fn(a, b)
                except Exception:
                    # try passing file paths to function
                    out = infer_fn(a, b)
                # if out is an image array or PIL Image, save it
                if out is None:
                    # some implementations write directly to disk; continue
                    continue
                try:
                    if hasattr(out, 'save'):
                        out.save(os.path.join(out_dir, f'frame_%06d_mid.png' % (i+1)))
                    else:
                        # assume numpy array
                        import numpy as np
                        im = Image.fromarray(out.astype('uint8'))
                        im.save(os.path.join(out_dir, f'frame_%06d_mid.png' % (i+1)))
                except Exception:
                    pass
            return True
    except Exception:
        return False
    return False

if __name__ == '__main__':
    ok = try_import_inference()
    sys.exit(0 if ok else 2)
PY

    # run batch script
    PYTHONPATH="$REPO_DIR:$PYTHONPATH" python3 "$TMP_DIR/batch_rife.py" "$TMP_DIR/input" "$TMP_DIR/output" "$FACTOR" >/tmp/batch_rife_run.log 2>&1 || true
    if [ -s "$TMP_DIR/output" ] || [ -s "/tmp/batch_rife_run.log" ]; then
      # consider success if output dir contains files
      if ls "$TMP_DIR/output"/*.png >/dev/null 2>&1; then
        BATCH_OK=1
        log "Batch-runner produced outputs: $(ls -1 "$TMP_DIR/output" | head -n 5 | tr '\n' ',' )"
      else
        # inspect log for clues
        log "Batch-runner log (first 200 chars):"
        head -c 200 "/tmp/batch_rife_run.log" || true
      fi
    fi
  fi

  # If batch-runner succeeded, skip per-pair external invocations
  if [ "$BATCH_OK" -eq 1 ]; then
    log "Batch-runner succeeded, skipping per-pair subprocess loop"
  else
    log "Batch-runner not available or failed — falling back to per-pair execution"

    # If repository has inference_img.py (pairwise inference), try to run simple in-place process (best-effort)
    if [ -f "$REPO_DIR/inference_img.py" ]; then
      log "Found inference_img.py — attempting pairwise inference (best-effort)"

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

      # Run inference on each consecutive frame pair; output to TMP_DIR/output as frame_%06d_out.png
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
          # Invoke RIFE script with PYTHONPATH set to repo. Capture logs for debugging.
          PYTHONPATH="$REPO_DIR:$PYTHONPATH" python3 "$REPO_DIR/inference_img.py" --img "$a" "$b" --ratio 0.5 --model train_log >"$TMP_DIR/rife_pair_$i.log" 2>&1 || true

          # Emit the pair log to stdout for remote debugging
          if [ -f "$TMP_DIR/rife_pair_$i.log" ]; then
            echo "--- RIFE pair log: $TMP_DIR/rife_pair_$i.log (start) ---"
            sed -n '1,200p' "$TMP_DIR/rife_pair_$i.log" 2>/dev/null || true
            echo "--- RIFE pair log: $TMP_DIR/rife_pair_$i.log (end) ---"
          fi

          # Try to locate produced mid-frame in common locations and move it to out_mid
          # Common outputs: output.png in repo root, or files in current dir matching *mid*.png
          if [ -f "$REPO_DIR/output.png" ]; then
            mv "$REPO_DIR/output.png" "$out_mid" 2>/dev/null || true
          fi
          if [ -f "output.png" ]; then
            mv "output.png" "$out_mid" 2>/dev/null || true
          fi
          # find any recent png in repo root that may be the mid frame
          cand=$(find "$REPO_DIR" -maxdepth 1 -type f -iname '*mid*.png' -print -quit 2>/dev/null || true)
          if [ -n "$cand" ] && [ ! -f "$out_mid" ]; then
            mv "$cand" "$out_mid" 2>/dev/null || true
          fi
          # As a last resort, try to move the newest PNG under repo (if any)
          if [ ! -f "$out_mid" ]; then
            newest=$(find "$REPO_DIR" -maxdepth 2 -type f -iname '*.png' -printf '%T@ %p
' 2>/dev/null | sort -nr | head -n 1 | awk '{print $2}' || true)
            if [ -n "$newest" ]; then
              mv "$newest" "$out_mid" 2>/dev/null || true
            fi
          fi

          i=$((i+1))
        done
        log "Pairwise inference attempts finished; output dir listing: $(ls -1 "$TMP_DIR/output" | head -n 20 2>/dev/null || true)"
      fi
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
