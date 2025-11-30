#!/usr/bin/env bash
# Safe runner for realesrgan_batch_upscale.py
# Usage: realesrgan_batch_safe.sh <input_dir> <output_dir> [batch_args...]
set -u
BATCH_PY="/workspace/project/realesrgan_batch_upscale.py"
if [ ! -f "$BATCH_PY" ]; then
  echo "ERROR: batch script not found: $BATCH_PY" >&2
  exit 2
fi
IN_DIR=${1:-}
OUT_DIR=${2:-}
shift 2 || true
# Keep the original caller args as a single string for robust detection of explicit --batch-size
CALLER_ARGS_STR="$*"
EXTRA_ARGS=("$@")
# If caller passed a single space-separated string (e.g. unquoted), split it into array elements for robust parsing
if [ ${#EXTRA_ARGS[@]} -eq 1 ]; then
  single="${EXTRA_ARGS[0]}"
  # if the single element contains a space, split it
  if echo "$single" | grep -q ' '; then
    # shell-safe split into array
    read -r -a EXTRA_ARGS <<< "$single"
  fi
fi
LOGFILE="/tmp/realesrgan_batch_safe_$(date +%s).log"

# Determine if caller provided explicit batch-size and capture tile-size from EXTRA_ARGS
TILE_SIZE=256
HAS_BATCH_ARG=0
for ((i=0;i<${#EXTRA_ARGS[@]};i++)); do
  a="${EXTRA_ARGS[$i]}"
  case "$a" in
    --batch-size|--batch-size=*|-b)
      HAS_BATCH_ARG=1
      ;;
    --tile-size)
      nextidx=$((i+1))
      if [ $nextidx -lt ${#EXTRA_ARGS[@]} ]; then
        TILE_SIZE="${EXTRA_ARGS[$nextidx]}"
      fi
      ;;
  esac
done

# Final determination: caller explicitly requested batch-size if it appears in the original caller string or in parsed args
HAS_BATCH=0
if [ $HAS_BATCH_ARG -eq 1 ] || echo "$CALLER_ARGS_STR" | grep -q -- --batch-size 2>/dev/null; then
  HAS_BATCH=1
fi

# allow overriding maximum sensible batch via env (default 64)
export MAX_BATCH=${MAX_BATCH:-32}

# Run once and capture logs
echo "Running batch script (first attempt). Log: $LOGFILE"
# Ensure TORCH_COMPILE_DISABLE is exported; child processes inherit it
: ${TORCH_COMPILE_DISABLE:=1}

# --- NOTE ---
# Previously the script re-initialized HAS_BATCH and TILE_SIZE here which could override
# the earlier detection (from CALLER_ARGS_STR / EXTRA_ARGS). That caused explicit
# caller-provided --batch-size flags to be ignored and the command to default to --batch-size 1.
# We removed that duplicate re-detection so the previously computed HAS_BATCH/TILE_SIZE are used.

# If user didn't specify --batch-size, attempt a very quick GPU probe to estimate a safe batch for given tile size
if [ "$HAS_BATCH" -eq 0 ]; then
  echo "No explicit --batch-size provided; running fast GPU probe for tile_size=$TILE_SIZE to estimate safe batch..."
  # If SKIP_PROBE=1, only compute an estimate from VRAM (no allocations/tests)
  if [ "${SKIP_PROBE:-0}" = "1" ]; then
    SUGGEST_BATCH=$(python3 - "$TILE_SIZE" <<'PY'
import sys,os
try:
    import torch
    tile=int(sys.argv[1])
    # Prefer free memory if available, otherwise use total
    try:
        free = torch.cuda.mem_get_info(0)[0]
    except Exception:
        free = None
    try:
        total = torch.cuda.get_device_properties(0).total_memory
    except Exception:
        total = None
    use_bytes = free if (free is not None and free>0) else total
    vram_gb = (use_bytes or 0) / (1024.0**3)
    # table mapping (tile -> vram ranges -> suggested batch)
    def map_batch(tile, gb):
        if tile >= 512:
            # For large tiles prefer small batches; allow batch=2 for 12-24GB
            if gb < 8: return 1
            if gb < 12: return 1
            if gb < 24: return 2
            return 4
        if tile >= 256:
            if gb < 8: return 1
            if gb < 12: return 2
            if gb < 16: return 3
            if gb < 24: return 4
            return 8
        # tile < 256 -> treat as 128
        if gb < 8: return 2
        if gb < 12: return 4
        if gb < 16: return 8
        if gb < 24: return 12
        return 16
    suggested = map_batch(tile, vram_gb)
    # apply MAX_BATCH clamp
    try:
        max_batch_env = int(os.environ.get('MAX_BATCH','32'))
    except Exception:
        max_batch_env = 32
    suggested = min(suggested, max_batch_env)
    if suggested < 1:
        suggested = 1
    print(suggested)
except Exception:
    print(1)
PY
)
    echo "VRAM-only mode: suggested batch_size=$SUGGEST_BATCH"
    EXTRA_ARGS=("--batch-size" "$SUGGEST_BATCH" "${EXTRA_ARGS[@]}")
  else
    SUGGEST_BATCH=$(python3 - "$TILE_SIZE" <<'PY'
import sys,os
try:
    import torch
    tile=int(sys.argv[1])
    # Prefer free memory if available, otherwise use total
    try:
        free = torch.cuda.mem_get_info(0)[0]
    except Exception:
        free = None
    try:
        total = torch.cuda.get_device_properties(0).total_memory
    except Exception:
        total = None
    use_bytes = free if (free is not None and free>0) else total
    vram_gb = (use_bytes or 0) / (1024.0**3)
    # deterministic table mapping
    def map_batch(tile, gb):
        if tile >= 512:
            # For large tiles prefer small batches; allow batch=2 for 12-24GB
            if gb < 8: return 1
            if gb < 12: return 1
            if gb < 24: return 2
            return 4
        if tile >= 256:
            if gb < 8: return 1
            if gb < 12: return 2
            if gb < 16: return 3
            if gb < 24: return 4
            return 8
        # tile < 256 -> treat as 128
        if gb < 8: return 2
        if gb < 12: return 4
        if gb < 16: return 8
        if gb < 24: return 12
        return 16
    suggested = map_batch(tile, vram_gb)
    # clamp by MAX_BATCH
    try:
        max_batch_env = int(os.environ.get('MAX_BATCH','32'))
    except Exception:
        max_batch_env = 32
    suggested = min(suggested, max_batch_env)
    if suggested < 1:
        suggested = 1
    # quick empirical test: try allocating FP16 tensor at suggested batch; if OOM, halve until success
    dtype = torch.float16
    torch.cuda.empty_cache()
    candidate = suggested
    success = False
    for _ in range(6):
        try:
            t = torch.empty((candidate,3,tile,tile), device='cuda', dtype=dtype)
            del t
            torch.cuda.empty_cache()
            success = True
            break
        except Exception:
            candidate = max(1, candidate // 2)
            continue
    if not success:
        candidate = 1
    print(candidate)
except Exception:
    print(1)
PY
)
    if [ -n "$SUGGEST_BATCH" ]; then
      echo "Probe suggests batch_size=$SUGGEST_BATCH";
      EXTRA_ARGS=("--batch-size" "$SUGGEST_BATCH" "${EXTRA_ARGS[@]}")
    fi
  fi
fi

# If we did not receive an explicit --batch-size from the caller, sanitize EXTRA_ARGS and reinsert probe suggestion
if [ "$HAS_BATCH" -eq 0 ]; then
  # Sanitize EXTRA_ARGS: remove any explicit --batch-size or -b flags so our suggested/default will be enforced
  CLEAN_EXTRA=()
  skip_next=0
  for a in "${EXTRA_ARGS[@]}"; do
    if [ "$skip_next" -eq 1 ]; then
      skip_next=0
      continue
    fi
    case "$a" in
      --batch-size=*)
        # skip explicit key=value form
        continue
        ;;
      --batch-size|-b)
        # skip this flag and its value
        skip_next=1
        continue
        ;;
      *)
        CLEAN_EXTRA+=("$a")
        ;;
    esac
  done
  EXTRA_ARGS=("${CLEAN_EXTRA[@]}")

  # Reinsert suggested batch if probe produced one and no explicit --batch-size remains
  if [ -n "${SUGGEST_BATCH:-}" ]; then
    has_bs=0
    for a in "${EXTRA_ARGS[@]}"; do
      if [ "$a" = "--batch-size" ] || [ "$a" = "-b" ] || echo "$a" | grep -q -- '--batch-size=' 2>/dev/null; then
        has_bs=1
        break
      fi
    done
    if [ $has_bs -eq 0 ]; then
      EXTRA_ARGS=("--batch-size" "$SUGGEST_BATCH" "${EXTRA_ARGS[@]}")
      printf 'Applied suggested batch_size: %s\n' "${SUGGEST_BATCH}" >> "$LOGFILE"
    fi
  fi

  # Log sanitized args
  printf 'Sanitized EXTRA_ARGS: %s\n' "${EXTRA_ARGS[*]}" >> "$LOGFILE"
  # Log MAX_BATCH as well
  printf 'MAX_BATCH: %s\n' "${MAX_BATCH}" >> "$LOGFILE"
fi

# --- Progress watcher (background) ---
# Configurable interval (seconds)
: ${PROGRESS_INTERVAL:=10}
# Count input frames (if IN_DIR exists)
INPUT_COUNT=0
if [ -d "$IN_DIR" ]; then
  INPUT_COUNT=$(find "$IN_DIR" -maxdepth 1 -type f \( -iname '*.png' -o -iname '*.jpg' -o -iname '*.jpeg' \) | wc -l || true)
fi

start_progress_watcher() {
  local outdir="$1"; local logfile="$2"; local interval="$3"; local total="$4"
  # ensure outdir exists (may be created by batch script)
  local waited=0
  # wait up to 60s for outdir to appear
  while [ ! -d "$outdir" ] && [ $waited -lt 120 ]; do
    sleep 0.5; waited=$((waited+1))
  done
  START_TS=$(date +%s)
  LAST_COUNT=0
  # log watcher start
  echo "Starting progress watcher (interval ${interval}s) for $outdir (total frames: $total)" | tee -a "$logfile"
  while true; do
    CURR_COUNT=0
    if [ -d "$outdir" ]; then
      CURR_COUNT=$(find "$outdir" -maxdepth 1 -type f \( -iname '*.png' -o -iname '*.jpg' -o -iname '*.jpeg' \) | wc -l || true)
    fi
    NOW_TS=$(date +%s)
    ELAPSED=$((NOW_TS - START_TS))
    if [ "$ELAPSED" -le 0 ]; then ELAPSED=1; fi
    # average FPS since start
    if [ "$CURR_COUNT" -gt 0 ]; then
      AVG_FPS=$(awk "BEGIN{printf \"%.2f\", $CURR_COUNT/$ELAPSED}")
    else
      AVG_FPS="0.00"
    fi
    # instantaneous FPS over the last interval
    DELTA=$((CURR_COUNT - LAST_COUNT))
    if [ $DELTA -lt 0 ]; then DELTA=0; fi
    if [ "$interval" -gt 0 ]; then
      INST_FPS=$(awk "BEGIN{printf \"%.2f\", $DELTA/$interval}")
    else
      INST_FPS="0.00"
    fi
    REMAINING=0
    ETA_STR="?s"
    if [ "$total" -gt 0 ]; then
      REMAINING=$((total - CURR_COUNT))
      if [ "$CURR_COUNT" -gt 0 ] && [ "$ELAPSED" -gt 0 ]; then
        ETA_SEC=$(awk "BEGIN{printf \"%.0f\", $REMAINING / ($AVG_FPS+0) }")
        ETA_MIN=$((ETA_SEC/60))
        ETA_STR="~${ETA_MIN}m"
      fi
    fi
    PERCENT="0"
    if [ "$total" -gt 0 ]; then
      PERCENT=$(( CURR_COUNT * 100 / total )) 2>/dev/null || PERCENT=0
    fi
    TS="$(date '+%H:%M:%S')"
    MSG="[$TS] Progress: ${CURR_COUNT}/${total} frames (${PERCENT}%) | avg: ${AVG_FPS} fps | inst: ${INST_FPS} fps | ETA: ${ETA_STR}"
    echo "$MSG"
    printf '%s\n' "$MSG" >> "$logfile"
    LAST_COUNT=$CURR_COUNT
    # exit if done
    if [ "$total" -gt 0 ] && [ "$CURR_COUNT" -ge "$total" ]; then
      break
    fi
    sleep "$interval"
  done
}

# Start watcher in background; will be killed after CMD finishes
start_progress_watcher "$OUT_DIR" "$LOGFILE" "$PROGRESS_INTERVAL" "$INPUT_COUNT" &
PROGRESS_WATCHER_PID=$!

# Run the batch script and capture all output
# Build command array so quoting/arrays are preserved and we can log what we actually run
# Prefer probe-suggested batch_size if no explicit --batch-size present
HAS_BFLAG=0
for a in "${EXTRA_ARGS[@]}"; do
  case "$a" in
    --batch-size|--batch-size=*|-b)
      HAS_BFLAG=1
      break
      ;;
  esac
done
if [ $HAS_BFLAG -eq 0 ]; then
  if [ -n "${SUGGEST_BATCH:-}" ]; then
    CMD=(python3 "$BATCH_PY" "$IN_DIR" "$OUT_DIR" --batch-size "$SUGGEST_BATCH" "${EXTRA_ARGS[@]}")
  else
    CMD=(python3 "$BATCH_PY" "$IN_DIR" "$OUT_DIR" --batch-size 1 "${EXTRA_ARGS[@]}")
  fi
else
  CMD=(python3 "$BATCH_PY" "$IN_DIR" "$OUT_DIR" "${EXTRA_ARGS[@]}")
fi

# Log the exact command to the logfile for debugging
# Use printf with CMD[*] to avoid 'argument mixes string and array' shellcheck-like warnings
printf 'Running command: %s\n' "${CMD[*]}" >> "$LOGFILE"
# Also print the running command to stdout so progress is visible immediately
echo "Running command: ${CMD[*]}" | tee -a "$LOGFILE"
# Also log environment of interest
echo "ENV: TORCH_COMPILE_DISABLE=${TORCH_COMPILE_DISABLE:-}, SKIP_PROBE=${SKIP_PROBE:-}, AUTO_TUNE_BATCH=${AUTO_TUNE_BATCH:-}, PROBE_SAFE_FACTOR=${PROBE_SAFE_FACTOR:-}" >> "$LOGFILE"

# Start a live logfile monitor to surface progress lines to stdout
# Use tail -n0 -F so we only see new lines appended after this point
( tail -n0 -F "$LOGFILE" 2>/dev/null | while IFS= read -r line; do
    # filter likely progress lines to avoid flooding
    if echo "$line" | grep -qE "Processed|Processing|Processing first frame|frames|fps|Progress|%|ETA|Saving|Batched forward OOM|OOM|ERROR|WARN|Traceback|Model loaded|Dummy forward|Loading Real-ESRGAN|Attempting torch.compile|torch.compile succeeded|torch._dynamo"; then
      echo "$line"
    fi
  done
) &
LOG_MONITOR_PID=$!

# Run the batch process and append output to logfile
"${CMD[@]}" >> "$LOGFILE" 2>&1 || true

# After command completes, stop watcher if running
if ps -p $PROGRESS_WATCHER_PID > /dev/null 2>&1; then
  kill $PROGRESS_WATCHER_PID 2>/dev/null || true
fi
# stop live logfile monitor
if ps -p $LOG_MONITOR_PID > /dev/null 2>&1; then
  kill $LOG_MONITOR_PID 2>/dev/null || true
fi

# Inspect log for known problematic signatures
LOG_CONTENT=$(cat "$LOGFILE" 2>/dev/null || true)
NEEDS_RETRY=0
if echo "$LOG_CONTENT" | grep -q -i "libcuda.so cannot found"; then
  echo "Detected missing libcuda in batch log"
  NEEDS_RETRY=1
fi
if echo "$LOG_CONTENT" | grep -q -i "torch._dynamo"; then
  echo "Detected torch._dynamo / inductor messages in batch log"
  NEEDS_RETRY=1
fi
if echo "$LOG_CONTENT" | grep -q -i "Batched forward OOM"; then
  echo "Detected Batched forward OOM in batch log"
  NEEDS_RETRY=1
fi
if echo "$LOG_CONTENT" | grep -q -i "backend='inductor' raised"; then
  echo "Detected inductor backend failure in batch log"
  NEEDS_RETRY=1
fi

if [ "$NEEDS_RETRY" -eq 1 ]; then
  echo "Retrying batch script with conservative settings and TORCH_COMPILE_DISABLE=1"
  # Conservative overrides
  ALT_ARGS=("--batch-size" "1" "--tile-size" "256" "--save-workers" "1" "--use-local-temp" "--half")
  # Combine EXTRA_ARGS but strip any conflicting flags (batch-size, tile-size, save-workers, --torch-compile)
  CLEANED=()
  skip_next=0
  for a in "${EXTRA_ARGS[@]}"; do
    if [ "$skip_next" -eq 1 ]; then skip_next=0; continue; fi
    case "$a" in
      --batch-size|-b)
        skip_next=1; continue;;
      --tile-size)
        skip_next=1; continue;;
      --save-workers)
        skip_next=1; continue;;
      --torch-compile)
        # skip this flag to force disabled compile
        continue;;
      --use-local-temp|--half|--out-format|--jpeg-quality)
        CLEANED+=("$a")
        # if option expects value, preserve next
        if [ "$a" = "--out-format" ] || [ "$a" = "--jpeg-quality" ]; then
          :
        fi
        ;;
      *)
        CLEANED+=("$a")
        ;;
    esac
  done
  # Export TORCH_COMPILE_DISABLE explicitly for retry
  export TORCH_COMPILE_DISABLE=1
  # Run retry
  # Print combined args safely
  echo -n "Second run args:"
  for arg in "${CLEANED[@]}"; do printf " %s" "$arg"; done
  for arg in "${ALT_ARGS[@]}"; do printf " %s" "$arg"; done
  echo
  python3 "$BATCH_PY" "$IN_DIR" "$OUT_DIR" "${CLEANED[@]}" "${ALT_ARGS[@]}" >> "$LOGFILE" 2>&1 || true
  echo "Retry log appended to $LOGFILE"
fi

# Print tail of log for caller visibility
echo "==== Realesrgan batch safe log (tail 200) ===="
tail -n 200 "$LOGFILE" || true

# Exit with 0 if output dir has files
OUT_COUNT=$(ls -1 "$OUT_DIR"/*.{png,jpg,jpeg} 2>/dev/null | wc -l || true)
if [ "$OUT_COUNT" -gt 0 ]; then
  echo "Batch script produced $OUT_COUNT output files"
  exit 0
fi

# Otherwise return failure
echo "Batch script did not produce outputs (check $LOGFILE)" >&2
exit 1
