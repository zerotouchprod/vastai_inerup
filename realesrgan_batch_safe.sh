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

# allow overriding maximum sensible batch via env (default 64)
export MAX_BATCH=${MAX_BATCH:-32}

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
    use_bytes = free if (free is not None and free>0) :
