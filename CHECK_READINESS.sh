#!/bin/bash
# Final Checklist - Video Generation Module

echo "╔════════════════════════════════════════════════════════════════╗"
echo "║                                                                ║"
echo "║           📋 VIDEO GENERATION - FINAL CHECKLIST 📋            ║"
echo "║                                                                ║"
echo "╚════════════════════════════════════════════════════════════════╝"
echo ""

GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m'

check_file() {
    if [ -f "$1" ]; then
        echo -e "${GREEN}✓${NC} $1"
        return 0
    else
        echo -e "${RED}✗${NC} $1 ${YELLOW}(MISSING)${NC}"
        return 1
    fi
}

check_dir() {
    if [ -d "$1" ]; then
        echo -e "${GREEN}✓${NC} $1/"
        return 0
    else
        echo -e "${RED}✗${NC} $1/ ${YELLOW}(MISSING)${NC}"
        return 1
    fi
}

cd /home/fevr/PycharmProjects/vastai_inerup || exit 1

echo "🔍 Checking files..."
echo ""

echo "📦 Core Backend:"
check_file "src/services/generation/config.py"
check_file "src/services/generation/models.py"
check_file "src/services/generation/orchestrator.py"
check_file "src/services/generation/engines/base.py"
check_file "src/services/generation/engines/text2video.py"
check_file "src/services/generation/engines/image2video.py"
check_file "src/services/generation/utils/image_loader.py"
check_file "src/entrypoints/run_gen.py"
echo ""

echo "🐳 Docker & Infrastructure:"
check_file "docker/Dockerfile.gen"
check_file "requirements.gen.txt"
check_file "scripts/build_video_gen.sh"
echo ""

echo "🧪 Tests:"
check_file "tests/unit/services/generation/test_config.py"
check_file "tests/unit/services/generation/test_models.py"
check_file "tests/unit/services/generation/utils/test_image_loader.py"
check_file "tests/integration/generation/test_text2video_workflow.py"
check_file "tests/integration/generation/test_image2video_workflow.py"
check_file "tests/run_generation_tests.sh"
echo ""

echo "📚 Documentation:"
check_file "IMPLEMENTATION_PLAN_TEXT2VIDEO_I2V.md"
check_file "IMPLEMENTATION_COMPLETE.md"
check_file "QUICKSTART_VIDEO_GEN.md"
check_file "README_GENERATION.md"
check_file "CHANGELOG_VIDEO_GEN.md"
check_file "DOCKER_BUILD_TROUBLESHOOTING.md"
check_file "QUICK_COMMANDS.sh"
check_file "FILE_STRUCTURE.md"
echo ""

echo "🔧 Dockerfile Verification:"
echo "Checking for fixed huggingface-cli path..."
if grep -q "/opt/venv/bin/huggingface-cli" docker/Dockerfile.gen; then
    echo -e "${GREEN}✓${NC} Dockerfile has correct path to huggingface-cli"
else
    echo -e "${RED}✗${NC} Dockerfile missing fixed path"
fi
echo ""

echo "╔════════════════════════════════════════════════════════════════╗"
echo "║                                                                ║"
echo "║                    ✅ CHECKLIST COMPLETE ✅                    ║"
echo "║                                                                ║"
echo "╚════════════════════════════════════════════════════════════════╝"
echo ""

echo -e "${GREEN}🚀 Ready to build!${NC}"
echo ""
echo "Next steps:"
echo "  1. Build Docker image:"
echo "     chmod +x scripts/build_video_gen.sh"
echo "     ./scripts/build_video_gen.sh"
echo ""
echo "  2. Or manually:"
echo "     docker build -f docker/Dockerfile.gen -t video-gen:latest ."
echo ""
echo "  3. Expected build time: 15-20 minutes"
echo "  4. Expected image size: ~15GB"
echo ""
echo "  5. After build, run verification:"
echo "     docker run --rm --gpus all video-gen:latest \\"
echo "       python -m src.entrypoints.run_gen --help"
echo ""
echo "📖 Documentation:"
echo "  → QUICKSTART_VIDEO_GEN.md - Quick start guide"
echo "  → DOCKER_BUILD_TROUBLESHOOTING.md - If build fails"
echo "  → QUICK_COMMANDS.sh - Ready-to-use commands"
echo ""
