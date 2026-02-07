#!/bin/bash
# Build Video Generation Docker Image on External HDD
# With CogVideoX-5b-I2V model baked in
# Optimized for limited disk space on main drive

set -e

echo "╔════════════════════════════════════════════════════════════════╗"
echo "║                                                                ║"
echo "║   🐳 BUILDING VIDEO GEN DOCKER IMAGE (EXTERNAL HDD) 🐳        ║"
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
IMAGE_NAME="${IMAGE_NAME:-video-gen-optimized}"
IMAGE_TAG="${IMAGE_TAG:-latest}"
DOCKERFILE="docker/Dockerfile.gen.optimized"
HF_TOKEN="${HF_TOKEN:-}"
EXTERNAL_MOUNT="${EXTERNAL_MOUNT:-/mnt/external_hdd}"
PROJECT_NAME="vastai_inerup_external"

# Check if external mount exists
if [ ! -d "$EXTERNAL_MOUNT" ]; then
    echo -e "${YELLOW}⚠️  External mount not found at: $EXTERNAL_MOUNT${NC}"
    echo ""
    echo -e "${BLUE}📋 To set up external HDD:${NC}"
    echo "  1. Connect external HDD"
    echo "  2. Find device: sudo fdisk -l"
    echo "  3. Create mount point: sudo mkdir -p $EXTERNAL_MOUNT"
    echo "  4. Mount: sudo mount /dev/sdX1 $EXTERNAL_MOUNT"
    echo "  5. Set permissions: sudo chmod 777 $EXTERNAL_MOUNT"
    echo ""
    read -p "Continue with current directory instead? (y/n) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        echo "Build cancelled."
        exit 0
    fi
    EXTERNAL_MOUNT="."
    PROJECT_NAME="vastai_inerup"
fi

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

# Prepare external directory
EXTERNAL_PROJECT_PATH="$EXTERNAL_MOUNT/$PROJECT_NAME"
if [ "$EXTERNAL_MOUNT" != "." ]; then
    echo -e "${BLUE}📂 Preparing external HDD build...${NC}"
    echo "  Source: $(pwd)"
    echo "  Destination: $EXTERNAL_PROJECT_PATH"
    
    # Clean previous build if exists
    if [ -d "$EXTERNAL_PROJECT_PATH" ]; then
        echo -e "${YELLOW}⚠️  Cleaning previous build directory...${NC}"
        rm -rf "$EXTERNAL_PROJECT_PATH"
    fi
    
    # Copy project to external HDD
    echo -e "${BLUE}📋 Copying project to external HDD...${NC}"
    mkdir -p "$EXTERNAL_PROJECT_PATH"
    
    # Copy only necessary files (exclude large directories)
    echo "  Copying source files..."
    cp -r src/ "$EXTERNAL_PROJECT_PATH/src/"
    cp -r docker/ "$EXTERNAL_PROJECT_PATH/docker/"
    cp requirements.gen.txt "$EXTERNAL_PROJECT_PATH/"
    cp .dockerignore "$EXTERNAL_PROJECT_PATH/" 2>/dev/null || true
    
    # Change to external directory
    cd "$EXTERNAL_PROJECT_PATH"
    echo -e "${GREEN}✅ Project copied to external HDD${NC}"
fi

# Estimate build time
echo ""
echo -e "${BLUE}📊 Build Information:${NC}"
echo "  Image name: ${IMAGE_NAME}:${IMAGE_TAG}"
echo "  Dockerfile: ${DOCKERFILE}"
echo "  Build location: $(pwd)"
echo "  Model: THUDM/CogVideoX-5b-I2V"
if [ -n "$HF_TOKEN" ]; then
    echo "  Authentication: HF_TOKEN provided (higher rate limits)"
else
    echo "  Authentication: No HF_TOKEN (lower rate limits, may be slower)"
fi
echo ""
echo -e "${YELLOW}⏱️  Estimated build time: 15-20 minutes${NC}"
echo -e "${YELLOW}💾 Expected image size: ~10-12GB (optimized)${NC}"
echo -e "${YELLOW}💿 Required disk space: ~30GB temporary + ~12GB final${NC}"
echo ""

# Check disk space on current location
echo -e "${BLUE}📊 Disk Space Check:${NC}"
df -h "$(pwd)" | tail -1
echo ""

# Confirm build
read -p "Continue with build? (y/n) " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "Build cancelled."
    exit 0
fi

echo ""
echo -e "${BLUE}🔨 Starting build on $(pwd)...${NC}"
echo ""

# Build with progress
BUILD_ARGS="--build-arg CACHEBUST=$(date +%s)"
if [ -n "$HF_TOKEN" ]; then
    echo -e "${YELLOW}🔑 Using HF_TOKEN for authenticated downloads${NC}"
    BUILD_ARGS="$BUILD_ARGS --build-arg HF_TOKEN=$HF_TOKEN"
fi

# Enable BuildKit for better performance
export DOCKER_BUILDKIT=1

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

    # Compare with original if exists
    if docker images "video-gen:latest" --format "{{.Repository}}" | grep -q "video-gen"; then
        echo -e "${BLUE}📊 Size Comparison:${NC}"
        echo "  Optimized: $(docker images "${IMAGE_NAME}:${IMAGE_TAG}" --format "{{.Size}}")"
        echo "  Original:  $(docker images "video-gen:latest" --format "{{.Size}}")"
        echo ""
    fi

    # Quick verification
    echo -e "${BLUE}🔍 Quick Verification:${NC}"
    echo "Checking PyTorch and CUDA availability..."
    docker run --rm "${IMAGE_NAME}:${IMAGE_TAG}" \
        python -c 'import torch; print(f"PyTorch {torch.__version__}"); print(f"CUDA available: {torch.cuda.is_available()}")'

    echo ""
    echo "Checking model cache..."
    docker run --rm "${IMAGE_NAME}:${IMAGE_TAG}" \
        find /root/.cache/huggingface -type f -name "*.safetensors" | head -5 | xargs -I {} sh -c 'echo "  $(basename {})"'

    echo ""
    echo -e "${GREEN}✅ Next steps:${NC}"
    echo "  1. Test the image:"
    echo "     docker run --rm --gpus all ${IMAGE_NAME}:${IMAGE_TAG} python -m src.entrypoints.run_gen --help"
    echo ""
    echo "  2. Push to registry (if needed):"
    echo "     docker tag ${IMAGE_NAME}:${IMAGE_TAG} your-registry/video-gen:optimized"
    echo "     docker push your-registry/video-gen:optimized"
    echo ""
    echo "  3. Clean up external directory (if used):"
    if [ "$EXTERNAL_MOUNT" != "." ]; then
        echo "     rm -rf $EXTERNAL_PROJECT_PATH"
    fi
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
    echo "  1. Out of disk space on external HDD"
    echo "     → Check: df -h $EXTERNAL_MOUNT"
    echo "     → Need at least 30GB free"
    echo ""
    echo "  2. Docker daemon not running"
    echo "     → Check: sudo systemctl status docker"
    echo "     → Start: sudo systemctl start docker"
    echo ""
    echo "  3. Network issues downloading model"
    echo "     → Check internet connection"
    echo "     → Try with HF_TOKEN for higher rate limits"
    echo ""
    echo "  4. CUDA/cuDNN version mismatch"
    echo "     → Check NVIDIA driver: nvidia-smi"
    echo "     → Should be compatible with CUDA 12.4"
    echo ""
    
    # Clean up external directory on failure
    if [ "$EXTERNAL_MOUNT" != "." ] && [ -d "$EXTERNAL_PROJECT_PATH" ]; then
        echo -e "${YELLOW}🧹 Cleaning up external directory...${NC}"
        rm -rf "$EXTERNAL_PROJECT_PATH"
    fi
    
    exit 1
fi

# Clean up external directory on success (optional)
if [ "$EXTERNAL_MOUNT" != "." ] && [ -d "$EXTERNAL_PROJECT_PATH" ]; then
    echo ""
    read -p "Clean up external directory ($EXTERNAL_PROJECT_PATH)? (y/n) " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        echo -e "${YELLOW}🧹 Cleaning up external directory...${NC}"
        rm -rf "$EXTERNAL_PROJECT_PATH"
        echo -e "${GREEN}✅ External directory cleaned${NC}"
    fi
fi

echo ""
echo -e "${GREEN}✨ Build completed successfully! ✨${NC}"