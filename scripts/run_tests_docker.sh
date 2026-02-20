#!/usr/bin/env bash
# run_tests_docker.sh — build lightweight test image and run full suite
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
IMAGE="vastai-gen-test:local"

echo "▶ Building test image..."
docker build \
  -f "${REPO_ROOT}/docker/Dockerfile.test" \
  -t "${IMAGE}" \
  "${REPO_ROOT}"

echo ""
echo "▶ Running tests (coverage ≥ 80% on core modules)..."
docker run --rm \
  -e HF_HUB_OFFLINE=1 \
  -e TRANSFORMERS_OFFLINE=1 \
  -e GEN_ENABLE_SAFETY_CHECKER=false \
  "${IMAGE}" \
  pytest \
    tests/unit/test_gen_models.py \
    tests/unit/test_gen_config.py \
    tests/unit/test_generation_result.py \
    tests/unit/test_domain_generation.py \
    tests/unit/test_base_engine.py \
    tests/integration/test_text2video_full.py \
    tests/integration/test_image2video_full.py \
    tests/integration/test_universal_mode.py \
    tests/integration/test_run_gen_e2e.py \
    -v --tb=short --timeout=30 \
    --cov \
    --cov-config=.coveragerc \
    --cov-report=term-missing \
    --cov-fail-under=80 \
    -m "not slow"
