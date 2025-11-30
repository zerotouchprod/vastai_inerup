#!/usr/bin/env bash
# Wrapper to run Real-ESRGAN (PyTorch) if available in /workspace/project/external/Real-ESRGAN
# Note: NOT using set -e to allow proper error handling
# Usage: run_realesrgan_pytorch.sh <input> <output> <scale:int (default 4)>
INFILE=${1:-}
OUTFILE=${2:-}
SCALE=${3:-4}

if [ -z "$INFILE" ] || [ -z "$OUTFILE" ]; then
  echo "Usage: $0 <input-file> <output-file> <scale:int (default 4)>"
  exit 2
fi

REPO_DIR="/workspace/project/external/Real-ESRGAN"
if [ ! -d "$REPO_DIR" ]; then
  echo "Real-ESRGAN repo not found in $REPO_DIR. Place Real-ESRGAN cloned repo there or adjust Dockerfile.pytorch to clone it."
  exit 3
fi

# --- Runtime safety defaults (no image rebuild required) ---
# Disable torch.compile by default to avoid increased peak memory / libcuda inductor issues
export TORCH_COMPILE_DISABLE=${TORCH_COMPILE_DISABLE:-1}
# FAST_COMPILE enables --torch-compile; default OFF for stability
export FAST_COMPILE=${FAST_COMPILE:-0}
# Conservative BATCH_ARGS tuned for safety: small tile, fp16, single save-worker (batch-size will be set via VRAM mapping unless explicitly provided)
export BATCH_ARGS=${BATCH_ARGS:-"--use-local-temp --save-workers 1 --tile-size 256 --half --out-format png"}
# Disable auto-tuning by default to avoid long micro-sweeps on startup
export AUTO_TUNE_BATCH=${AUTO_TUNE_BATCH:-false}
# Skip live allocation probing by default (use VRAM-only estimate) to fast-start on varied machines
export SKIP_PROBE=${SKIP_PROBE:-1}

# Ensure Python outputs are unbuffered so progress prints appear in real time
export PYTHONUNBUFFERED=1

## VRAM -> batch mapping helpers
vram_to_batch() {
  # Multi-GPU aware: collect memory for all GPUs and use the minimum (conservative)
  local mem_list=""
  local count=0

  if command -v nvidia-smi >/dev/null 2>&1; then
    # produce list of memory totals (MiB), one per GPU
    mem_list=$(nvidia-smi --query-gpu=memory.total --format=csv,nounits,noheader 2>/dev/null | tr -d '\r' || true)
    # normalize whitespace
    mem_list=$(echo "$mem_list" | tr '\n' ' ' | sed -E 's/^ +| +$//g')
  fi

  if [ -z "$mem_list" ]; then
    # fallback to Python torch if available (gives bytes per device)
    if command -v python3 >/dev/null 2>&1; then
      pyout=$(python3 - <<'PY' 2>/dev/null || true
import sys
out=[]
try:
    import torch
    if torch.cuda.is_available():
        for i in range(torch.cuda.device_count()):
            out.append(str(torch.cuda.get_device_properties(i).total_memory))
    else:
        out=[]
except Exception:
    out=[]
print('\n'.join(out))
PY
)
      mem_list=$(echo "$pyout" | awk '{ if ($1) printf "%d\n", ($1/1024/1024); }' | tr -d '\r' | tr '\n' ' ' | sed -E 's/^ +| +$//g')
    fi
  fi

  # If still empty, return 1 as safe default
  if [ -z "$mem_list" ]; then
    echo 1
    return
  fi

  # Build array and compute min and count
  read -r -a arr <<< "$mem_list"
  count=${#arr[@]}
  min_mb=0
  for x in "${arr[@]}"; do
    # ensure integer
    val=$(echo "$x" | tr -cd '0-9')
    if [ -z "$val" ]; then
      continue
    fi
    if [ $min_mb -eq 0 ] || [ $val -lt $min_mb ]; then
      min_mb=$val
    fi
  done

  if [ -z "$min_mb" ] || [ "$min_mb" -eq 0 ]; then
    echo 1
    return
  fi

  gb=$((min_mb / 1024))

  # More conservative mapping (empirical) using minimum per-GPU memory
  # <12GB => batch 1; 12-16 => 2; 16-24 => 4; 24-32 => 8; >=32 => 16
  if [ $gb -lt 12 ]; then
    batch=1
  elif [ $gb -lt 16 ]; then
    batch=2
  elif [ $gb -lt 24 ]; then
    batch=4
  elif [ $gb -lt 32 ]; then
    batch=8
  else
    batch=16
  fi

  # Log details: count and per-GPU sizes and chosen batch
  echo "gpu_mem_list_mb=${mem_list} gpu_count=${count} min_gpu_gb=${gb} chosen_batch=${batch}"
  echo "$batch"
}

apply_vram_batch_mapping() {
  # Only apply when AUTO_TUNE_BATCH is disabled (we don't want to override tuning)
  if [ "${AUTO_TUNE_BATCH:-false}" = "true" ]; then
    echo "AUTO_TUNE_BATCH=true -> skipping VRAM mapping"
    return 0
  fi
  # If BATCH_ARGS already contains --batch-size, do nothing
  if echo "$BATCH_ARGS" | grep -q -- '--batch-size'; then
    echo "BATCH_ARGS already contains --batch-size; skipping VRAM mapping"
    return 0
  fi
  # Call vram_to_batch which prints a diagnostic line then the batch number
  vinfo=$(vram_to_batch)
  # vinfo may contain two lines: diagnostic and batch. Extract last token as batch
  suggested=$(echo "$vinfo" | tail -n1 | tr -d '\r')
  diag=$(echo "$vinfo" | sed '
$ d')
  if [ -n "$diag" ]; then
    echo "VRAM info: $diag"
  fi
  if [ -z "$suggested" ]; then
    suggested=1
  fi
  echo "VRAM->batch mapping: applying suggested batch_size=$suggested"
  BATCH_ARGS="$BATCH_ARGS --batch-size $suggested"
}

# Apply VRAM->batch mapping early so downstream code sees proper BATCH_ARGS
apply_vram_batch_mapping

# Ensure Python outputs are unbuffered so progress prints appear in real time
export PYTHONUNBUFFERED=1

# Enable automatic upload to Backblaze B2 by default; can be disabled by setting AUTO_UPLOAD_B2=0
export AUTO_UPLOAD_B2=${AUTO_UPLOAD_B2:-1}

# upload result path (preserved across runs)
export UPLOAD_RESULT_JSON=${UPLOAD_RESULT_JSON:-/workspace/realesrgan_upload_result.json}

# Optional automatic upload to Backblaze B2 (S3-compatible). Enable by setting AUTO_UPLOAD_B2=1 and B2_BUCKET env.
maybe_upload_b2() {
  local file_path="$1"
  if [ "${AUTO_UPLOAD_B2:-0}" != "1" ]; then
    echo "AUTO_UPLOAD_B2 disabled; skipping upload"
    return 0
  fi
  if [ -z "${B2_BUCKET:-}" ]; then
    echo "AUTO_UPLOAD_B2=1 but B2_BUCKET not set; skipping upload (no bucket configured)"
    return 0
  fi
  if [ ! -f "$file_path" ]; then
    echo "AUTO_UPLOAD_B2: file not found: $file_path"
    return 1
  fi
  # Default object key: prefer B2_OUTPUT_KEY (set by launcher) then B2_KEY (legacy), then basename
  local key
  if [ -n "${B2_OUTPUT_KEY:-}" ]; then
    key="${B2_OUTPUT_KEY}"
  elif [ -n "${B2_KEY:-}" ]; then
    key="${B2_KEY}"
  else
    key="$(basename "$file_path")"
  fi
  echo "AUTO_UPLOAD_B2: uploading $file_path -> s3://${B2_BUCKET}/${key} (endpoint=${B2_ENDPOINT:-})"
  # Ensure directory for result exists
  mkdir -p "$(dirname "$UPLOAD_RESULT_JSON")" 2>/dev/null || true
  # Run upload script and capture stdout/stderr to result json (may contain error text if failed)
  python3 /workspace/project/upload_b2.py --file "$file_path" --bucket "${B2_BUCKET}" --key "$key" --endpoint "${B2_ENDPOINT:-}" > "$UPLOAD_RESULT_JSON" 2>&1
  local rc=$?
  if [ $rc -ne 0 ]; then
    echo "AUTO_UPLOAD_B2: upload script failed (exit $rc). See $UPLOAD_RESULT_JSON for details"
    return $rc
  fi
  echo "AUTO_UPLOAD_B2: upload succeeded; result saved to $UPLOAD_RESULT_JSON"
  # Print a compact machine-friendly line with exact object path for log parsing
  echo "B2_UPLOAD_KEY_USED: s3://${B2_BUCKET}/${key}"
  # print brief summary (first lines)
  head -n 30 "$UPLOAD_RESULT_JSON" || true
  return 0
}

# Try to ensure libcuda.so is visible via a plain symlink; some PyTorch/Inductor code expects libcuda.so
if ! ldconfig -p | grep -q "libcuda.so" 2>/dev/null; then
  echo "NOTICE: libcuda not visible via ldconfig; searching for libcuda.so.* files..."
  FOUND=$(find /lib* /usr/lib* -maxdepth 3 -name 'libcuda.so*' 2>/dev/null | head -n 1 || true)
  if [ -n "$FOUND" ]; then
    echo "Found libcuda candidate: $FOUND"
    if [ ! -e "/usr/lib/libcuda.so" ]; then
      echo "Creating symlink /usr/lib/libcuda.so -> $FOUND"
      mkdir -p /usr/lib 2>/dev/null || true
      ln -sf "$FOUND" /usr/lib/libcuda.so 2>/dev/null || echo "Warning: failed to create symlink /usr/lib/libcuda.so (insufficient permissions?)" >&2
      ldconfig || true
    else
      echo "/usr/lib/libcuda.so already exists"
    fi
  else
    echo "WARNING: libcuda.so not found anywhere inside container. Ensure the host driver is exposed (mount libcuda or use --gpus)" >&2
  fi
else
  echo "libcuda is already visible via ldconfig"
fi

# --- FFmpeg encoder selection + progress helper
# choose available encoder (prefer NVENC h264 then hevc, fallback libx264)
choose_video_encoder() {
  # Respect forced overrides from environment for testing/debug
  # FORCE_SW_ENC=1 -> force software libx264
  # FORCE_ENC=<encoder_name> -> force specific encoder string (e.g. h264_nvenc or hevc_nvenc)
  if [ "${FORCE_SW_ENC:-0}" = "1" ]; then
    echo "libx264";
    return;
  fi
  if [ -n "${FORCE_ENC:-}" ]; then
    echo "${FORCE_ENC}";
    return;
  fi
  if command -v ffmpeg >/dev/null 2>&1 && ffmpeg -hide_banner -encoders 2>/dev/null | grep -qE "h264_nvenc"; then
    echo "h264_nvenc"
  elif command -v ffmpeg >/dev/null 2>&1 && ffmpeg -hide_banner -encoders 2>/dev/null | grep -qE "hevc_nvenc"; then
    echo "hevc_nvenc"
  else
    echo "libx264"
  fi
}

# determine output pixel format conservatively based on input file pix_fmt and encoder support
choose_out_pix_fmt() {
  local infile="$1"
  local enc="$2"
  local inp
  inp=$(ffprobe -v error -select_streams v:0 -show_entries stream=pix_fmt -of default=nokey=1:noprint_wrappers=1 "$infile" 2>/dev/null | head -n1 || true)
  echo "INPUT_PIX_FMT:${inp}"
  # default safe 8-bit
  local outpf="yuv420p"
  # if input is 10-bit and encoder is hevc_nvenc, try 10-bit hevc
  if echo "$inp" | grep -q "10" 2>/dev/null && [ "$enc" = "hevc_nvenc" ]; then
    outpf="yuv420p10le"
  fi
  echo "$outpf"
}

# run ffmpeg with chosen encoder and emit machine-friendly progress lines prefixed with FFPROGRESS:
# usage: run_ffmpeg_with_progress <outfile> -- <ffmpeg-args...>
run_ffmpeg_with_progress() {
  local outfile="$1"; shift
  # consume '--' if present
  if [ "$1" = "--" ]; then shift; fi
  local enc
  enc=$(choose_video_encoder)
  echo "FFENCODER_CHOSEN:${enc}"
  local pixfmt
  if [ -n "$INFILE" ]; then
    pixfmt=$(choose_out_pix_fmt "$INFILE" "$enc")
  else
    pixfmt="yuv420p"
  fi
  echo "FFOUT_PIX_FMT:${pixfmt}"

  local enc_args=()
  if [ "$enc" = "libx264" ]; then
    enc_args=("-c:v" "libx264" "-crf" "18" "-preset" "medium" "-pix_fmt" "$pixfmt")
  else
    # NVENC args - conservative presets and quality tuned for good visual results
    enc_args=("-c:v" "$enc" "-preset" "p6" "-rc" "vbr_hq" "-cq" "19" "-b:v" "0" "-pix_fmt" "$pixfmt")
  fi

  # Build full ffmpeg command: user-supplied args first, encoder args appended, add progress pipe
  # We redirect ffmpeg stderr to a prefixed FFERR: stream and parse progress from stdout
  # Use -progress pipe:1 -nostats to get machine-friendly progress lines on stdout
  # Show a readable command preview (join user args and encoder args safely)
  echo "FFCMD: ffmpeg -y $* ${enc_args[*]} -progress pipe:1 -nostats $outfile"

  # Run ffmpeg; capture stdout(progress) and stderr
  ffmpeg -y "$@" "${enc_args[@]}" -progress pipe:1 -nostats "$outfile" 2> >(while IFS= read -r el; do echo "FFERR:$el"; done) | while IFS= read -r pl; do
    # progress lines are key=value
    if echo "$pl" | grep -q '=' 2>/dev/null; then
      k=$(echo "$pl" | cut -d'=' -f1)
      v=$(echo "$pl" | cut -d'=' -f2-)
      echo "FFPROGRESS:$k=$v"
    else
      echo "FFPROGRESS:$pl"
    fi
  done
  local rc=${PIPESTATUS[0]:-0}
  return $rc
}

# Function to perform frame-by-frame upscaling (used as fallback)
do_frame_by_frame_upscale() {
  local INPUT="$1"
  local OUTPUT="$2"
  local SCALE_FACTOR="$3"

  echo "=== Using frame-by-frame upscaling method ==="

  if [ ! -f "$REPO_DIR/inference_realesrgan.py" ]; then
    echo "ERROR: inference_realesrgan.py not found in $REPO_DIR"
    return 1
  fi

  TMP_DIR=$(mktemp -d)
  echo "Created temp directory: $TMP_DIR"

  # Extract frames
  echo "Extracting frames from input video..."
  mkdir -p "$TMP_DIR/input" "$TMP_DIR/output"
  # Extract frames as 8-bit RGB to avoid 10-bit -> 8-bit misinterpretation by downstream tools
  ffmpeg -v warning -i "$INPUT" -pix_fmt rgb24 -qscale:v 1 "$TMP_DIR/input/frame_%06d.png"

  if [ $? -ne 0 ]; then
    echo "ERROR: Failed to extract frames"
    rm -rf "$TMP_DIR"
    return 1
  fi

  FRAME_COUNT=$(ls -1 "$TMP_DIR/input"/*.png 2>/dev/null | wc -l)
  echo "Extracted $FRAME_COUNT frames, upscaling each frame (this will take a while)..."
  echo "Progress will be shown by Real-ESRGAN..."

  # Get FPS for reassembly
  FPS=$(ffprobe -v error -select_streams v:0 -show_entries stream=r_frame_rate -of default=noprint_wrappers=1:nokey=1 "$INPUT" 2>/dev/null | head -1 | awk -F'/' '{if (NF==2) print $1/$2; else print $1}')
  [ -z "$FPS" ] && FPS="24"
  echo "Video FPS: $FPS"

  # Use BATCH upscaling for 10x speed improvement!
  BATCH_SCRIPT="/workspace/project/realesrgan_batch_upscale.py"

  if [ -f "$BATCH_SCRIPT" ]; then
    echo ""
    echo "=========================================="
    echo "🚀 Using BATCH Real-ESRGAN upscaling (GPU accelerated - 10x FASTER!)"
    echo "   Frames: $FRAME_COUNT x${SCALE_FACTOR}"
    echo "   Method: Parallel GPU processing"
    echo "=========================================="
    echo ""

    # Allow overriding batch args via BATCH_ARGS env var (e.g. "--batch-size 16 --use-local-temp --save-workers 8")
    if [ -n "$BATCH_ARGS" ]; then
      # If AUTO_TUNE_BATCH is unset or true, strip any explicit --batch-size N from BATCH_ARGS
      if [ "${AUTO_TUNE_BATCH:-true}" = "true" ]; then
        # remove occurrences of '--batch-size <num>' from BATCH_ARGS (simple grep/sed)
        CLEANED_BATCH_ARGS=$(echo "$BATCH_ARGS" | sed -E "s/--batch-size(=|[[:space:]]+)[0-9]+//g")
        # collapse multiple spaces
        CLEANED_BATCH_ARGS=$(echo "$CLEANED_BATCH_ARGS" | tr -s ' ')
        echo "Using BATCH_ARGS (auto-tune enabled; stripped --batch-size if present): $CLEANED_BATCH_ARGS"
        # Append torch-compile flag if requested via env
        if [ "${FAST_COMPILE:-false}" = "1" ] || [ "${FAST_COMPILE:-false}" = "true" ]; then
          bash /workspace/project/realesrgan_batch_safe.sh "$TMP_DIR/input" "$TMP_DIR/output" $CLEANED_BATCH_ARGS --scale $SCALE_FACTOR --device cuda --torch-compile
        else
          bash /workspace/project/realesrgan_batch_safe.sh "$TMP_DIR/input" "$TMP_DIR/output" $CLEANED_BATCH_ARGS --scale $SCALE_FACTOR --device cuda
        fi
      else
        echo "Using BATCH_ARGS: $BATCH_ARGS"
        if [ "${FAST_COMPILE:-false}" = "1" ] || [ "${FAST_COMPILE:-false}" = "true" ]; then
          bash /workspace/project/realesrgan_batch_safe.sh "$TMP_DIR/input" "$TMP_DIR/output" $BATCH_ARGS --scale $SCALE_FACTOR --device cuda --torch-compile
        else
          bash /workspace/project/realesrgan_batch_safe.sh "$TMP_DIR/input" "$TMP_DIR/output" $BATCH_ARGS --scale $SCALE_FACTOR --device cuda
        fi
      fi
    else
      # No explicit batch args -> let batch script auto-tune for this GPU
      if [ "${FAST_COMPILE:-false}" = "1" ] || [ "${FAST_COMPILE:-false}" = "true" ]; then
        bash /workspace/project/realesrgan_batch_safe.sh "$TMP_DIR/input" "$TMP_DIR/output" --scale $SCALE_FACTOR --device cuda --torch-compile
      else
        bash /workspace/project/realesrgan_batch_safe.sh "$TMP_DIR/input" "$TMP_DIR/output" --scale $SCALE_FACTOR --device cuda
      fi
    fi

    if [ $? -ne 0 ]; then
      echo "⚠️ Batch upscaling failed, falling back to frame-by-frame method..."

      # Fallback to old method
      # Start progress monitor
      (
        START_TIME=$(date +%s)
        while sleep 5; do
          CURR_COUNT=$(ls -1 "$TMP_DIR/output"/*.png 2>/dev/null | wc -l)
          if [ "$CURR_COUNT" -gt 0 ]; then
            PERCENT=$((CURR_COUNT * 100 / FRAME_COUNT))
            ELAPSED=$(($(date +%s) - START_TIME))

            # Calculate ETA
            if [ "$CURR_COUNT" -gt 0 ] && [ "$ELAPSED" -gt 0 ]; then
              FRAMES_PER_SEC=$(echo "scale=2; $CURR_COUNT / $ELAPSED" | bc -l 2>/dev/null || echo "0")
              REMAINING=$((FRAME_COUNT - CURR_COUNT))
              ETA_SEC=$(echo "scale=0; $REMAINING / $FRAMES_PER_SEC" | bc -l 2>/dev/null || echo "0")
              ETA_MIN=$((ETA_SEC / 60))

              echo "[$(date '+%H:%M:%S')] 📊 Progress: $CURR_COUNT/$FRAME_COUNT frames ($PERCENT%) | Speed: ${FRAMES_PER_SEC} fps | ETA: ~${ETA_MIN}m"
            else
              echo "[$(date '+%H:%M:%S')] 📊 Progress: $CURR_COUNT/$FRAME_COUNT frames ($PERCENT%)"
            fi
          fi
        done
      ) &
      PROGRESS_PID=$!

      cd "$REPO_DIR" && python3 -u inference_realesrgan.py -i "$TMP_DIR/input" -o "$TMP_DIR/output" -n RealESRGAN_x4plus -s $SCALE_FACTOR --tile 256 2>&1 | tr '\r' '\n' | while IFS= read -r line; do
        # Show progress lines but filter out excessive warnings
        if echo "$line" | grep -qE "Processing|Progress|%|\[.*\]|frame|Upscaling"; then
          echo "$line"
        elif echo "$line" | grep -qE "ERROR|WARN|Failed"; then
          echo "$line"
        fi
      done

      # Stop progress monitor
      kill $PROGRESS_PID 2>/dev/null || true
    fi
  else
    echo "⚠️ Batch script not found, using slower frame-by-frame method..."

    # Start progress monitor
    (
      START_TIME=$(date +%s)
      while sleep 5; do
        CURR_COUNT=$(ls -1 "$TMP_DIR/output"/*.png 2>/dev/null | wc -l)
        if [ "$CURR_COUNT" -gt 0 ]; then
          PERCENT=$((CURR_COUNT * 100 / FRAME_COUNT))
          ELAPSED=$(($(date +%s) - START_TIME))

          # Calculate ETA
          if [ "$CURR_COUNT" -gt 0 ] && [ "$ELAPSED" -gt 0 ]; then
            FRAMES_PER_SEC=$(echo "scale=2; $CURR_COUNT / $ELAPSED" | bc -l 2>/dev/null || echo "0")
            REMAINING=$((FRAME_COUNT - CURR_COUNT))
            ETA_SEC=$(echo "scale=0; $REMAINING / $FRAMES_PER_SEC" | bc -l 2>/dev/null || echo "0")
            ETA_MIN=$((ETA_SEC / 60))

            echo "[$(date '+%H:%M:%S')] 📊 Progress: $CURR_COUNT/$FRAME_COUNT frames ($PERCENT%) | Speed: ${FRAMES_PER_SEC} fps | ETA: ~${ETA_MIN}m"
          else
            echo "[$(date '+%H:%M:%S')] 📊 Progress: $CURR_COUNT/$FRAME_COUNT frames ($PERCENT%)"
          fi
        fi
      done
    ) &
    PROGRESS_PID=$!

    cd "$REPO_DIR" && python3 -u inference_realesrgan.py -i "$TMP_DIR/input" -o "$TMP_DIR/output" -n RealESRGAN_x4plus -s $SCALE_FACTOR --tile 256 2>&1 | tr '\r' '\n' | while IFS= read -r line; do
      # Show progress lines but filter out excessive warnings
      if echo "$line" | grep -qE "Processing|Progress|%|\[.*\]|frame|Upscaling"; then
        echo "$line"
      elif echo "$line" | grep -qE "ERROR|WARN|Failed"; then
        echo "$line"
      fi
    done

    # Stop progress monitor
    kill $PROGRESS_PID 2>/dev/null || true
  fi
  wait $PROGRESS_PID 2>/dev/null || true

  if [ $? -ne 0 ]; then
    echo ""
    echo "ERROR: Frame-by-frame upscaling failed"
    rm -rf "$TMP_DIR"
    return 1
  fi

  # Count output frames
  OUTPUT_FRAME_COUNT=$(ls -1 "$TMP_DIR/output"/*.png 2>/dev/null | wc -l)
  echo ""
  echo "=========================================="
  echo "Upscaling complete! Processed $OUTPUT_FRAME_COUNT frames"
  echo "=========================================="
  echo ""

  if [ "$OUTPUT_FRAME_COUNT" -ne "$FRAME_COUNT" ]; then
    echo "ERROR: Frame count mismatch after upscaling!"
    rm -rf "$TMP_DIR"
    return 1
  fi

  # Extract audio
  echo "Extracting audio track from original video..."
  # Use ffprobe to determine audio codec/extension and extract using copy; report with prefix for watcher
  if command -v ffprobe >/dev/null 2>&1; then
    a_codec=$(ffprobe -v error -select_streams a:0 -show_entries stream=codec_name -of default=nokey=1:noprint_wrappers=1 "$INPUT" 2>/dev/null | head -n1 || true)
  else
    a_codec=""
  fi
  if [ -n "$a_codec" ]; then
    echo "FFPROGRESS:audio_codec=$a_codec"
  fi
  run_ffmpeg_with_progress "$TMP_DIR/audio.aac" -- -i "$INPUT" -vn -acodec copy
  if [ -f "$TMP_DIR/audio.aac" ]; then
    echo "✓ Audio extracted"
  else
    echo "No audio track found"
  fi

  # Reassemble video
  echo ""
  echo "=========================================="
  echo "Reassembling upscaled video with audio..."
  echo "This may take a few minutes..."
  echo "=========================================="
  echo ""

  if [ -f "$TMP_DIR/audio.aac" ]; then
    run_ffmpeg_with_progress "$OUTPUT" -- -framerate "$FPS" -i "$TMP_DIR/output/frame_%06d_out.png" -i "$TMP_DIR/audio.aac" -shortest
  else
    run_ffmpeg_with_progress "$OUTPUT" -- -framerate "$FPS" -i "$TMP_DIR/output/frame_%06d_out.png"
  fi

  local RESULT=$?
  rm -rf "$TMP_DIR"

  if [ $RESULT -ne 0 ]; then
    echo ""
    echo "ERROR: Failed to reassemble video"
    return 1
  fi

  echo ""
  echo "=========================================="
  echo "✓ Frame-by-frame upscaling completed successfully"
  OUTPUT_SIZE=$(ls -lh "$OUTPUT" 2>/dev/null | awk '{print $5}')
  echo "Output file: $OUTPUT ($OUTPUT_SIZE)"
  echo "=========================================="
  # Optional upload first (if enabled), then write sentinel
  if [ "${AUTO_UPLOAD_B2:-0}" = "1" ]; then
    maybe_upload_b2 "$OUTPUT"
    rc=$?
    if [ $rc -ne 0 ]; then
      echo "AUTO_UPLOAD_B2: upload failed (rc=$rc). Continuing without upload. See $UPLOAD_RESULT_JSON for details"
    else
      echo "AUTO_UPLOAD_B2: upload succeeded"
    fi
  else
    echo "AUTO_UPLOAD_B2 not enabled; skipping upload"
  fi
  echo "VASTAI_PIPELINE_COMPLETED_SUCCESSFULLY"
  touch /workspace/VASTAI_PIPELINE_COMPLETED_SUCCESSFULLY 2>/dev/null || true
  rm -rf "$TMP_DIR"
  exit 0
}

# helper: write assembly info (frames, duration, size) and perform upload+sentinel
finalize_success() {
  local file="$1"
  local info_json="/workspace/realesrgan_assembly_info.json"
  local frames="unknown"
  local duration="unknown"
  local size="unknown"
  if command -v ffprobe >/dev/null 2>&1; then
    # attempt to read exact frame count
    frames=$(ffprobe -v error -count_frames -select_streams v:0 -show_entries stream=nb_read_frames -of default=nokey=1:noprint_wrappers=1 "$file" 2>/dev/null || true)
    if [ -z "$frames" ] || [ "$frames" = "N/A" ]; then
      # fallback to estimating via ffprobe format nb_frames or default
      frames=$(ffprobe -v error -select_streams v:0 -show_entries stream=nb_frames -of default=nokey=1:noprint_wrappers=1 "$file" 2>/dev/null || true)
    fi
    duration=$(ffprobe -v error -show_entries format=duration -of default=nokey=1:noprint_wrappers=1 "$file" 2>/dev/null || true)
  fi
  size=$(ls -l "$file" 2>/dev/null | awk '{print $5}' || true)
  # sanitize empty
  frames=${frames:-unknown}
  duration=${duration:-unknown}
  size=${size:-unknown}
  # Write JSON-ish info (no dependency on jq)
  printf '{\n  "file": "%s",\n  "frames": "%s",\n  "duration": "%s",\n  "size": "%s"\n}\n' "$file" "$frames" "$duration" "$size" > "$info_json" || true
  echo "Assembly info saved to $info_json"
  echo "Assembly summary: frames=$frames duration=$duration size=$size"
  # attempt upload if enabled
  if [ "${AUTO_UPLOAD_B2:-0}" = "1" ]; then
    maybe_upload_b2 "$file"
    rc=$?
    if [ $rc -ne 0 ]; then
      echo "AUTO_UPLOAD_B2: upload failed (rc=$rc). See $UPLOAD_RESULT_JSON and $info_json for details"
    else
      echo "AUTO_UPLOAD_B2: upload succeeded"
      # Attempt to parse upload_result and echo the object path in a compact line
      if [ -f "$UPLOAD_RESULT_JSON" ]; then
        # Try to extract bucket/key from JSON (simple grep + sed for portability)
        BUCKET=$(grep -oP '"bucket"\s*:\s*"\K[^"]+' "$UPLOAD_RESULT_JSON" 2>/dev/null || true)
        KEY=$(grep -oP '"key"\s*:\s*"\K[^"]+' "$UPLOAD_RESULT_JSON" 2>/dev/null || true)
        if [ -n "$BUCKET" ] && [ -n "$KEY" ]; then
          echo "B2_UPLOAD_KEY_USED: s3://$BUCKET/$KEY"
        fi
      fi
    fi
  else
    echo "AUTO_UPLOAD_B2 not enabled; skipping upload"
  fi
  # final sentinel
  echo "VASTAI_PIPELINE_COMPLETED_SUCCESSFULLY"
  touch /workspace/VASTAI_PIPELINE_COMPLETED_SUCCESSFULLY 2>/dev/null || true
}

# Try BATCH upscaling first (10x faster!)
BATCH_SCRIPT="/workspace/project/realesrgan_batch_upscale.py"
if [ -f "$BATCH_SCRIPT" ]; then
  echo "=========================================="
  echo "🚀 Using BATCH Real-ESRGAN (GPU accelerated - 10x FASTER!)"
  echo "   Method: Parallel GPU batch processing"
  echo "=========================================="
  echo ""

  # Extract frames to temp dir
  TMP_DIR=$(mktemp -d)
  echo "Extracting frames to $TMP_DIR..."
  mkdir -p "$TMP_DIR/input" "$TMP_DIR/output"

  # Extract frames as 8-bit RGB to avoid 10-bit -> 8-bit misinterpretation by downstream tools
  ffmpeg -v warning -i "$INFILE" -pix_fmt rgb24 -qscale:v 1 "$TMP_DIR/input/frame_%06d.png"

  if [ $? -eq 0 ]; then
    FRAME_COUNT=$(ls -1 "$TMP_DIR/input"/*.png 2>/dev/null | wc -l)
    echo "Extracted $FRAME_COUNT frames"
    echo ""

    # Get FPS for reassembly
    FPS=$(ffprobe -v error -select_streams v:0 -show_entries stream=r_frame_rate -of default=noprint_wrappers=1:nokey=1 "$INFILE" 2>/dev/null | head -1 | awk -F'/' '{if (NF==2) print $1/$2; else print $1}')
    [ -z "$FPS" ] && FPS="24"

    # Run batch upscale (with progress)
    # Use larger batch size for better GPU utilization
    # If SCALE=2 or 4, use it directly; otherwise auto-detect best scale for 4K
    if [ "$SCALE" = "2" ] || [ "$SCALE" = "4" ]; then
      echo "Using explicit scale: ${SCALE}x"
      # Allow BATCH_ARGS override; otherwise let batch script auto-tune
      if [ -n "$BATCH_ARGS" ]; then
        if [ "${AUTO_TUNE_BATCH:-true}" = "true" ]; then
          CLEANED_BATCH_ARGS=$(echo "$BATCH_ARGS" | sed -E "s/--batch-size(=|[[:space:]]+)[0-9]+//g")
          CLEANED_BATCH_ARGS=$(echo "$CLEANED_BATCH_ARGS" | tr -s ' ')
          echo "Using BATCH_ARGS (auto-tune enabled; stripped --batch-size if present): $CLEANED_BATCH_ARGS"
          if [ "${FAST_COMPILE:-false}" = "1" ] || [ "${FAST_COMPILE:-false}" = "true" ]; then
            bash /workspace/project/realesrgan_batch_safe.sh "$TMP_DIR/input" "$TMP_DIR/output" $CLEANED_BATCH_ARGS --scale $SCALE --device cuda --torch-compile
          else
            bash /workspace/project/realesrgan_batch_safe.sh "$TMP_DIR/input" "$TMP_DIR/output" $CLEANED_BATCH_ARGS --scale $SCALE --device cuda
          fi
        else
          echo "Using BATCH_ARGS: $BATCH_ARGS"
          if [ "${FAST_COMPILE:-false}" = "1" ] || [ "${FAST_COMPILE:-false}" = "true" ]; then
            bash /workspace/project/realesrgan_batch_safe.sh "$TMP_DIR/input" "$TMP_DIR/output" $BATCH_ARGS --scale $SCALE --device cuda --torch-compile
          else
            bash /workspace/project/realesrgan_batch_safe.sh "$TMP_DIR/input" "$TMP_DIR/output" $BATCH_ARGS --scale $SCALE --device cuda
          fi
        fi
      else
        bash /workspace/project/realesrgan_batch_safe.sh "$TMP_DIR/input" "$TMP_DIR/output" --scale $SCALE --device cuda
      fi
    else
      # Auto-mode: target 4K (2160p) height
      echo "Auto-detecting best scale for 4K target..."
      if [ -n "$BATCH_ARGS" ]; then
        if [ "${AUTO_TUNE_BATCH:-true}" = "true" ]; then
          CLEANED_BATCH_ARGS=$(echo "$BATCH_ARGS" | sed -E "s/--batch-size(=|[[:space:]]+)[0-9]+//g")
          CLEANED_BATCH_ARGS=$(echo "$CLEANED_BATCH_ARGS" | tr -s ' ')
          echo "Using BATCH_ARGS (auto-tune enabled; stripped --batch-size if present): $CLEANED_BATCH_ARGS"
          if [ "${FAST_COMPILE:-false}" = "1" ] || [ "${FAST_COMPILE:-false}" = "true" ]; then
            bash /workspace/project/realesrgan_batch_safe.sh "$TMP_DIR/input" "$TMP_DIR/output" $CLEANED_BATCH_ARGS --target-height 2160 --device cuda --torch-compile
          else
            bash /workspace/project/realesrgan_batch_safe.sh "$TMP_DIR/input" "$TMP_DIR/output" $CLEANED_BATCH_ARGS --target-height 2160 --device cuda
          fi
        else
          echo "Using BATCH_ARGS: $BATCH_ARGS"
          if [ "${FAST_COMPILE:-false}" = "1" ] || [ "${FAST_COMPILE:-false}" = "true" ]; then
            bash /workspace/project/realesrgan_batch_safe.sh "$TMP_DIR/input" "$TMP_DIR/output" $BATCH_ARGS --target-height 2160 --device cuda --torch-compile
          else
            bash /workspace/project/realesrgan_batch_safe.sh "$TMP_DIR/input" "$TMP_DIR/output" $BATCH_ARGS --target-height 2160 --device cuda
          fi
        fi
      else
        bash /workspace/project/realesrgan_batch_safe.sh "$TMP_DIR/input" "$TMP_DIR/output" --target-height 2160 --device cuda
      fi
    fi

    if [ $? -eq 0 ] && [ -n "$(ls -A $TMP_DIR/output 2>/dev/null)" ]; then
      echo ""
      echo "Reassembling video from upscaled frames..."
      # Assemble from image sequence using predictable pattern (more robust than concat filelist)
      first_file=$(ls -1v "$TMP_DIR/output"/*.{png,jpg,jpeg} 2>/dev/null | head -n1 || true)
      if [ -n "$first_file" ]; then
        ext="${first_file##*.}"
        pattern="frame_%06d.$ext"
        # Count output images and assemble with explicit frame count to avoid ffmpeg stopping early
        OUT_IMG_COUNT=$(ls -1 "$TMP_DIR/output"/*."$ext" 2>/dev/null | wc -l || true)
        if [ -z "$OUT_IMG_COUNT" ] || [ "$OUT_IMG_COUNT" -le 0 ]; then
          echo "ERROR: no images with extension .$ext found in output"
        else
          echo "Assembling video using image2 pattern: $pattern (framerate=$FPS, frames=$OUT_IMG_COUNT)"
          # Determine start number from first file name (handles frame_000000.png vs frame_000001.png)
          base=$(basename "$first_file")
          # extract numeric group: last contiguous digits before the extension
          start_num=$(echo "$base" | sed -E 's/.*_([0-9]+)\..*/\1/')
          # convert to decimal (strip leading zeros)
          start_num=$((10#$start_num))
          echo "Detected start_number=$start_num"
          # Use run_ffmpeg_with_progress to choose encoder and emit progress for external watcher
          run_ffmpeg_with_progress "$OUTFILE" -- -start_number "$start_num" -framerate "$FPS" -i "$TMP_DIR/output/$pattern" -frames:v "$OUT_IMG_COUNT"
          if [ -f "$OUTFILE" ]; then
            echo "✓ Assembled: $OUTFILE"
            finalize_success "$OUTFILE"
            rm -rf "$TMP_DIR"
            exit 0
          else
            echo "ERROR: assembly from pattern failed; attempting concat fallback"
          fi
        fi
      else
        echo "ERROR: no images found in $TMP_DIR/output to assemble"
      fi
      # Fallback: try concat filelist as last resort
      FILELIST="$TMP_DIR/output/filelist.txt"
      : > "$FILELIST" 2>/dev/null || true
      for f in "$TMP_DIR/output"/*.{png,jpg,jpeg}; do
        [ -f "$f" ] && echo "file '$f'" >> "$FILELIST"
      done
      if [ -s "$FILELIST" ]; then
        echo "Trying concat fallback (filelist)"
        run_ffmpeg_with_progress "$OUTFILE" -- -safe 0 -f concat -i "$FILELIST" -framerate "$FPS"
        if [ -f "$OUTFILE" ]; then
          echo "✓ Assembled (concat fallback): $OUTFILE"
          finalize_success "$OUTFILE"
          rm -rf "$TMP_DIR"
          exit 0
        fi
      fi
      echo "ERROR: failed to assemble video from upscaled frames"
       fi
  fi
fi

# Fallback: Try video inference script (slower, but more compatible)
if [ -f "$REPO_DIR/inference_realesrgan_video.py" ]; then
  echo "Using inference_realesrgan_video.py for video upscaling (slower method)"
  echo "Processing video (this may take several minutes)..."

  # Get input video info for debugging
  if command -v ffprobe >/dev/null 2>&1; then
    echo ""
    echo "=========================================="
    echo "Input video info:"
    ffprobe -v error -show_entries format=duration,size,bit_rate -show_entries stream=width,height,nb_frames,r_frame_rate -of default=noprint_wrappers=1 "$INFILE" 2>&1 | head -10
    echo "=========================================="
    echo ""

    # Check nb_frames presence; if missing, prefer frame-by-frame fallback to avoid KeyError in external script
    NB_FRAMES=$(ffprobe -v error -select_streams v:0 -show_entries stream=nb_frames -of default=nokey=1:noprint_wrappers=1 "$INFILE" 2>/dev/null | tr -d '\n') || true
    if [ -z "$NB_FRAMES" ] || [ "$NB_FRAMES" = "N/A" ]; then
      echo "WARNING: ffprobe did not return nb_frames (nb_frames='$NB_FRAMES'), using frame-by-frame fallback to avoid external KeyError"
      do_frame_by_frame_upscale "$INFILE" "$OUTFILE" "$SCALE"
      RESULT=$?
      if [ $RESULT -ne 0 ]; then
        echo "ERROR: frame-by-frame fallback failed"
        exit 4
      else
        exit 0
      fi
    fi
  fi

  # Run Real-ESRGAN with output monitoring
  python3 -u "$REPO_DIR/inference_realesrgan_video.py" -i "$INFILE" -o "$OUTFILE" -n RealESRGAN_x4plus -s $SCALE 2>&1 | tee /tmp/realesrgan_output.log | while IFS= read -r line; do
    # Show progress and important messages
    if echo "$line" | grep -qE "Processing|Progress|%|fps|frame|Upscaling|inference|^\["; then
      echo "$line"
    elif echo "$line" | grep -qE "ERROR|WARN|Failed|Traceback|File.*line"; then
      # Show error/traceback lines
      echo "$line"
    fi
  done
  RESULT=$?

  if [ $RESULT -ne 0 ]; then
    echo "ERROR: Real-ESRGAN inference failed with exit code $RESULT"
    exit 4
  fi

  echo "Inference completed, checking output..."

  # IMPORTANT: inference_realesrgan_video.py may create a directory instead of a file
  # Check if output is a valid video file, if not - search for the actual output
  if [ -d "$OUTFILE" ]; then
    echo "WARNING: Output is a directory, searching for video file inside..."
    echo "Directory contents:"
    ls -lhR "$OUTFILE" || true

    # Find all MP4 files in the directory and subdirectories, sort by size (largest first)
    ACTUAL_VIDEO=$(find "$OUTFILE" -name "*.mp4" -type f -exec ls -s {} \; 2>/dev/null | sort -rn | head -n 1 | awk '{print $2}')

    if [ -n "$ACTUAL_VIDEO" ] && [ -f "$ACTUAL_VIDEO" ]; then
      echo "Found video: $ACTUAL_VIDEO ($(ls -lh "$ACTUAL_VIDEO" | awk '{print $5}'))"
      echo "Moving to $OUTFILE..."

      # Copy the video file out first, then remove the directory
      TEMP_FILE="${OUTFILE}.tmp.mp4"
      cp "$ACTUAL_VIDEO" "$TEMP_FILE"
      rm -rf "$OUTFILE"
      mv "$TEMP_FILE" "$OUTFILE"

      echo "Video moved successfully"
    else
      echo "ERROR: No MP4 file found in output directory"
      echo "Directory structure:"
      find "$OUTFILE" -type f 2>/dev/null || true
      exit 4
    fi
  elif [ ! -f "$OUTFILE" ] || [ ! -s "$OUTFILE" ]; then
    echo "ERROR: Output file missing or empty: $OUTFILE"
    ls -lh "$(dirname "$OUTFILE")" || true
    exit 4
  fi

  # Success — write sentinel so external monitors/pipelines can detect completion
  # Optional upload first (if enabled), then write sentinel
  if [ "${AUTO_UPLOAD_B2:-0}" = "1" ]; then
    maybe_upload_b2 "$OUTFILE"
    rc=$?
    if [ $rc -ne 0 ]; then
      echo "AUTO_UPLOAD_B2: upload failed (rc=$rc). Continuing without upload. See $UPLOAD_RESULT_JSON for details"
    else
      echo "AUTO_UPLOAD_B2: upload succeeded"
    fi
  else
    echo "AUTO_UPLOAD_B2 not enabled; skipping upload"
  fi
  echo "VASTAI_PIPELINE_COMPLETED_SUCCESSFULLY"
  touch /workspace/VASTAI_PIPELINE_COMPLETED_SUCCESSFULLY 2>/dev/null || true
fi
