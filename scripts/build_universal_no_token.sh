#!/bin/bash
# Build script for Universal Studio Docker image WITHOUT HF_TOKEN dependency
# Uses anonymous downloads only - no rebuild when token changes

set -e

echo "🚀 Building Universal Studio Docker Image (No HF_TOKEN)"
echo "========================================================"

# Configuration
IMAGE_NAME="universal-studio-no-token"
IMAGE_TAG="latest"
DOCKERFILE="docker/Dockerfile.universal_no_token"
BUILD_CONTEXT="."

# Check if podman/docker is available
if command -v podman &> /dev/null; then
    DOCKER_CMD="podman"
    echo "📦 Using Podman"
elif command -v docker &> /dev/null; then
    DOCKER_CMD="docker"
    echo "📦 Using Docker"
else
    echo "❌ Error: Neither podman nor docker found"
    exit 1
fi

# Check disk space
echo "💾 Checking disk space..."
df -h . | grep -E "(Filesystem|/dev/)"

# Build command
echo "🔨 Building image: $IMAGE_NAME:$IMAGE_TAG"
echo "   Dockerfile: $DOCKERFILE (No HF_TOKEN dependency)"
echo "   Context: $BUILD_CONTEXT"
echo "   Note: Using anonymous downloads (lower rate limits)"

# Run build
$DOCKER_CMD build \
    -f "$DOCKERFILE" \
    -t "$IMAGE_NAME:$IMAGE_TAG" \
    --progress=plain \
    "$BUILD_CONTEXT"

# Check build result
if [ $? -eq 0 ]; then
    echo "✅ Build successful!"
    echo ""
    echo "📦 Image details:"
    $DOCKER_CMD images "$IMAGE_NAME:$IMAGE_TAG"
    echo ""
    echo "🚀 To run the container:"
    echo "   $DOCKER_CMD run --gpus all $IMAGE_NAME:$IMAGE_TAG \\"
    echo "     python -m src.services.generation.pipeline \\"
    echo "     --prompt \"Cyberpunk city, realistic, rain\""
    echo ""
    echo "🎨 Test prompts:"
    echo "   • Photorealism: \"Cyberpunk city at night, rain, neon lights, realistic photography\""
    echo "   • Anime: \"Anime girl running through cherry blossom forest, vibrant colors\""
    echo "   • 3D Art: \"Futuristic spaceship, 3D render, cinematic lighting, unreal engine\""
    echo ""
    echo "🔧 Advantages of this build:"
    echo "   • No HF_TOKEN dependency - won't rebuild when token changes"
    echo "   • Cache-friendly - same Dockerfile always produces same image"
    echo "   • Security - no tokens embedded in images"
    echo "   • Anonymous downloads (lower rate limits but acceptable for Docker builds)"
else
    echo "❌ Build failed!"
    exit 1
fi