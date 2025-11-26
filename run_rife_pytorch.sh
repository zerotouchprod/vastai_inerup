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

  # Ensure cleanup on exit. If KEEP_TMP=1, preserve TMP_DIR for debugging.
  rc=0
  if [ "${KEEP_TMP:-0}" = "1" ]; then
    log "KEEP_TMP=1 -> temporary dir will be preserved for debugging: $TMP_DIR"
    trap 'rc=$?; echo "KEEP_TMP=1 set; temporary dir preserved: ${TMP_DIR}"; exit $rc' EXIT
  else
    trap 'rc=$?; rm -rf "${TMP_DIR}" >/dev/null 2>&1 || true; exit $rc' EXIT
  fi

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

  # Try persistent/batch runner to avoid reloading model for each pair
  PERSIST_SCRIPT="/workspace/project/scripts/_rife_persistent_local.py"
  if [ -f "$PERSIST_SCRIPT" ]; then
    log "Attempting persistent RIFE runner: $PERSIST_SCRIPT"
    python3 "$PERSIST_SCRIPT" --repo-dir "$REPO_DIR" --input "$TMP_DIR/input" --output "$TMP_DIR/output" --factor "$FACTOR" 2>&1 | tee -a "$TMP_DIR/rife.log"
    PERR=${PIPESTATUS[0]:-0}
    # Validate that persistent runner produced output files (non-empty PNGs)
    OUT_COUNT=$(find "$TMP_DIR/output" -maxdepth 1 -type f -name '*.png' -size +0c 2>/dev/null | wc -l)
    if [ $PERR -eq 0 ] && [ "$OUT_COUNT" -gt 0 ]; then
      log "Persistent runner completed successfully and produced $OUT_COUNT output frames — skipping per-pair fallback"
      RC=0
      PERSISTED=1
    else
      if [ $PERR -eq 2 ]; then
        log "Persistent runner not supported for this RIFE fork (exit 2) — falling back to per-pair calls"
      else
        log "Persistent runner exit code: $PERR, output frames: $OUT_COUNT — falling back to per-pair method"
        # print tail of rife.log for debugging if present
        if [ -f "$TMP_DIR/rife.log" ]; then
          log "--- persistent rife.log (last 200 lines) ---"
          tail -n 200 "$TMP_DIR/rife.log" || true
          log "--- end persistent rife.log ---"
        fi
      fi
      PERSISTED=0
      # if the persistent run created some garbage files, remove them to ensure clean per-pair run
      rm -f "$TMP_DIR/output"/*.png >/dev/null 2>&1 || true
    fi
  else
    PERSISTED=0
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
  ffmpeg -v warning -i "$INPUT_VIDEO_PATH" -vn -acodec copy "$TMP_DIR/audio.aac" >/dev/null 2>&1
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

  # Ensure required RIFE model files exist (e.g., flownet.pkl)
  log "Checking for required RIFE model files in $REPO_DIR/train_log..."
  if ! ls "$REPO_DIR/train_log"/flownet*.pkl >/dev/null 2>&1 && ! ls "$REPO_DIR/train_log"/*flownet*.pkl >/dev/null 2>&1; then
    log "flownet model not found in $REPO_DIR/train_log."
    # Try environment-provided model dir first
    if [ -n "${RIFE_MODEL_DIR:-}" ] && [ -d "$RIFE_MODEL_DIR" ] && ls "$RIFE_MODEL_DIR"/flownet*.pkl >/dev/null 2>&1; then
      log "Copying RIFE models from RIFE_MODEL_DIR=$RIFE_MODEL_DIR -> $REPO_DIR/train_log"
      mkdir -p "$REPO_DIR/train_log"
      cp -r "$RIFE_MODEL_DIR"/* "$REPO_DIR/train_log/" || true
      if ls "$REPO_DIR/train_log"/flownet*.pkl >/dev/null 2>&1 || ls "$REPO_DIR/train_log"/*flownet*.pkl >/dev/null 2>&1; then
        log "Copied flownet model files into $REPO_DIR/train_log"
      else
        log "ERROR: Copy from RIFE_MODEL_DIR failed or files missing after copy"
        [ "${KEEP_TMP:-0}" = "1" ] || rm -rf "$TMP_DIR"
        exit 3
      fi
    elif [ -d "/opt/rife_models/train_log" ] && ls "/opt/rife_models/train_log"/flownet*.pkl >/dev/null 2>&1; then
      log "Copying RIFE models from /opt/rife_models/train_log -> $REPO_DIR/train_log"
      mkdir -p "$REPO_DIR/train_log"
      cp -r /opt/rife_models/train_log/* "$REPO_DIR/train_log/" || true
      if ls "$REPO_DIR/train_log"/flownet*.pkl >/dev/null 2>&1 || ls "$REPO_DIR/train_log"/*flownet*.pkl >/dev/null 2>&1; then
        log "Copied flownet model files into $REPO_DIR/train_log"
      else
        log "ERROR: Copy from /opt/rife_models failed or files missing after copy"
        [ "${KEEP_TMP:-0}" = "1" ] || rm -rf "$TMP_DIR"
        exit 3
      fi
    else
      log "ERROR: No RIFE models found (looked in $REPO_DIR/train_log, /opt/rife_models/train_log, and RIFE_MODEL_DIR=${RIFE_MODEL_DIR:-<unset>})"
      log "RIFE requires model files (e.g., flownet.pkl) placed in $REPO_DIR/train_log"
      [ "${KEEP_TMP:-0}" = "1" ] || rm -rf "$TMP_DIR"
      exit 3
    fi
  else
    log "Found flownet model files in $REPO_DIR/train_log"
  fi

  # Ensure repo contains 'model' package (otherwise imports like model.RIFE_HD fail)
  if [ ! -d "$REPO_DIR/model" ]; then
    log "ERROR: RIFE code folder 'model' not found in $REPO_DIR (needed for imports like model.RIFE_HD)."
    log "Make sure you have a complete RIFE repo at $REPO_DIR (clone the correct fork) and that the 'model' directory exists."
    rm -rf "$TMP_DIR"
    exit 3
  fi

  # Test which interpolation method works
  log "Testing interpolation methods..."
  echo ""

  # Attempt to run known RIFE entrypoints in order of preference. These are best-effort
  # invocations because different RIFE forks may expose different CLI arguments.
  RC=2
  if [ "$PERSISTED" = "1" ]; then
    log "Persistent mode already processed frames — skipping per-pair inference steps"
    RC=0
  elif [ -f "/workspace/project/rife_interpolate_direct.py" ]; then
     log "Found /workspace/project/rife_interpolate_direct.py — attempting direct interpolation"
     python3 "/workspace/project/rife_interpolate_direct.py" "$TMP_DIR/input" "$TMP_DIR/output" "$FACTOR" 2>&1 | tee "$TMP_DIR/rife.log"
     RC=${PIPESTATUS[0]:-0}
  elif [ -f "$REPO_DIR/inference_img.py" ]; then
    log "Found $REPO_DIR/inference_img.py — attempting frame-by-frame inference"
    # inference_img.py expects two image paths: --img <imgA> <imgB>
    # We'll call it for each consecutive frame pair and run it from the output directory
    log "Running inference_img.py on each adjacent frame pair (this may take some time)"
    mkdir -p "$TMP_DIR/output"
    # collect sorted frames
    mapfile -t FRAMES < <(ls -1 "$TMP_DIR/input"/*.png 2>/dev/null | sort)
    # Make a stable copy of the inference script into the temp dir so it can't disappear mid-run
    COPY_INFERENCE="$TMP_DIR/inference_img.py"
    if [ -f "$REPO_DIR/inference_img.py" ]; then
      cp -p "$REPO_DIR/inference_img.py" "$COPY_INFERENCE" 2>/dev/null || true
      if [ ! -f "$COPY_INFERENCE" ]; then
        log "ERROR: Failed to copy $REPO_DIR/inference_img.py -> $COPY_INFERENCE"
        RC=2
      else
        log "Using copied inference script: $COPY_INFERENCE"
      fi
    else
      log "ERROR: $REPO_DIR/inference_img.py not found when attempting to copy into temp dir"
      RC=2
    fi

    if [ ${#FRAMES[@]} -lt 2 ]; then
      log "ERROR: Not enough frames for frame-pair inference (${#FRAMES[@]} found)"
      RC=5
    else
      RC=0
      # start output sequence counter
      OUT_SEQ=1
      # ensure output dir empty for predictable diffs
      rm -f "$TMP_DIR/output"/*.png >/dev/null 2>&1 || true
      for idx in "${!FRAMES[@]}"; do
        if [ "$idx" -ge $((${#FRAMES[@]} - 1)) ]; then
          break
        fi
        A=${FRAMES[$idx]}
        B=${FRAMES[$((idx+1))]}
        log "Processing pair: $(basename "$A") + $(basename "$B")"

        # Basic sanity checks: files exist and non-empty
        if [ ! -f "$A" ] || [ ! -s "$A" ]; then
          log "ERROR: Frame missing or empty: $A"
          RC=6
          break
        fi
        if [ ! -f "$B" ] || [ ! -s "$B" ]; then
          log "ERROR: Frame missing or empty: $B"
          RC=6
          break
        fi

        # Snapshot existing outputs in both repo and tmp output (to detect new files)
        pre_repo=$(ls -1 "$REPO_DIR"/*.png 2>/dev/null || true)
        pre_out=$(ls -1 "$TMP_DIR/output"/*.png 2>/dev/null || true)

        # Ensure the copied inference script exists and run it (execute from REPO_DIR so imports work)
        if [ ! -f "$COPY_INFERENCE" ]; then
          log "ERROR: Copied inference script missing: $COPY_INFERENCE"
          RC=2
          break
        fi
        log "Running copied inference script in-process with REPO_DIR as CWD and on PYTHONPATH"
        python3 -u -c "import sys,os,runpy; os.chdir('$REPO_DIR'); sys.path.insert(0,'$REPO_DIR'); sys.argv=['inference_img.py','--img','$A','$B','--exp','1','--ratio','$FACTOR']; runpy.run_path('$COPY_INFERENCE', run_name='__main__')" 2>&1 | tee -a "$TMP_DIR/rife.log"
        RC_CUR=${PIPESTATUS[0]:-0}
        if [ $RC_CUR -ne 0 ]; then
          log "ERROR: inference_img.py failed for pair $(basename "$A")/$(basename "$B") (exit $RC_CUR)"
          RC=$RC_CUR
          break
        fi

        # Find newly created files in repo and tmp output
        post_repo=$(ls -1 "$REPO_DIR"/*.png 2>/dev/null || true)
        post_out=$(ls -1 "$TMP_DIR/output"/*.png 2>/dev/null || true)
        new_files=""
        # files new in repo
        for f in $post_repo; do
          case " $pre_repo " in
            *" $f "*) ;;
            *) new_files="$new_files $f";;
          esac
        done
        # files new in tmp output
        for f in $post_out; do
          case " $pre_out " in
            *" $f "*) ;;
            *) new_files="$new_files $f";;
          esac
        done

        if [ -z "$new_files" ]; then
          log "ERROR: inference_img.py did not produce any new output files for pair $(basename "$A")/$(basename "$B")"
          RC=7
          break
        fi

        # Move/rename each new file into sequential frame_%06d_out.png names
        for nf in $new_files; do
          # If file found in repo and not already in tmp output, copy it
          if [ -f "$nf" ]; then
            target="$TMP_DIR/output/frame_$(printf "%06d" $OUT_SEQ)_out.png"
            mv "$nf" "$target" 2>/dev/null || cp "$nf" "$target" 2>/dev/null || true
            log "Saved interpolated frame: $(basename "$target")"
            OUT_SEQ=$((OUT_SEQ + 1))
          fi
        done
      done
    fi
  elif [ -f "$REPO_DIR/inference_video.py" ]; then
    log "Found $REPO_DIR/inference_video.py — attempting video inference (may require scikit-video)"
    (cd "$REPO_DIR" && python3 -u inference_video.py -i "$INPUT_VIDEO_PATH" -o "$OUTPUT_VIDEO_PATH" -f "$FACTOR" 2>&1) | tee "$TMP_DIR/rife.log"
    RC=${PIPESTATUS[0]:-0}
  else
    # No standard entrypoint matched yet. Try heuristic discovery of other candidate scripts
    log "No standard RIFE entrypoint matched; searching for additional candidate scripts (heuristic)"
    echo "--- Candidate python files in $REPO_DIR ---" >> "$TMP_DIR/rife.log" 2>/dev/null || true
    ls -1 "$REPO_DIR"/*.py 2>/dev/null | tee -a "$TMP_DIR/rife.log" || true

    mapfile -t FRAMES < <(ls -1 "$TMP_DIR/input"/*.png 2>/dev/null | sort)
    if [ ${#FRAMES[@]} -lt 2 ]; then
      log "Not enough frames to run candidate tests (${#FRAMES[@]} found)"
      RC=2
    else
      RC=2
      A=${FRAMES[0]}
      B=${FRAMES[1]}
      # Candidate filename patterns
      patterns=("*inference*.py" "*interp*.py" "*interpolate*.py" "*rife*.py" "*_rife_*.py")
      for pat in "${patterns[@]}"; do
        for cand in $REPO_DIR/$pat; do
          [ -f "$cand" ] || continue
          log "Attempting candidate script: $cand"
          echo "---- HEAD of $cand ----" >> "$TMP_DIR/rife.log" 2>/dev/null || true
          head -n 60 "$cand" >> "$TMP_DIR/rife.log" 2>/dev/null || true
          COPY_CAND="$TMP_DIR/$(basename "$cand")"
          cp -p "$cand" "$COPY_CAND" 2>/dev/null || cp "$cand" "$COPY_CAND" 2>/dev/null || true
          rm -f "$TMP_DIR/output"/*.png 2>/dev/null || true
          log "Running candidate $COPY_CAND on a single pair to test compatibility"
          python3 -u -c "import sys,os,runpy; os.chdir('$REPO_DIR'); sys.path.insert(0,'$REPO_DIR'); sys.argv=['$(basename "$COPY_CAND")','--img','$A','$B','--ratio','$FACTOR']; runpy.run_path('$COPY_CAND', run_name='__main__')" 2>&1 | tee -a "$TMP_DIR/rife.log"
          RC_C=${PIPESTATUS[0]:-0}
          OUT_COUNT=$(find "$TMP_DIR/output" -maxdepth 1 -type f -name '*.png' -size +0c 2>/dev/null | wc -l)
          if [ $RC_C -eq 0 ] && [ "$OUT_COUNT" -gt 0 ]; then
            log "Candidate $cand successfully produced $OUT_COUNT output files — adopting it for full run"
            RC=0
            break 2
          else
            log "Candidate $cand failed (exit $RC_C, outputs: $OUT_COUNT) — continuing search"
          fi
        done
      done
      if [ $RC -ne 0 ]; then
        log "No additional candidate scripts succeeded"
      fi
    fi
  fi

  if [ $RC -ne 0 ]; then
    log "ERROR: RIFE interpolation step failed (exit code: $RC)."
    # Print helper diagnostics: list recent temp dirs and show rife.log/contents
    echo "--- DEBUG: Listing temp directories matching /tmp/rife_tmp.* ---"
    ls -ld /tmp/rife_tmp.* 2>/dev/null || true

    # If TMP_DIR is set, prefer it; otherwise try to find the most recent temp dir
    if [ -n "${TMP_DIR:-}" ] && [ -d "$TMP_DIR" ]; then
      LATEST_TMP="$TMP_DIR"
    else
      LATEST_TMP=$(ls -1dt /tmp/rife_tmp.* 2>/dev/null | head -n1 || true)
    fi

    if [ -n "$LATEST_TMP" ] && [ -d "$LATEST_TMP" ]; then
      echo "--- DEBUG: Showing tail of $LATEST_TMP/rife.log (last 400 lines) ---"
      tail -n 400 "$LATEST_TMP/rife.log" 2>/dev/null || echo "(no rife.log in $LATEST_TMP)"
      echo "--- DEBUG: Listing contents of $LATEST_TMP ---"
      ls -la "$LATEST_TMP" 2>/dev/null || true
    else
      echo "--- DEBUG: No temp dir found at /tmp/rife_tmp.* ---"
    fi

    # If a rife.log exists in the (current) TMP_DIR, also print a helpful tail for debugging (legacy behavior)
    if [ -n "${TMP_DIR:-}" ] && [ -f "$TMP_DIR/rife.log" ]; then
      log "----- BEGIN RIFE LOG ($TMP_DIR/rife.log) (last 500 lines) -----"
      tail -n 500 "$TMP_DIR/rife.log" || true
      log "-----  END RIFE LOG -----"
    fi

    # Cleanup (respect KEEP_TMP for debugging)
    [ "${KEEP_TMP:-0}" = "1" ] || rm -rf "${TMP_DIR:-}" 2>/dev/null || true
    exit $RC
  fi

  # Find output frames produced by RIFE. Try several common filename patterns.
  OUT_PATTERN=""
  if ls "$TMP_DIR/output"/*_out.png >/dev/null 2>&1; then
    # RIFE variants sometimes emit frame_000001_out.png
    OUT_PATTERN="frame_%06d_out.png"
  elif ls "$TMP_DIR/output"/frame_*.png >/dev/null 2>&1; then
    OUT_PATTERN="frame_%06d.png"
  elif ls "$TMP_DIR/output"/*.png >/dev/null 2>&1; then
    # fallback: pick any png and let ffmpeg glob it (requires numeric sequence naming)
    OUT_PATTERN="frame_%06d.png"
  else
    log "ERROR: No output frames found in $TMP_DIR/output after RIFE run"
    rm -rf "$TMP_DIR"
    exit 5
  fi

  # To make ffmpeg assembly robust, create a sequentially numbered set in assembled/
  ASSEMBLE_DIR="$TMP_DIR/assembled"
  mkdir -p "$ASSEMBLE_DIR"
  IDX=1
  # Use a stable sort (version sort) if available, otherwise plain sort
  if ls "$TMP_DIR/output"/*.png >/dev/null 2>&1; then
    # generate list of files in natural order
    FILE_LIST=$(ls -1v "$TMP_DIR/output"/*.png 2>/dev/null || true)
    if [ -z "$FILE_LIST" ]; then
      FILE_LIST=$(printf "%s\n" "$TMP_DIR/output"/*.png | sort -V 2>/dev/null || true)
    fi
    for f in $FILE_LIST; do
      if [ -f "$f" ] && [ -s "$f" ]; then
        cp -f "$f" "$ASSEMBLE_DIR/frame_$(printf "%06d" $IDX).png" || cp -f "$f" "$ASSEMBLE_DIR/frame_$(printf "%06d" $IDX).png" 2>/dev/null || true
        IDX=$((IDX+1))
      fi
    done
  fi
  ASSEMBLED_COUNT=$(ls -1 "$ASSEMBLE_DIR"/*.png 2>/dev/null | wc -l)
  if [ $ASSEMBLED_COUNT -eq 0 ]; then
    log "ERROR: No valid assembled frames found in $ASSEMBLE_DIR — cannot reassemble video"
    [ "${KEEP_TMP:-0}" = "1" ] || rm -rf "$TMP_DIR"
    exit 5
  fi
  # We'll use assembled/frame_%06d.png for ffmpeg
  ASSEMBLED_PATTERN="frame_%06d.png"

  # Reassemble into final video using assembled set
  log "Reassembling interpolated frames into video (FPS: ${TARGET_FPS}) using $ASSEMBLE_DIR"
  if [ -f "$TMP_DIR/audio.aac" ]; then
    ffmpeg -y -v warning -stats -framerate "$TARGET_FPS" -start_number 1 -i "$ASSEMBLE_DIR/$ASSEMBLED_PATTERN" -i "$TMP_DIR/audio.aac" -c:v libx264 -crf 18 -pix_fmt yuv420p -c:a aac -shortest "$OUTPUT_VIDEO_PATH"
  else
    ffmpeg -y -v warning -stats -framerate "$TARGET_FPS" -start_number 1 -i "$ASSEMBLE_DIR/$ASSEMBLED_PATTERN" -c:v libx264 -crf 18 -pix_fmt yuv420p "$OUTPUT_VIDEO_PATH"
  fi
  FFMPEG_RC=$?

  # If ffmpeg failed with assembled set, try glob fallback directly on output (edge cases)
  if [ $FFMPEG_RC -ne 0 ]; then
    log "ffmpeg failed with $FFMPEG_RC on assembled set; attempting glob-based reassembly as fallback"
    if [ -f "$TMP_DIR/audio.aac" ]; then
      ffmpeg -y -v warning -stats -framerate "$TARGET_FPS" -pattern_type glob -i "$TMP_DIR/output/*.png" -i "$TMP_DIR/audio.aac" -c:v libx264 -crf 18 -pix_fmt yuv420p -c:a aac -shortest "$OUTPUT_VIDEO_PATH"
    else
      ffmpeg -y -v warning -stats -framerate "$TARGET_FPS" -pattern_type glob -i "$TMP_DIR/output/*.png" -c:v libx264 -crf 18 -pix_fmt yuv420p "$OUTPUT_VIDEO_PATH"
    fi
    FFMPEG_RC=$?
  fi

  if [ $FFMPEG_RC -ne 0 ]; then
    log "ERROR: Failed to reassemble video from frames (ffmpeg exit: $FFMPEG_RC)"
    rm -rf "$TMP_DIR"
    exit $FFMPEG_RC
  fi

  # Success - cleanup and exit 0
  log "✅ RIFE interpolation completed successfully — output: $OUTPUT_VIDEO_PATH"
  rm -rf "$TMP_DIR"
  exit 0

fi

# If we reach here it means the fast frame-by-frame branch was not available.
log "No supported RIFE frame-by-frame method detected — exiting with code 2 to allow fallback."
exit 2
