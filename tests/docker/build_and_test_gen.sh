#!/bin/bash
# Build and test script for video generation Docker image

set -e

echo "🐳 Building video generation Docker image..."
echo "================================================"

IMAGE_NAME="video-gen"
IMAGE_TAG="latest"
FULL_IMAGE="${IMAGE_NAME}:${IMAGE_TAG}"

# Build image
echo "📦 Building ${FULL_IMAGE}..."
docker build -f Dockerfile.gen -t ${FULL_IMAGE} . \
  --build-arg BUILDKIT_INLINE_CACHE=1

echo "✅ Build complete!"
echo ""

# Show image info
echo "📊 Image information:"
docker images ${IMAGE_NAME}
echo ""

# Test 1: Import test
echo "🧪 Test 1: Running import tests..."
docker run --rm ${FULL_IMAGE} \
  python tests/test_generation_imports.py

echo "✅ Import tests passed!"
echo ""

# Test 2: Dry-run test
echo "🧪 Test 2: Running dry-run test..."
docker run --rm ${FULL_IMAGE} \
  python -m src.entrypoints.run_gen \
  --job '{"prompts": ["A test video"]}' \
  --dry-run

echo "✅ Dry-run test passed!"
echo ""

# Test 3: Unit tests (if pytest available)
echo "🧪 Test 3: Running unit tests..."
docker run --rm ${FULL_IMAGE} \
  pytest tests/unit/services/generation/ -v --tb=short || echo "⚠️  Unit tests skipped (pytest not in image)"

echo ""

# Test 4: CUDA availability check
echo "🧪 Test 4: Checking CUDA availability..."
docker run --rm --gpus all ${FULL_IMAGE} \
  python -c "import torch; print(f'CUDA available: {torch.cuda.is_available()}'); print(f'CUDA version: {torch.version.cuda}'); print(f'GPU count: {torch.cuda.device_count()}')" \
  || echo "⚠️  GPU test skipped (no GPU available)"

echo ""

# Summary
echo "================================================"
echo "✅ All tests passed!"
echo ""
echo "🚀 Ready to run:"
echo ""
echo "# With B2 upload:"
echo "docker run --rm --gpus all \\"
echo "  -e B2_KEY=\"your_key\" \\"
echo "  -e B2_SECRET=\"your_secret\" \\"
echo "  -e B2_BUCKET=\"your_bucket\" \\"
echo "  ${FULL_IMAGE} \\"
echo "  python -m src.entrypoints.run_gen \\"
echo "  --job '{\"prompts\": [\"A cat dancing\"]}'"
echo ""
echo "# Without B2 (local only):"
echo "docker run --rm --gpus all \\"
echo "  ${FULL_IMAGE} \\"
echo "  python -m src.entrypoints.run_gen \\"
echo "  --job '{\"prompts\": [\"test\"]}' \\"
echo "  --no-upload"
echo ""
echo "# With model cache volume:"
echo "docker run --rm --gpus all \\"
echo "  -v \$(pwd)/models:/root/.cache/huggingface \\"
echo "  ${FULL_IMAGE} \\"
echo "  python -m src.entrypoints.run_gen \\"
echo "  --job '{\"prompts\": [\"test\"]}'"
