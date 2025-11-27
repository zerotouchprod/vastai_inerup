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
EXTRA_ARGS=("$@")
LOGFILE="/tmp/realesrgan_batch_safe_$(date +%s).log"

# Run once and capture logs
echo "Running batch script (first attempt). Log: $LOGFILE"
# Ensure TORCH_COMPILE_DISABLE is exported; child processes inherit it
: ${TORCH_COMPILE_DISABLE:=1}

# If user didn't specify --batch-size, attempt a very quick GPU probe to estimate a safe batch for given tile size
HAS_BATCH=0
TILE_SIZE=256
for ((i=0;i<${#EXTRA_ARGS[@]};i++)); do
  a="${EXTRA_ARGS[$i]}"
  if [ "$a" = "--batch-size" ] || [ "$a" = "-b" ]; then
    HAS_BATCH=1
  fi
  if [ "$a" = "--tile-size" ]; then
    # next arg is tile size
    nextidx=$((i+1))
    if [ $nextidx -lt ${#EXTRA_ARGS[@]} ]; then
      TILE_SIZE="${EXTRA_ARGS[$nextidx]}"
    fi
  fi
done

if [ "$HAS_BATCH" -eq 0 ]; then
  echo "No explicit --batch-size provided; running fast GPU probe for tile_size=$TILE_SIZE to estimate safe batch..."
  # If SKIP_PROBE=1, only compute an estimate from VRAM (no allocations/tests)
  if [ "${SKIP_PROBE:-0}" = "1" ]; then
    SUGGEST_BATCH=$(python3 - "$TILE_SIZE" <<'PY'
import sys,os
try:
    import torch
    tile=int(sys.argv[1])
    bytes_per_sample = tile * tile * 3 * 2
    # Determine safety factor: prefer explicit env, otherwise autotune by total VRAM
    pf = os.environ.get('PROBE_SAFE_FACTOR')
    prop_safe = None
    try:
        prop = torch.cuda.get_device_properties(0)
        total_bytes = prop.total_memory
    except Exception:
        total_bytes = None
    if pf is not None:
        try:
            prop_safe = float(pf)
        except Exception:
            prop_safe = None
    if prop_safe is None:
        # autotune safety factor by total VRAM (conservative defaults)
        if total_bytes is None:
            prop_safe = 4.0
        else:
            gb = total_bytes / (1024**3)
            if gb < 10:
                prop_safe = 10.0
            elif gb < 16:
                prop_safe = 8.0
            elif gb < 24:
                prop_safe = 5.0
            else:
                prop_safe = 3.0
    # prefer free memory if available
    free_bytes = None
    try:
        free_bytes = torch.cuda.mem_get_info(0)[0]
    except Exception:
        free_bytes = None
    use_bytes = free_bytes if (free_bytes is not None and free_bytes>0) else total_bytes
    if use_bytes is None:
        est = 1
    else:
        est = int(use_bytes / (bytes_per_sample * prop_safe))
    if est < 1:
        est = 1
    est = min(est, 512)
    print(est)
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
    bytes_per_sample = tile * tile * 3 * 2
    # Determine safety factor: prefer explicit env, otherwise autotune by total VRAM
    pf = os.environ.get('PROBE_SAFE_FACTOR')
    prop_safe = None
    try:
        prop = torch.cuda.get_device_properties(0)
        total_bytes = prop.total_memory
    except Exception:
        total_bytes = None
    if pf is not None:
        try:
            prop_safe = float(pf)
        except Exception:
            prop_safe = None
    if prop_safe is None:
        if total_bytes is None:
            prop_safe = 4.0
        else:
            gb = total_bytes / (1024**3)
            if gb < 10:
                prop_safe = 10.0
            elif gb < 16:
                prop_safe = 8.0
            elif gb < 24:
                prop_safe = 5.0
            else:
                prop_safe = 3.0
    # prefer free memory for testing
    try:
        free_bytes = torch.cuda.mem_get_info(0)[0]
    except Exception:
        free_bytes = None
    use_bytes = free_bytes if (free_bytes is not None and free_bytes>0) else total_bytes
    if use_bytes is None:
        est = 1
    else:
        est = int(use_bytes / (bytes_per_sample * prop_safe))
    if est < 1:
        est = 1
    est = min(est, 512)
    dtype = torch.float16
    torch.cuda.empty_cache()
    candidate = est
    success = 1
    for _ in range(6):
        try:
            t = torch.empty((candidate,3,tile,tile), device='cuda', dtype=dtype)
            del t
            torch.cuda.empty_cache()
            print(candidate)
            success = 1
            break
        except Exception:
            success = 0
            candidate = max(1, candidate // 2)
            continue
    if not success:
        print(1)
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

# Run the batch script and capture all output
python3 "$BATCH_PY" "$IN_DIR" "$OUT_DIR" "${EXTRA_ARGS[@]}" > "$LOGFILE" 2>&1 || true

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
          # next arg preserved
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
