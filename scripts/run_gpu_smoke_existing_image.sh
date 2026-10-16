#!/usr/bin/env bash
# Run the immutable worker smoke code inside the existing large Vast image.
# The surrounding Aividup SSH pipeline is responsible for cloning this repo,
# collecting the two JSON files, and destroying the instance.
set -euo pipefail

PROJECT_ROOT="${PROJECT_ROOT:-/workspace/project}"
PYTHON="${PYTHON:-python3}"
RESULT_PATH="${GPU_SMOKE_RESULT_PATH:-/workspace/gpu-smoke-result.json}"
DIAGNOSTIC_PATH="${GPU_SMOKE_DIAGNOSTIC_PATH:-/workspace/gpu-smoke-diagnostics.json}"

export PYTHONPATH="${PROJECT_ROOT}${PYTHONPATH:+:${PYTHONPATH}}"
export GPU_SMOKE_RESULT_PATH="$RESULT_PATH"
export GPU_SMOKE_DIAGNOSTIC_PATH="$DIAGNOSTIC_PATH"

exec "$PYTHON" "$PROJECT_ROOT/tests/gpu_smoke/run.py"
