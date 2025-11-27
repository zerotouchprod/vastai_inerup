#!/usr/bin/env bash
# Wrapper to run Real-ESRGAN (PyTorch) if available in /workspace/project/external/Real-ESRGAN
# Note: NOT using set -e to allow proper error handling
# Usage: run_realesrgan_pytorch.sh <input> <output> <scale>
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
# Conservative BATCH_ARGS tuned for ~15-16GB GPUs (RTX A4000): small tile, fp16, few save-workers
export BATCH_ARGS=${BATCH_ARGS:-"--use-local-temp --save-workers 1 --tile-size 256 --out-format jpg --jpeg-quality 90 --half"}
# Allow auto-tune by default
export AUTO_TUNE_BATCH=${AUTO_TUNE_BATCH:-true}

# Ensure Python outputs are unbuffered so progress prints appear in real time
export PYTHONUNBUFFERED=1

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
  ffmpeg -v warning -i "$INPUT" -qscale:v 1 "$TMP_DIR/input/frame_%06d.png"

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
        PREV_COUNT=0
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
          PREV_COUNT=$CURR_COUNT
        done
      ) &
      PROGRESS_PID=$!

      cd "$REPO_DIR" && python3 -u inference_realesrgan.py -i "$TMP_DIR/input" -o "$TMP_DIR/output" -n RealESRGAN_x4plus -s $SCALE_FACTOR --tile 256 2>&1 | sed -u 's/\r/\\n/g' | while IFS= read -r line; do
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
      PREV_COUNT=0
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
        PREV_COUNT=$CURR_COUNT
      done
    ) &
    PROGRESS_PID=$!

    cd "$REPO_DIR" && python3 -u inference_realesrgan.py -i "$TMP_DIR/input" -o "$TMP_DIR/output" -n RealESRGAN_x4plus -s $SCALE_FACTOR --tile 256 2>&1 | sed -u 's/\r/\\n/g' | while IFS= read -r line; do
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
  ffmpeg -v warning -i "$INPUT" -vn -acodec copy "$TMP_DIR/audio.aac" 2>/dev/null && echo "✓ Audio extracted" || echo "No audio track found"

  # Reassemble video
  echo ""
  echo "=========================================="
  echo "Reassembling upscaled video with audio..."
  echo "This may take a few minutes..."
  echo "=========================================="
  echo ""

  if [ -f "$TMP_DIR/audio.aac" ]; then
    ffmpeg -v warning -stats -framerate "$FPS" -i "$TMP_DIR/output/frame_%06d_out.png" -i "$TMP_DIR/audio.aac" -c:v libx264 -crf 18 -pix_fmt yuv420p -c:a aac -shortest "$OUTPUT"
  else
    ffmpeg -v warning -stats -framerate "$FPS" -i "$TMP_DIR/output/frame_%06d_out.png" -c:v libx264 -crf 18 -pix_fmt yuv420p "$OUTPUT"
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
  echo ""
  return 0
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

  ffmpeg -v warning -i "$INFILE" -qscale:v 1 "$TMP_DIR/input/frame_%06d.png"

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
      # Prefer explicit filelist concat assembly to control order and support JPG
      FILELIST="$TMP_DIR/output/filelist.txt"
      (for f in $(ls -1v "$TMP_DIR/output"/*.{png,jpg,jpeg} 2>/dev/null); do echo "file '$f'"; done) > "$FILELIST" || true
      if [ -s "$FILELIST" ]; then
        echo "Using filelist assembly (first lines):"
        head -n 20 "$FILELIST"
        ffmpeg -y -safe 0 -f concat -i "$FILELIST" -framerate "$FPS" -c:v libx264 -crf 18 -pix_fmt yuv420p "$OUTFILE" >/dev/null 2>&1 || true
        if [ -f "$OUTFILE" ]; then
          echo "✓ Assembled from filelist: $OUTFILE"
          rm -rf "$TMP_DIR"
          exit 0
        else
          echo "filelist assembly failed, falling back to pattern-based assembly"
        fi
      else
        echo "No filelist could be created (no images found); falling back to pattern-based assembly"
      fi

      # Fallback: pattern-based assembly (previous behavior)
      ffmpeg -y -framerate "$FPS" -i "$TMP_DIR/output/frame_%06d.png" -c:v libx264 -crf 18 -preset medium -pix_fmt yuv420p "$OUTFILE" >/dev/null 2>&1

      if [ -f "$OUTFILE" ]; then
        echo "✓ Batch upscaling completed successfully!"
        rm -rf "$TMP_DIR"
        exit 0
      fi
    fi

    echo "⚠️ Batch upscaling failed, falling back to video method..."
    rm -rf "$TMP_DIR"
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
    NB_FRAMES=$(ffprobe -v error -select_streams v:0 -show_entries stream=nb_frames -of default=noprint_wrappers=1:nokey=1 "$INFILE" 2>/dev/null | tr -d '\n') || true
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

fi
