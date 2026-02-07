#!/bin/bash
# Build script for Universal Studio Docker image
# Optimized for RTX 4090/5090 with DreamShaper XL Lightning + CogVideoX

set -e

echo "🚀 Building Universal Studio Docker Image"
echo "=========================================="

# Configuration
IMAGE_NAME="universal-studio"
IMAGE_TAG="latest"
DOCKERFILE="docker/Dockerfile.anime_studio"  # Updated to use universal model
BUILD_CONTEXT="."
HF_TOKEN="${HF_TOKEN:-}"  # Optional: set HF_TOKEN for authenticated downloads

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

# Build arguments
BUILD_ARGS=""
if [ -n "$HF_TOKEN" ]; then
    BUILD_ARGS="--build-arg HF_TOKEN=$HF_TOKEN"
    echo "🔑 Using HF_TOKEN for authenticated downloads"
else
    echo "⚠️  No HF_TOKEN provided, using unauthenticated downloads (rate limited)"
fi

# Build command
echo "🔨 Building image: $IMAGE_NAME:$IMAGE_TAG"
echo "   Dockerfile: $DOCKERFILE"
echo "   Context: $BUILD_CONTEXT"

# Run build
$DOCKER_CMD build \
    -f "$DOCKERFILE" \
    -t "$IMAGE_NAME:$IMAGE_TAG" \
    --progress=plain \
    $BUILD_ARGS \
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
else
    echo "❌ Build failed!"
    exit 1
fi