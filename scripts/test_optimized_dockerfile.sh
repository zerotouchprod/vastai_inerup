#!/bin/bash
# Test optimized Dockerfile without full build
# Quick validation of Dockerfile syntax and dependencies

set -e

echo "🔍 Testing optimized Dockerfile.gen.optimized"
echo ""

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

DOCKERFILE="docker/Dockerfile.gen.optimized"

# Check if Dockerfile exists
if [ ! -f "$DOCKERFILE" ]; then
    echo -e "${RED}❌ Error: Dockerfile not found at $DOCKERFILE${NC}"
    exit 1
fi

echo -e "${GREEN}✅ Dockerfile found: $DOCKERFILE${NC}"
echo ""

# Check Dockerfile syntax with hadolint if available
if command -v hadolint &> /dev/null; then
    echo "📋 Checking Dockerfile syntax with hadolint..."
    hadolint "$DOCKERFILE" && echo -e "${GREEN}✅ Dockerfile syntax OK${NC}" || echo -e "${YELLOW}⚠️  Hadolint warnings (non-critical)${NC}"
else
    echo -e "${YELLOW}⚠️  hadolint not installed, skipping syntax check${NC}"
    echo "  Install: sudo apt-get install hadolint"
fi
echo ""

# Check for common issues
echo "🔍 Checking for common issues..."
echo ""

# 1. Check base images
echo "1. Checking base images..."
if grep -q "FROM ubuntu:22.04" "$DOCKERFILE"; then
    echo -e "   ${GREEN}✅ Stage 1: ubuntu:22.04 (lightweight)${NC}"
else
    echo -e "   ${RED}❌ Stage 1: Wrong base image${NC}"
fi

if grep -q "FROM nvidia/cuda:12.4.0-cudnn9-devel-ubuntu22.04" "$DOCKERFILE"; then
    echo -e "   ${GREEN}✅ Stage 2: nvidia/cuda:12.4.0-cudnn9-devel-ubuntu22.04${NC}"
else
    echo -e "   ${RED}❌ Stage 2: Wrong base image${NC}"
fi

if grep -q "FROM nvidia/cuda:12.4.0-cudnn9-runtime-ubuntu22.04" "$DOCKERFILE"; then
    echo -e "   ${GREEN}✅ Stage 3: nvidia/cuda:12.4.0-cudnn9-runtime-ubuntu22.04${NC}"
else
    echo -e "   ${RED}❌ Stage 3: Wrong base image${NC}"
fi
echo ""

# 2. Check multi-stage build
echo "2. Checking multi-stage build structure..."
STAGE_COUNT=$(grep -c "^FROM " "$DOCKERFILE")
if [ "$STAGE_COUNT" -eq 3 ]; then
    echo -e "   ${GREEN}✅ 3-stage build detected${NC}"
else
    echo -e "   ${RED}❌ Expected 3 stages, found $STAGE_COUNT${NC}"
fi
echo ""

# 3. Check model download command
echo "3. Checking model download command..."
if grep -q "python -m huggingface_hub.cli.hf download THUDM/CogVideoX-5b-I2V" "$DOCKERFILE"; then
    echo -e "   ${GREEN}✅ Model download command found${NC}"
else
    echo -e "   ${RED}❌ Model download command missing${NC}"
fi
echo ""

# 4. Check virtual environment usage
echo "4. Checking virtual environment usage..."
if grep -q "python3 -m venv /opt/venv" "$DOCKERFILE"; then
    echo -e "   ${GREEN}✅ Virtual environment setup found${NC}"
else
    echo -e "   ${RED}❌ Virtual environment setup missing${NC}"
fi
echo ""

# 5. Check cleanup commands
echo "5. Checking cleanup commands..."
if grep -q "rm -rf /var/lib/apt/lists/" "$DOCKERFILE"; then
    echo -e "   ${GREEN}✅ APT cache cleanup found${NC}"
else
    echo -e "   ${YELLOW}⚠️  APT cache cleanup missing${NC}"
fi

if grep -q "rm -rf /root/.cache/pip" "$DOCKERFILE"; then
    echo -e "   ${GREEN}✅ PIP cache cleanup found${NC}"
else
    echo -e "   ${YELLOW}⚠️  PIP cache cleanup missing${NC}"
fi
echo ""

# 6. Check environment variables
echo "6. Checking critical environment variables..."
REQUIRED_ENVS=("HF_HOME" "HF_HUB_OFFLINE" "TORCH_INFERENCE_MODE" "PYTORCH_CUDA_ALLOC_CONF")
for env in "${REQUIRED_ENVS[@]}"; do
    if grep -q "ENV $env" "$DOCKERFILE"; then
        echo -e "   ${GREEN}✅ $env found${NC}"
    else
        echo -e "   ${RED}❌ $env missing${NC}"
    fi
done
echo ""

# 7. Check COPY commands
echo "7. Checking COPY commands..."
if grep -q "COPY --from=downloader /model_cache" "$DOCKERFILE"; then
    echo -e "   ${GREEN}✅ Model copy from downloader stage found${NC}"
else
    echo -e "   ${RED}❌ Model copy missing${NC}"
fi

if grep -q "COPY --from=builder /opt/venv" "$DOCKERFILE"; then
    echo -e "   ${GREEN}✅ Virtual environment copy from builder found${NC}"
else
    echo -e "   ${RED}❌ Virtual environment copy missing${NC}"
fi
echo ""

# 8. Check healthcheck
echo "8. Checking healthcheck..."
if grep -q "^HEALTHCHECK" "$DOCKERFILE"; then
    echo -e "   ${GREEN}✅ Healthcheck found${NC}"
else
    echo -e "   ${YELLOW}⚠️  Healthcheck missing (optional)${NC}"
fi
echo ""

# Summary
echo "📊 Summary:"
echo "=========="
echo "Optimized Dockerfile analysis complete."
echo ""
echo "Expected optimizations:"
echo "  • Lightweight base images (ubuntu + cuda instead of full pytorch)"
echo "  • 3-stage build (downloader, builder, runtime)"
echo "  • Virtual environment for dependency isolation"
echo "  • Cache cleanup in each stage"
echo "  • Model baked into image (required for Vast.ai)"
echo ""
echo "To test full build:"
echo "  ./scripts/build_video_gen_external.sh"
echo ""
echo "Or quick test without external HDD:"
echo "  export HF_TOKEN=\"your_token\""
echo "  docker build -f docker/Dockerfile.gen.optimized -t test-optimized ."
echo ""

echo -e "${GREEN}✅ Dockerfile validation complete${NC}"