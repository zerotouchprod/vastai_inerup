#!/bin/bash
# Build Video Generation Docker Image
# With CogVideoX-5b-I2V model baked in

set -e

echo "╔════════════════════════════════════════════════════════════════╗"
echo "║                                                                ║"
echo "║         🐳 BUILDING VIDEO GENERATION DOCKER IMAGE 🐳          ║"
echo "║                                                                ║"
echo "╚════════════════════════════════════════════════════════════════╝"
echo ""

# Colors
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

# Configuration
IMAGE_NAME="${IMAGE_NAME:-video-gen}"
IMAGE_TAG="${IMAGE_TAG:-latest}"
DOCKERFILE="${DOCKERFILE:-docker/Dockerfile.gen}"
HF_TOKEN="${HF_TOKEN:-}"
OPTIMIZED="${OPTIMIZED:-0}"

# Check if Dockerfile exists
if [ ! -f "$DOCKERFILE" ]; then
    echo -e "${RED}❌ Error: Dockerfile not found at $DOCKERFILE${NC}"
    exit 1
fi

# Check if requirements.gen.txt exists
if [ ! -f "requirements.gen.txt" ]; then
    echo -e "${RED}❌ Error: requirements.gen.txt not found${NC}"
    exit 1
fi

# Estimate build time
echo -e "${BLUE}📊 Build Information:${NC}"
echo "  Image name: ${IMAGE_NAME}:${IMAGE_TAG}"
echo "  Dockerfile: ${DOCKERFILE}"
echo "  Model: THUDM/CogVideoX-5b-I2V"
if [ -n "$HF_TOKEN" ]; then
    echo "  Authentication: HF_TOKEN provided (higher rate limits)"
else
    echo "  Authentication: No HF_TOKEN (lower rate limits, may be slower)"
fi
echo ""
if [ "$DOCKERFILE" = "docker/Dockerfile.gen.optimized" ]; then
    echo -e "${YELLOW}⏱️  Estimated build time: 12-18 minutes (optimized)${NC}"
    echo -e "${YELLOW}💾 Expected image size: ~10-12GB (optimized)${NC}"
else
    echo -e "${YELLOW}⏱️  Estimated build time: 15-20 minutes${NC}"
    echo -e "${YELLOW}💾 Expected image size: ~15GB${NC}"
fi
echo ""

# Confirm build
read -p "Continue with build? (y/n) " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "Build cancelled."
    exit 0
fi

echo ""
echo -e "${BLUE}🔨 Starting build...${NC}"
echo ""

# Build with progress
BUILD_ARGS="--build-arg CACHEBUST=$(date +%s)"
if [ -n "$HF_TOKEN" ]; then
    echo -e "${YELLOW}🔑 Using HF_TOKEN for authenticated downloads${NC}"
    BUILD_ARGS="$BUILD_ARGS --build-arg HF_TOKEN=$HF_TOKEN"
fi

docker build \
    -f "${DOCKERFILE}" \
    -t "${IMAGE_NAME}:${IMAGE_TAG}" \
    --progress=plain \
    $BUILD_ARGS \
    .

BUILD_EXIT_CODE=$?

if [ $BUILD_EXIT_CODE -eq 0 ]; then
    echo ""
    echo -e "${GREEN}╔════════════════════════════════════════════════════════════════╗${NC}"
    echo -e "${GREEN}║                                                                ║${NC}"
    echo -e "${GREEN}║                  ✅ BUILD SUCCESSFUL! ✅                       ║${NC}"
    echo -e "${GREEN}║                                                                ║${NC}"
    echo -e "${GREEN}╚════════════════════════════════════════════════════════════════╝${NC}"
    echo ""

    # Show image info
    echo -e "${BLUE}📦 Image Information:${NC}"
    docker images "${IMAGE_NAME}:${IMAGE_TAG}" --format "table {{.Repository}}\t{{.Tag}}\t{{.Size}}\t{{.CreatedAt}}"
    echo ""

    # Quick verification
    echo -e "${BLUE}🔍 Quick Verification:${NC}"
    echo "Checking PyTorch and CUDA availability..."
    docker run --rm "${IMAGE_NAME}:${IMAGE_TAG}" \
        python -c 'import torch; print(f"PyTorch {torch.__version__}"); print(f"CUDA available: {torch.cuda.is_available()}")'

    echo ""
    echo "Checking HuggingFace CLI..."
    docker run --rm "${IMAGE_NAME}:${IMAGE_TAG}" \
        python -m huggingface_hub.commands.huggingface_cli --version || echo "CLI check skipped"
    echo ""

    echo -e "${GREEN}✅ Next steps:${NC}"
    echo "  1. Test the image:"
    echo "     docker run --rm --gpus all ${IMAGE_NAME}:${IMAGE_TAG} python -m src.entrypoints.run_gen --help"
    echo ""
    echo "  2. Run a test generation (dry-run):"
    echo "     docker run --rm --gpus all ${IMAGE_NAME}:${IMAGE_TAG} \\"
    echo "       python -m src.entrypoints.run_gen \\"
    echo "       --job '{\"prompts\": [\"test\"]}' --dry-run"
    echo ""
    echo "  3. Full test with actual generation:"
    echo "     export B2_KEY=\"your_key\""
    echo "     export B2_SECRET=\"your_secret\""
    echo "     export B2_BUCKET=\"your_bucket\""
    echo "     docker run --rm --gpus all \\"
    echo "       -e B2_KEY -e B2_SECRET -e B2_BUCKET \\"
    echo "       ${IMAGE_NAME}:${IMAGE_TAG} \\"
    echo "       python -m src.entrypoints.run_gen \\"
    echo "       --job '{\"prompts\": [\"A cat dancing\"]}'"
    echo ""
    echo "  4. See QUICK_COMMANDS.sh for more examples"
    echo ""

else
    echo ""
    echo -e "${RED}╔════════════════════════════════════════════════════════════════╗${NC}"
    echo -e "${RED}║                                                                ║${NC}"
    echo -e "${RED}║                    ❌ BUILD FAILED! ❌                         ║${NC}"
    echo -e "${RED}║                                                                ║${NC}"
    echo -e "${RED}╚════════════════════════════════════════════════════════════════╝${NC}"
    echo ""
    echo -e "${RED}Build failed with exit code: ${BUILD_EXIT_CODE}${NC}"
    echo ""
    echo "Common issues:"
    echo "  1. Network issues downloading model"
    echo "     → Check internet connection"
    echo "     → Try again (may be HuggingFace rate limiting)"
    echo ""
    echo "  2. Out of disk space"
    echo "     → Free up ~20GB disk space"
    echo "     → Run: docker system prune -a"
    echo ""
    echo "  3. Missing files"
    echo "     → Check requirements.gen.txt exists"
    echo "     → Check src/ directory exists"
    echo ""
    exit 1
fi
