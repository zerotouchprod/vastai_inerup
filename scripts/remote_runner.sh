#!/usr/bin/env bash
set -eo pipefail

# remote_runner.sh
# Run inside the container on vast.ai
#
# NEW: If config.yaml exists in repo, uses it instead of ENV vars!
# This allows updating processing parameters via Git without rebuilding instance.
#
# ENV vars (fallback if no config.yaml):
#  INPUT_URL - URL to download input
#  MODE - upscale|interpolate|both
#  SCALE - integer (2 or 4)
#  INTERP_FACTOR - float (e.g. 2.5)
#  B2_BUCKET - destination bucket
#  B2_OUTPUT_KEY - object key for output
#  B2_ENDPOINT - S3 endpoint

# 🐍 USE NATIVE PYTHON PROCESSORS (no shell scripts!)
# This enables the new pure Python implementations without rebuilding Docker image.
# Native processors provide full debugging support and are 100% Python.
export USE_NATIVE_PROCESSORS=${USE_NATIVE_PROCESSORS:-1}

echo "=== Remote Runner Starting ==="
echo "Time: $(date)"
echo ""

if [ "$USE_NATIVE_PROCESSORS" = "1" ]; then
  echo "🐍 Native Python processors ENABLED (no bash scripts)"
  echo "   → Full debugging support"
  echo "   → 100% Python code"
else
  echo "🐚 Shell-based processors (legacy mode)"
fi
echo ""

# Default: allow NVENC attempts (faster) but fallback to software if NVENC fails.
# Can be overridden by setting FORCE_SW_ENC=1 in the job environment to force libx264.
export FORCE_SW_ENC=${FORCE_SW_ENC:-0}
echo "[remote_runner] FORCE_SW_ENC=${FORCE_SW_ENC} (1=force libx264, 0=allow NVENC)"

# If a persistent pending upload exists from a previous run, attempt it now (one-shot retry)
PENDING_MARKER=/workspace/.pending_upload.json
MAX_ATTEMPTS=${MAX_ATTEMPTS:-3}
if [ -f "$PENDING_MARKER" ]; then
  echo "[FORCE_UPLOAD] Found pending upload marker: $PENDING_MARKER -> will attempt retry now"
  # read attempts from marker (if present)
  P_ATTEMPTS=0
  if python3 - <<PY >/dev/null 2>&1
import json
try:
    obj=json.load(open('$PENDING_MARKER'))
    print(int(obj.get('attempts',0)))
except Exception:
    pass
PY
  then
    P_ATTEMPTS=$(python3 - <<PY
import json
try:
    obj=json.load(open('$PENDING_MARKER'))
    print(int(obj.get('attempts',0)))
except Exception:
    print(0)
PY
)
  fi
  echo "[FORCE_UPLOAD] pending marker attempts=$P_ATTEMPTS max_allowed=$MAX_ATTEMPTS"
  if [ "$P_ATTEMPTS" -ge "$MAX_ATTEMPTS" ]; then
    echo "[FORCE_UPLOAD] Max attempts reached for pending upload (attempts=$P_ATTEMPTS >= $MAX_ATTEMPTS). Skipping retry."
  else
    # The helper will read pending marker if FORCE_FILE not set
    HELPER="/workspace/project/scripts/force_upload_and_fail.sh"
    if [ -f "$HELPER" ]; then
      echo "[FORCE_UPLOAD] Invoking helper for pending upload: $HELPER"
      # allow small-file uploads for pending retries as previous run failed
      export FORCE_UPLOAD_ALLOW_SMALL=1
      if [ -x "$HELPER" ]; then
        "$HELPER"
        rc=$?
      else
        bash "$HELPER"
        rc=$?
      fi
      echo "[FORCE_UPLOAD] pending upload helper exited with code=$rc"
      # Do not exit the runner; log and continue
    else
      echo "[FORCE_UPLOAD] ERROR: helper script not found: $HELPER"
    fi
  fi
fi

# Control flag: set ENABLE_EARLY_FORCE_UPLOAD=1 to enable the unconditional early upload check (disabled by default)
if [ "${ENABLE_EARLY_FORCE_UPLOAD:-0}" != "1" ]; then
  echo "[FORCE_UPLOAD] Early unconditional upload disabled (ENABLE_EARLY_FORCE_UPLOAD!=1). To enable set ENABLE_EARLY_FORCE_UPLOAD=1 in job env."
else

# EARLY FORCE-UPLOAD: check for trigger or existing output mp4s and run one-shot uploader immediately.
# This block is intentionally early so the upload occurs right after git fetch/entrypoint logs.
{
  echo "[FORCE_UPLOAD] PRECHECK START"
  # presence of trigger files
  if [ -f /workspace/project/.force_upload ]; then
    echo "[FORCE_UPLOAD] project trigger present: /workspace/project/.force_upload"
  else
    echo "[FORCE_UPLOAD] project trigger NOT present"
  fi
  if [ -f /workspace/.force_upload ]; then
    echo "[FORCE_UPLOAD] workspace trigger present: /workspace/.force_upload"
  fi
  if [ -f /workspace/force_upload_trigger ]; then
    echo "[FORCE_UPLOAD] legacy trigger present: /workspace/force_upload_trigger"
  fi

  # find newest mp4 in /workspace/output
  newest_mp4=$(ls -1t /workspace/output/*.mp4 2>/dev/null | head -n1 || true)
  if [ -n "$newest_mp4" ] && [ -s "$newest_mp4" ]; then
    echo "[FORCE_UPLOAD] found candidate mp4: $newest_mp4"

    # prefer bucket/key from trigger JSON if present
    TRIG_PATH="/workspace/project/.force_upload"
    TRIG_BUCKET=""
    TRIG_KEY=""
    if [ -s "$TRIG_PATH" ]; then
      TRIG_JSON=$(cat "$TRIG_PATH" 2>/dev/null || true)
      if python3 - <<PY >/dev/null 2>&1
import sys,json
s=sys.stdin.read()
try:
    obj=json.loads(s)
    if isinstance(obj,dict): print('OK')
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
      fi
    fi

    BKT="${TRIG_BUCKET:-}"
    if [ -z "$BKT" ]; then
      BKT="${B2_BUCKET:-}"
    fi
    KEYV="${TRIG_KEY:-}"
    if [ -z "$KEYV" ]; then
      KEYV="${B2_OUTPUT_KEY:-${B2_KEY:-}}"
    fi

    if [ -z "$BKT" ]; then
      echo "[FORCE_UPLOAD] No B2 bucket configured (trigger or env); skipping force upload"
    else
      echo "[FORCE_UPLOAD] Triggering upload of $newest_mp4 -> s3://$BKT/${KEYV:-auto}"
      export FORCE_FILE="$newest_mp4"
      export B2_BUCKET="$BKT"
      # Use B2_OUTPUT_KEY for object key to avoid clobbering B2_KEY (which is used for credentials)
      export B2_OUTPUT_KEY="$KEYV"
       # mark ran so repeated restarts don't re-trigger (helper also writes marker)
      touch /workspace/.force_upload_ran 2>/dev/null || true
      HELPER="/workspace/project/scripts/force_upload_and_fail.sh"
      if [ -f "$HELPER" ]; then
        echo "[FORCE_UPLOAD] Invoking helper: $HELPER"
        # Force allow small-file uploads for one-shot forced upload runs
        echo "[FORCE_UPLOAD] Forcing small-file upload bypass (FORCE_UPLOAD_ALLOW_SMALL=1)"
        export FORCE_UPLOAD_ALLOW_SMALL=1
        if [ -x "$HELPER" ]; then
          "$HELPER"
          rc=$?
        else
          # Fall back to running via bash so lack of executable bit doesn't block the upload
          bash "$HELPER"
          rc=$?
        fi
        echo "[FORCE_UPLOAD] force_upload_and_fail.sh exited with code=$rc"
        # propagate the exit code from helper (often intentionally non-zero to signal one-shot)
        exit $rc
      else
        echo "[FORCE_UPLOAD] ERROR: helper script not found: $HELPER"
      fi
    fi
  else
    echo "[FORCE_UPLOAD] No candidate mp4 found in /workspace/output"
  fi
  echo "[FORCE_UPLOAD] PRECHECK END"
} || true

fi

# Check if config.yaml exists in repository (after Git pull by entrypoint.sh)
CONFIG_FILE="/workspace/project/config.yaml"
USE_CONFIG=false

if [ -f "$CONFIG_FILE" ]; then
  echo "✓ Found config.yaml in repository!"
  echo "  → Will use config-driven workflow instead of ENV vars"
  USE_CONFIG=true
else
  echo "✗ No config.yaml found, using ENV vars (legacy mode)"
fi

echo ""

# Set defaults from ENV (used only if USE_CONFIG=false)
MODE="${MODE:-both}"
SCALE="${SCALE:-2}"
INTERP="${INTERP_FACTOR:-2.50}"
OUTPUT_DIR=/workspace/output
# FINAL (deprecated): final output path variable removed because it's unused in this script
# If a downstream step needs a final path, set/consume /workspace/final_output.mp4 explicitly

if [ "$USE_CONFIG" = false ]; then
  echo "[remote_runner] ENV MODE=$MODE SCALE=$SCALE INTERP=$INTERP"
  echo "[remote_runner] PREFER=${PREFER:-auto}"
fi

echo "[remote_runner] Checking for PyTorch wrapper scripts and ncnn binaries:"
if [ -x "/workspace/project/run_realesrgan_pytorch.sh" ]; then echo "  run_realesrgan_pytorch.sh: exists+executable"; else echo "  run_realesrgan_pytorch.sh: missing or not executable"; fi
if [ -x "/workspace/project/run_rife_pytorch.sh" ]; then echo "  run_rife_pytorch.sh: exists+executable"; else echo "  run_rife_pytorch.sh: missing or not executable"; fi
for b in realesrgan-ncnn-vulkan rife-ncnn-vulkan realesrgan-ncnn rife-ncnn realesrgan rife; do
  which $b >/dev/null 2>&1 && echo "  ncnn binary found in PATH: $b" || true
done

# Clone Real-ESRGAN and RIFE repos to get inference scripts
echo "[remote_runner] Checking external/Real-ESRGAN..."
if [ -d "/workspace/project/external/Real-ESRGAN" ]; then
  if [ -f "/workspace/project/external/Real-ESRGAN/inference_realesrgan.py" ]; then
    echo "[remote_runner] Real-ESRGAN already cloned and valid"
  else
    echo "[remote_runner] Real-ESRGAN directory exists but inference_realesrgan.py missing - re-cloning"
    rm -rf /workspace/project/external/Real-ESRGAN
    mkdir -p /workspace/project/external
    git clone --depth 1 https://github.com/xinntao/Real-ESRGAN.git /workspace/project/external/Real-ESRGAN
    rm -rf /workspace/project/external/Real-ESRGAN/realesrgan
    echo "[remote_runner] Removed realesrgan/ package dir (using installed package)"
  fi
else
  echo "[remote_runner] Cloning Real-ESRGAN..."
  mkdir -p /workspace/project/external
  git clone --depth 1 https://github.com/xinntao/Real-ESRGAN.git /workspace/project/external/Real-ESRGAN
  rm -rf /workspace/project/external/Real-ESRGAN/realesrgan
  echo "[remote_runner] Removed realesrgan/ package dir (using installed package)"
fi

echo "[remote_runner] Checking external/RIFE..."
if [ -d "/workspace/project/external/RIFE" ]; then
  if [ -f "/workspace/project/external/RIFE/RIFE_HDv3.py" ]; then
    echo "[remote_runner] RIFE already cloned and valid (RIFE_HDv3.py present)"
  else
    echo "[remote_runner] RIFE directory exists but RIFE_HDv3.py missing - re-cloning"
    rm -rf /workspace/project/external/RIFE
    mkdir -p /workspace/project/external
    git clone --depth 1 https://github.com/hzwer/arXiv2020-RIFE.git /workspace/project/external/RIFE

    # Copy preinstalled RIFE models from image to RIFE repo
    if [ -d "/opt/rife_models/train_log" ] && [ -n "$(ls -A /opt/rife_models/train_log 2>/dev/null)" ]; then
      echo "[remote_runner] Copying preinstalled RIFE models to RIFE repo..."
      mkdir -p /workspace/project/external/RIFE/train_log
      cp -r /opt/rife_models/train_log/* /workspace/project/external/RIFE/train_log/
      echo "[remote_runner] Models copied successfully ($(ls /workspace/project/external/RIFE/train_log/*.pkl 2>/dev/null | wc -l) .pkl files)"
    else
      echo "[remote_runner] WARNING: No preinstalled RIFE models found in /opt/rife_models/train_log/"
    fi
  fi
else
  echo "[remote_runner] Cloning RIFE..."
  mkdir -p /workspace/project/external
  git clone --depth 1 https://github.com/hzwer/arXiv2020-RIFE.git /workspace/project/external/RIFE

  # Copy preinstalled RIFE models from image to RIFE repo
  if [ -d "/opt/rife_models/train_log" ] && [ -n "$(ls -A /opt/rife_models/train_log 2>/dev/null)" ]; then
    echo "[remote_runner] Copying preinstalled RIFE models to RIFE repo..."
    mkdir -p /workspace/project/external/RIFE/train_log
    cp -r /opt/rife_models/train_log/* /workspace/project/external/RIFE/train_log/
    echo "[remote_runner] Models copied successfully ($(ls /workspace/project/external/RIFE/train_log/*.pkl 2>/dev/null | wc -l) .pkl files)"
  else
    echo "[remote_runner] WARNING: No preinstalled RIFE models found in /opt/rife_models/train_log/"
  fi
fi

# Verify RIFE was cloned successfully
if [ -f "/workspace/project/external/RIFE/RIFE_HDv3.py" ]; then
  echo "[remote_runner] ✓ RIFE_HDv3.py confirmed present"
else
  echo "[remote_runner] ✗ ERROR: RIFE_HDv3.py still missing after clone!"
  echo "[remote_runner] Listing /workspace/project/external/RIFE:"
  ls -la /workspace/project/external/RIFE/ 2>/dev/null || echo "Directory not found"
fi

# Ensure wrapper scripts are executable
if [ -f "/workspace/project/run_realesrgan_pytorch.sh" ]; then
  chmod +x /workspace/project/run_realesrgan_pytorch.sh || true
fi
if [ -f "/workspace/project/run_rife_pytorch.sh" ]; then
  chmod +x /workspace/project/run_rife_pytorch.sh || true
fi

# GPU diagnostics
echo ""
echo "=== GPU DIAGNOSTICS (inside container) ==="
if command -v nvidia-smi >/dev/null 2>&1; then
  nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv,noheader || echo "nvidia-smi query failed"
else
  echo "nvidia-smi not found"
fi

python3 - <<'PY'
import sys
try:
    import torch
    print('torch:', getattr(torch, '__version__', '(no torch)'))
    try:
        print('cuda_available:', torch.cuda.is_available())
        print('cuda_device_count:', torch.cuda.device_count())
        if torch.cuda.is_available():
            try:
                print('cuda_device_name:', torch.cuda.get_device_name(0))
            except Exception as e:
                print('cuda_device_name: error', e)
    except Exception as e:
        print('torch.cuda check failed:', e)
except Exception as e:
    print('import torch failed:', e)
PY

# Ensure output dir exists
mkdir -p "$OUTPUT_DIR"

# --- Smoke-test step (optional) ---
SMOKE_SECONDS_VAL=${SMOKE_SECONDS:-0}
SMOKE_TIMEOUT_VAL=${SMOKE_TIMEOUT:-180}
if [ "${SMOKE_SECONDS_VAL}" != "0" ] && [ -n "${SMOKE_SECONDS_VAL}" ]; then
  echo "\n=== SMOKE-TEST START (first ${SMOKE_SECONDS_VAL}s) ==="
  set -o pipefail
  SMOKE_IN=/workspace/smoke_input.mp4
  SMOKE_DIR=/workspace/smoke
  mkdir -p "$SMOKE_DIR"
  # Download first N seconds (fast) - use ffmpeg if available for precise trimming, else wget+ffmpeg
  if command -v ffmpeg >/dev/null 2>&1; then
    echo "[smoke] Downloading and trimming first ${SMOKE_SECONDS_VAL}s to ${SMOKE_IN}"
    if [ -n "$INPUT_URL" ]; then
      # Try direct frame extraction from the remote URL (avoid writing intermediate file)
      # This helps with .mkv inputs and remote URLs that ffmpeg can read directly.
      timeout ${SMOKE_TIMEOUT_VAL} ffmpeg -y -i "$INPUT_URL" -t ${SMOKE_SECONDS_VAL} -vf "select=not(mod(n\\,10))" -vframes 2 "$SMOKE_DIR/frame_%02d.png" >/workspace/smoke_ff_extract.log 2>&1 || true
      # If direct extraction produced frames, we are done; else try safer fallback
      if [ -f "$SMOKE_DIR/frame_01.png" ] || [ -f "$SMOKE_DIR/frame_1.png" ]; then
        echo "[smoke] Direct frame extraction succeeded"
      else
        echo "[smoke] Direct extraction failed; attempting to trim to ${SMOKE_IN} (re-encode) and extract frames"
        # Re-encode trimmed clip to MP4 to improve compatibility for exotic containers like MKV
        timeout ${SMOKE_TIMEOUT_VAL} ffmpeg -y -i "$INPUT_URL" -t ${SMOKE_SECONDS_VAL} -c:v libx264 -c:a aac -strict experimental "$SMOKE_IN" >/workspace/smoke_ffmpeg.log 2>&1 || true
        if [ -f "$SMOKE_IN" ]; then
          timeout ${SMOKE_TIMEOUT_VAL} ffmpeg -y -i "$SMOKE_IN" -vf "select=not(mod(n\\,10))" -vframes 2 "$SMOKE_DIR/frame_%02d.png" >/workspace/smoke_ff_extract.log 2>&1 || true
        else
          echo "[smoke] Failed to produce ${SMOKE_IN}; see /workspace/smoke_ffmpeg.log"
        fi
      fi
    else
      echo "[smoke] No INPUT_URL for smoke-test; skipping smoke-test"
      SMOKE_SECONDS_VAL=0
    fi
  else
    echo "[smoke] ffmpeg not available; attempting wget then ffmpeg if possible"
    if [ -n "$INPUT_URL" ]; then
      wget -O "/workspace/smoke_input_full.mp4" "$INPUT_URL" || true
      if command -v ffmpeg >/dev/null 2>&1; then
        timeout ${SMOKE_TIMEOUT_VAL} ffmpeg -y -i /workspace/smoke_input_full.mp4 -t ${SMOKE_SECONDS_VAL} -c copy "$SMOKE_IN" || true
        # Try direct extraction from downloaded file
        timeout ${SMOKE_TIMEOUT_VAL} ffmpeg -y -i "$SMOKE_IN" -vf "select=not(mod(n\\,10))" -vframes 2 "$SMOKE_DIR/frame_%02d.png" >/workspace/smoke_ff_extract.log 2>&1 || true
      fi
    fi
  fi

  # Report what we found for debugging
  echo "[smoke] Post-extract listing of ${SMOKE_DIR} (first 20 entries):"
  ls -la "$SMOKE_DIR" 2>/dev/null | sed -n '1,20p' || true
  echo "[smoke] tail of smoke_ff_extract.log (if present):"
  tail -n 50 /workspace/smoke_ff_extract.log 2>/dev/null || true

  # Normalize frame filename detection for downstream steps — prefer frame_01.png but accept frame_1.png
  FOUND_FRAME=""
  if [ -f "$SMOKE_DIR/frame_01.png" ]; then
    FOUND_FRAME="$SMOKE_DIR/frame_01.png"
  elif [ -f "$SMOKE_DIR/frame_1.png" ]; then
    FOUND_FRAME="$SMOKE_DIR/frame_1.png"
  else
    # try any frame_*.png
    FOUND_FRAME=$(ls "$SMOKE_DIR"/frame_*.png 2>/dev/null | head -n1 || true)
  fi

  if [ -n "$FOUND_FRAME" ]; then
    echo "[smoke] Using frame: $FOUND_FRAME"
  else
    echo "[smoke] No extracted frames found in $SMOKE_DIR"
  fi

  # RIFE test: run inference on the two frames using RIFE inference_img.py if available
  if [ -d "/workspace/project/external/RIFE" ] && [ -f "/workspace/project/external/RIFE/inference_img.py" ]; then
    echo "[smoke] Running RIFE inference on two frames"

    # Check if models were copied successfully
    if [ ! -f "/workspace/project/external/RIFE/train_log/flownet.pkl" ]; then
      echo "[smoke] WARNING: RIFE models not found in /workspace/project/external/RIFE/train_log/"
      echo "[smoke] Smoke-test will likely fail, but continuing to show actual error..."
    fi

    cd /workspace/project/external/RIFE || true
    # Set PYTHONPATH to include RIFE directory for module imports
    # Build args for inference_img.py based on detected frames
    FRAME_A="$FOUND_FRAME"
    # pick a second frame if available
    if [ -f "$SMOKE_DIR/frame_02.png" ]; then
      FRAME_B="$SMOKE_DIR/frame_02.png"
    elif [ -f "$SMOKE_DIR/frame_2.png" ]; then
      FRAME_B="$SMOKE_DIR/frame_2.png"
    else
      # try to find any second frame
      FRAME_B=$(ls "$SMOKE_DIR"/frame_*.png 2>/dev/null | sed -n '2p' || true)
    fi

    if [ -n "$FRAME_A" ] && [ -n "$FRAME_B" ]; then
      PYTHONPATH=/workspace/project/external/RIFE:$PYTHONPATH python3 /workspace/project/external/RIFE/inference_img.py --img "$FRAME_A" "$FRAME_B" --ratio 0.5 --model train_log >/workspace/smoke_rife.log 2>&1 || true
    else
      echo "[smoke] Not enough frames for RIFE smoke-test; skipping RIFE step"
    fi

    # Check for output file existence or success markers
    if [ -f "output.png" ] || [ -f "$SMOKE_DIR/frame_01_02_mid.png" ] || grep -qi "Loaded v3.x HD model" /workspace/smoke_rife.log 2>/dev/null; then
      echo "[smoke] ✓ RIFE smoke-test passed"
    else
      echo "[smoke] ✗ RIFE smoke-test failed - showing log:"
      echo "--- smoke_rife.log ---"
      cat /workspace/smoke_rife.log 2>/dev/null || echo "Log file not found"
      echo "--- end log ---"
      echo ""
      echo "⚠️  SMOKE-TEST FAILED (RIFE)"
      echo "This usually means models are missing in /opt/rife_models/train_log/"
      echo "The main pipeline will likely fail. Consider:"
      echo "  1. Rebuild image with models included"
      echo "  2. Set RIFE_MODEL_URL in config to auto-download"
      echo "  3. Set advanced.strict: false to allow fallback"
      echo ""
      echo "Continuing anyway to see full pipeline error..."
    fi
  else
    echo "[smoke] RIFE inference script not available; skipping RIFE step"
  fi

  # Real-ESRGAN test: use batch upscale script for single frame
  if [ -f "/workspace/project/realesrgan_batch_upscale.py" ]; then
    echo "[smoke] Running Real-ESRGAN batch upscale on one frame"
    mkdir -p "$SMOKE_DIR/esr_input" "$SMOKE_DIR/esr_output"

    # choose the frame to use for Real-ESRGAN
    ESR_SRC=""
    if [ -n "$FOUND_FRAME" ]; then
      ESR_SRC="$FOUND_FRAME"
    elif [ -f "$SMOKE_DIR/frame_01.png" ]; then
      ESR_SRC="$SMOKE_DIR/frame_01.png"
    elif [ -f "$SMOKE_DIR/frame_1.png" ]; then
      ESR_SRC="$SMOKE_DIR/frame_1.png"
    else
      ESR_SRC=$(ls "$SMOKE_DIR"/frame_*.png 2>/dev/null | head -n1 || true)
    fi

    if [ -n "$ESR_SRC" ] && [ -f "$ESR_SRC" ]; then
      cp "$ESR_SRC" "$SMOKE_DIR/esr_input/frame_000001.png" || true

      timeout ${SMOKE_TIMEOUT_VAL} python3 /workspace/project/realesrgan_batch_upscale.py \
        "$SMOKE_DIR/esr_input" "$SMOKE_DIR/esr_output" \
        --scale 2 --batch-size 1 --device cuda >/workspace/smoke_realesrgan.log 2>&1 || true

      # Check for output
      if [ -f "$SMOKE_DIR/esr_output/frame_000001.png" ]; then
        echo "[smoke] ✓ Real-ESRGAN smoke-test passed"
      else
        echo "[smoke] ✗ Real-ESRGAN smoke-test failed - showing log:"
        echo "--- smoke_realesrgan.log ---"
        head -50 /workspace/smoke_realesrgan.log 2>/dev/null || echo "(log file not found)"
        echo "--- end log ---"
        echo ""
        echo "⚠️  SMOKE-TEST WARNING: Real-ESRGAN failed"
        echo "This may indicate:"
        echo "  1. Missing Real-ESRGAN models in /opt/realesrgan_models/"
        echo "  2. GPU/CUDA issue (check GPU is available)"
        echo "  3. Out of memory"
        echo ""
        echo "📝 Continuing anyway - main pipeline will show detailed error if Real-ESRGAN truly broken..."
      fi
    else
      echo "[smoke] No frame available for Real-ESRGAN smoke-test; skipping"
    fi
  elif [ -x "/workspace/project/run_realesrgan_pytorch.sh" ]; then
    echo "[smoke] ⚠️  Skipping Real-ESRGAN smoke-test (requires video, not single frame)"
    echo "[smoke] Will test Real-ESRGAN during main pipeline processing"
  else
    echo "[smoke] Real-ESRGAN scripts not available; skipping Real-ESRGAN test"
  fi

  echo "=== SMOKE-TEST COMPLETE ==="
fi

# Run pipeline - CONFIG-DRIVEN or ENV-DRIVEN
if [ "$USE_CONFIG" = true ]; then
  echo ""
  echo "=== CONFIG-DRIVEN WORKFLOW ==="
  echo "Using config from: $CONFIG_FILE"
  echo ""

  # Show config content (for debugging)
  echo "--- Config preview ---"
  head -n 20 "$CONFIG_FILE" || echo "Could not preview config"
  echo "--- End preview ---"
  echo ""

  # Run using container_config_runner.py which reads config.yaml
  if [ -f "/workspace/project/scripts/container_config_runner.py" ]; then
    echo "[remote_runner] Running with config.yaml via container_config_runner.py..."
    env B2_KEY="$B2_KEY" B2_SECRET="$B2_SECRET" B2_BUCKET="$B2_BUCKET" B2_ENDPOINT="$B2_ENDPOINT" python3 /workspace/project/scripts/container_config_runner.py "$CONFIG_FILE"
  else
    echo "ERROR: container_config_runner.py not found!"
    echo "Falling back to ENV-driven mode..."
    USE_CONFIG=false
  fi
fi

# Fallback to ENV-driven mode (legacy) has been disabled to avoid accidental
# single-file processing when a config.yaml is present or when batch inputs are configured.
if [ "$USE_CONFIG" = false ]; then
  echo ""
  echo "=== ENV-DRIVEN WORKFLOW DISABLED ==="
  echo "Config file not found (config.yaml) and ENV-driven single-file mode is disabled by policy."
  echo "If you intended to run a single-file job, provide a config.yaml or re-enable ENV-driven mode manually."
  exit 0
fi

echo ""
echo "remote_runner done"
echo "[remote_runner] SUCCESS! Exiting container..."

# Exit explicitly to prevent restart
exit 0
