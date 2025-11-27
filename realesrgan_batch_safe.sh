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
  SUGGEST_BATCH=$(python3 - <<PY
import sys
try:
    import torch
    tile=int(sys.argv[1])
    # compute a conservative upper bound for number of tile-shaped samples that could fit in GPU RAM
    # bytes per element for float16 = 2, channels=3
    bytes_per_sample = tile * tile * 3 * 2
    prop_safe = 4.0  # conservative factor to account for activations/overhead
    # get total GPU memory in bytes
    total_bytes = None
    try:
        prop = torch.cuda.get_device_properties(0)
        total_bytes = prop.total_memory
    except Exception:
        total_bytes = None
    if total_bytes is None:
        max_try = 64
    else:
        est = int(total_bytes / (bytes_per_sample * prop_safe))
        # clamp to reasonable bounds
        if est < 1:
            max_try = 1
        else:
            max_try = min(max(est,1), 512)
    dtype=torch.float16
    torch.cuda.empty_cache()
    lo=0; hi=1
    # cap hi to max_try
    max_try_val = max_try
    while hi<=max_try_val:
        try:
            t = torch.empty((hi,3,tile,tile), device='cuda', dtype=dtype)
            del t
            torch.cuda.empty_cache()
            lo = hi
            hi = hi*2
        except Exception:
            break
    left=lo; right=min(hi, max_try_val)
    while left+1<right:
        mid=(left+right)//2
        try:
            t = torch.empty((mid,3,tile,tile), device='cuda', dtype=dtype)
            del t
            torch.cuda.empty_cache()
            left = mid
        except Exception:
            right = mid
    print(left if left>0 else 1)
except Exception:
    print(1)
PY
"$TILE_SIZE")
  if [ -n "$SUGGEST_BATCH" ]; then
    echo "Probe suggests batch_size=$SUGGEST_BATCH";
    # Prepend suggested batch into EXTRA_ARGS for the run
    EXTRA_ARGS=("--batch-size" "$SUGGEST_BATCH" "${EXTRA_ARGS[@]}")
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
