#!/bin/bash
# Docker Build Options for Video Generation
# Shows all available build options for limited disk space

set -e

echo "╔════════════════════════════════════════════════════════════════╗"
echo "║                                                                ║"
echo "║        🐳 DOCKER BUILD OPTIONS FOR LIMITED DISK SPACE 🐳      ║"
echo "║                                                                ║"
echo "╚════════════════════════════════════════════════════════════════╝"
echo ""

# Colors
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

echo -e "${BLUE}📊 Current Disk Space:${NC}"
df -h . | tail -1
echo ""

echo -e "${BLUE}🎯 Available Build Options:${NC}"
echo ""

echo "1. ${GREEN}Original Build (requires ~75GB)${NC}"
echo "   Size: ~15GB image + ~30GB temporary = ~45GB total"
echo "   Command: ./scripts/build_video_gen.sh"
echo "   Dockerfile: docker/Dockerfile.gen"
echo ""

echo "2. ${GREEN}Optimized Build (requires ~60GB)${NC}"
echo "   Size: ~10-12GB image + ~25GB temporary = ~35GB total"
echo "   Command: DOCKERFILE=docker/Dockerfile.gen.optimized ./scripts/build_video_gen.sh"
echo "   Dockerfile: docker/Dockerfile.gen.optimized"
echo "   Savings: 20-30% smaller image, 15-20% faster build"
echo ""

echo "3. ${GREEN}External HDD Build (recommended for < 75GB free)${NC}"
echo "   Size: ~10-12GB image, build on external drive"
echo "   Command: ./scripts/build_video_gen_external.sh"
echo "   Requirements: External HDD with ~100GB free space"
echo "   Mount point: /mnt/external_hdd (configurable)"
echo ""

echo "4. ${GREEN}Quick Test (no full build)${NC}"
echo "   Command: ./scripts/test_optimized_dockerfile.sh"
echo "   Purpose: Validate Dockerfile syntax and structure"
echo ""

echo -e "${BLUE}🔧 Configuration Options:${NC}"
echo ""
echo "HF_TOKEN (for faster downloads):"
echo "  export HF_TOKEN=\"hf_your_token_here\""
echo "  Without token: 10GB/hour limit"
echo "  With token: 50GB/hour limit"
echo ""
echo "External HDD mount point:"
echo "  export EXTERNAL_MOUNT=\"/mnt/external_hdd\""
echo "  Default: /mnt/external_hdd"
echo ""

echo -e "${BLUE}📋 Recommended Workflow:${NC}"
echo ""
echo "If you have < 75GB free on main drive:"
echo "  1. Connect external HDD (100GB+ recommended)"
echo "  2. sudo mkdir -p /mnt/external_hdd"
echo "  3. sudo mount /dev/sdX1 /mnt/external_hdd"
echo "  4. sudo chmod 777 /mnt/external_hdd"
echo "  5. export HF_TOKEN=\"hf_your_token\""
echo "  6. ./scripts/build_video_gen_external.sh"
echo ""

echo "If you have > 75GB free on main drive:"
echo "  1. export HF_TOKEN=\"hf_your_token\""
echo "  2. DOCKERFILE=docker/Dockerfile.gen.optimized ./scripts/build_video_gen.sh"
echo ""

echo -e "${BLUE}🔍 Verification After Build:${NC}"
echo ""
echo "Check image size:"
echo "  docker images video-gen-optimized"
echo ""
echo "Test PyTorch and CUDA:"
echo "  docker run --rm video-gen-optimized \\"
echo "    python -c 'import torch; print(f\"PyTorch {torch.__version__}\"); print(f\"CUDA: {torch.cuda.is_available()}\")'"
echo ""
echo "Check model files:"
echo "  docker run --rm video-gen-optimized \\"
echo "    find /root/.cache/huggingface -name \"*.safetensors\" | head -5"
echo ""

echo -e "${BLUE}📚 Documentation:${NC}"
echo ""
echo "Full optimization details:"
echo "  docs/DOCKERFILE_OPTIMIZATION.md"
echo ""
echo "Troubleshooting:"
echo "  DOCKER_BUILD_TROUBLESHOOTING.md"
echo ""

echo -e "${YELLOW}⚠️  Important Notes:${NC}"
echo "• Model is baked into image (required for Vast.ai)"
echo "• CUDA 12.4 requires NVIDIA driver >= 535.86.10"
echo "• Build time: 12-20 minutes depending on internet speed"
echo "• Use HF_TOKEN for faster model downloads"
echo ""

echo -e "${GREEN}✅ Ready to build? Choose option 1, 2, or 3 above.${NC}"
echo ""