#!/bin/bash
# Run all generation module tests
# Usage: ./tests/run_generation_tests.sh

set -e

echo "========================================"
echo "Running Generation Module Tests"
echo "========================================"

# Colors
GREEN='\033[0;32m'
RED='\033[0;31m'
NC='\033[0m' # No Color

# Change to project root
cd "$(dirname "$0")/.."

# Activate virtual environment if exists
if [ -d "venv" ]; then
    source venv/bin/activate
elif [ -d ".venv" ]; then
    source .venv/bin/activate
fi

# Set PYTHONPATH
export PYTHONPATH="${PWD}:${PYTHONPATH}"

echo ""
echo "========================================="
echo "1. Unit Tests - Configuration"
echo "========================================="
pytest tests/unit/services/generation/test_config.py -v

echo ""
echo "========================================="
echo "2. Unit Tests - Models"
echo "========================================="
pytest tests/unit/services/generation/test_models.py -v

echo ""
echo "========================================="
echo "3. Unit Tests - Image Loader"
echo "========================================="
pytest tests/unit/services/generation/utils/test_image_loader.py -v

echo ""
echo "========================================="
echo "4. Integration Tests - Text2Video"
echo "========================================="
pytest tests/integration/generation/test_text2video_workflow.py -v

echo ""
echo "========================================="
echo "5. Integration Tests - Image2Video"
echo "========================================="
pytest tests/integration/generation/test_image2video_workflow.py -v

echo ""
echo "========================================="
echo "Test Summary"
echo "========================================="

# Run all tests with coverage
pytest tests/unit/services/generation/ tests/integration/generation/ \
    --cov=src/services/generation \
    --cov-report=term-missing \
    --cov-report=html:htmlcov_generation \
    -v

echo ""
echo -e "${GREEN}✅ All tests completed!${NC}"
echo ""
echo "Coverage report generated in: htmlcov_generation/index.html"
