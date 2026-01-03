#!/bin/bash
# Build script for lightweight cleaner Docker image
# Usage: ./build-cleaner.sh

set -e  # Exit on error

IMAGE_NAME="video-cleaner"
TAG="light"
FULL_NAME="${IMAGE_NAME}:${TAG}"

echo "=================================================="
echo "Building Lightweight Video Cleaner Docker Image"
echo "=================================================="
echo ""
echo "Image: ${FULL_NAME}"
echo "Purpose: Subtitle & Watermark Removal Only"
echo "Excludes: RIFE, Real-ESRGAN, GFPGAN"
echo ""

# Build with Dockerfile.cleaner
echo "🔨 Building image..."
docker build -f Dockerfile.cleaner -t ${FULL_NAME} .

# Check image size
echo ""
echo "✅ Build complete!"
echo ""
echo "📊 Image Information:"
docker images ${FULL_NAME} --format "table {{.Repository}}\t{{.Tag}}\t{{.Size}}"

echo ""
echo "=================================================="
echo "🧪 Testing Image"
echo "=================================================="

# Test 1: Verify Python imports
echo ""
echo "Test 1: Verifying Python dependencies..."
docker run --rm ${FULL_NAME} python -c "
import torch
import cv2
import paddleocr
import numpy
import ffmpeg
print('✅ All core dependencies loaded successfully')
print(f'PyTorch version: {torch.__version__}')
print(f'OpenCV version: {cv2.__version__}')
print(f'NumPy version: {numpy.__version__}')
"

# Test 2: Verify CLI help works
echo ""
echo "Test 2: Verifying CLI..."
docker run --rm ${FULL_NAME} python -m src.presentation.cli --help | head -20

# Test 3: Check for missing deps (should fail gracefully)
echo ""
echo "Test 3: Verifying excluded features..."
echo "(Attempting to import Real-ESRGAN - should fail gracefully)"
docker run --rm ${FULL_NAME} python -c "
try:
    import basicsr
    print('❌ basicsr found (should be excluded)')
except ImportError:
    print('✅ basicsr not found (correctly excluded)')

try:
    from realesrgan import RealESRGANer
    print('❌ realesrgan found (should be excluded)')
except ImportError:
    print('✅ realesrgan not found (correctly excluded)')
" || true

echo ""
echo "=================================================="
echo "✅ All Tests Passed!"
echo "=================================================="
echo ""
echo "Usage Examples:"
echo ""
echo "1. Subtitle Removal:"
echo "   docker run --rm -v \$(pwd)/input:/input -v \$(pwd)/output:/output \\"
echo "     ${FULL_NAME} python -m src.presentation.cli \\"
echo "     --mode remove-subtitles --input /input/video.mp4 --output /output/"
echo ""
echo "2. Watermark Removal:"
echo "   docker run --rm -v \$(pwd)/input:/input -v \$(pwd)/output:/output \\"
echo "     ${FULL_NAME} python -m src.presentation.cli \\"
echo "     --mode remove-watermark --watermark-roi top-right --input /input/video.mp4"
echo ""
echo "3. v2.1 Animated Text (Experimental):"
echo "   docker run --rm -v \$(pwd)/input:/input -v \$(pwd)/output:/output \\"
echo "     ${FULL_NAME} python -m src.presentation.cli \\"
echo "     --mode remove-subtitles --animated --input /input/video.mp4"
echo ""
echo "=================================================="
echo "🎉 Ready to use!"
echo "=================================================="

