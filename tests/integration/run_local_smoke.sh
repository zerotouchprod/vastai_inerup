#!/usr/bin/env bash
# Simple local smoke runner for run_realesrgan_pytorch.sh
# Usage: ./tests/integration/run_local_smoke.sh [path/to/input_video] [scale]
# If input omitted, will use first file under tests/video/*

set -euo pipefail

INPUT=${1:-}
SCALE=${2:-2}

# find default test video
if [ -z "$INPUT" ]; then
  first=$(ls -1 tests/video/* 2>/dev/null | head -n1 || true)
  if [ -z "$first" ]; then
    echo "No test video found in tests/video. Provide path as first argument." >&2
    exit 2
  fi
  INPUT="$first"
fi

# Output path (placed next to repo root)
OUTDIR="/tmp/realesrgan_local_smoke"
mkdir -p "$OUTDIR"
BASENAME=$(basename "$INPUT")
OUTFILE="$OUTDIR/${BASENAME%.*}_upscaled_x${SCALE}.mp4"

# Conservative defaults for local GPU testing
export AUTO_TUNE_BATCH=false   # disable long micro-sweeps
# Start with a moderately small batch; the wrapper will map VRAM->batch if --batch-size not present
export BATCH_ARGS="--use-local-temp --save-workers 4 --tile-size 512 --half --out-format png"
export PYTHONUNBUFFERED=1

echo "Local smoke test"
echo "  input: $INPUT"
echo "  scale: $SCALE"
echo "  out:   $OUTFILE"
echo "  BATCH_ARGS: $BATCH_ARGS"
echo "  AUTO_TUNE_BATCH: $AUTO_TUNE_BATCH"

echo "\n== RUNNING ==\n"
# run script (assumes run_realesrgan_pytorch.sh is executable)
bash ./run_realesrgan_pytorch.sh "$INPUT" "$OUTFILE" "$SCALE"
RC=$?

if [ $RC -eq 0 ]; then
  echo "\nSmoke finished successfully. Output: $OUTFILE"
else
  echo "\nSmoke failed (exit $RC). Check console output and /tmp/realesrgan_batch_safe_*.log or $OUTDIR for artifacts."
fi

exit $RC

