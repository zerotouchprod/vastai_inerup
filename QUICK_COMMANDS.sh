#!/bin/bash
# Quick Commands for Video Generation Module

echo "🚀 VIDEO GENERATION - QUICK COMMANDS"
echo "===================================="
echo ""

# Colors
BLUE='\033[0;34m'
GREEN='\033[0;32m'
NC='\033[0m'

echo -e "${BLUE}📦 1. BUILD DOCKER IMAGE${NC}"
echo "----------------------------------------"
echo "# Using build script (recommended):"
echo "chmod +x scripts/build_video_gen.sh"
echo "./scripts/build_video_gen.sh"
echo ""
echo "# Or manually:"
echo "docker build -f docker/Dockerfile.gen -t video-gen:latest ."
echo ""
echo "# Note: Build takes 15-20 minutes (downloads ~11GB model)"
echo "# Final image size: ~15GB"
echo ""

echo -e "${BLUE}🧪 2. RUN TESTS${NC}"
echo "----------------------------------------"
echo "# Unit tests"
echo "pytest tests/unit/services/generation/ -v"
echo ""
echo "# Integration tests"
echo "pytest tests/integration/generation/ -v"
echo ""
echo "# All tests with coverage"
echo "pytest tests/unit/services/generation/ tests/integration/generation/ \\"
echo "  --cov=src/services/generation \\"
echo "  --cov-report=term-missing \\"
echo "  -v"
echo ""

echo -e "${BLUE}🎬 3. TEXT-TO-VIDEO (Simple)${NC}"
echo "----------------------------------------"
cat << 'EOF'
docker run --rm --gpus all \
  -e B2_KEY="${B2_KEY}" \
  -e B2_SECRET="${B2_SECRET}" \
  -e B2_BUCKET="${B2_BUCKET}" \
  video-gen:latest \
  python -m src.entrypoints.run_gen \
  --job '{"prompts": ["A cat dancing in the rain"]}'
EOF
echo ""

echo -e "${BLUE}🎬 4. TEXT-TO-VIDEO (Batch)${NC}"
echo "----------------------------------------"
cat << 'EOF'
docker run --rm --gpus all \
  -e B2_KEY="${B2_KEY}" \
  -e B2_SECRET="${B2_SECRET}" \
  -e B2_BUCKET="${B2_BUCKET}" \
  video-gen:latest \
  python -m src.entrypoints.run_gen \
  --job '{
    "prompts": [
      "A cyberpunk city at night",
      "A sunset over mountains",
      "Underwater coral reef"
    ],
    "guidance_scale": 7.0,
    "num_inference_steps": 40
  }'
EOF
echo ""

echo -e "${BLUE}🖼️  5. IMAGE-TO-VIDEO (URL)${NC}"
echo "----------------------------------------"
cat << 'EOF'
docker run --rm --gpus all \
  -e B2_KEY="${B2_KEY}" \
  -e B2_SECRET="${B2_SECRET}" \
  -e B2_BUCKET="${B2_BUCKET}" \
  video-gen:latest \
  python -m src.entrypoints.run_gen \
  --job '{
    "mode": "image2video",
    "prompts": ["Make the character wave and smile"],
    "input_images": ["https://example.com/anime_character.jpg"],
    "guidance_scale": 7.0,
    "num_frames": 49
  }'
EOF
echo ""

echo -e "${BLUE}🖼️  6. IMAGE-TO-VIDEO (Local File)${NC}"
echo "----------------------------------------"
cat << 'EOF'
docker run --rm --gpus all \
  -v /path/to/images:/images \
  -e B2_KEY="${B2_KEY}" \
  -e B2_SECRET="${B2_SECRET}" \
  -e B2_BUCKET="${B2_BUCKET}" \
  video-gen:latest \
  python -m src.entrypoints.run_gen \
  --job '{
    "mode": "image2video",
    "prompts": ["Animate this character"],
    "input_images": ["/images/character.jpg"]
  }'
EOF
echo ""

echo -e "${BLUE}💾 7. LOCAL STORAGE (No Upload)${NC}"
echo "----------------------------------------"
cat << 'EOF'
docker run --rm --gpus all \
  -v $(pwd)/output:/app/output \
  video-gen:latest \
  python -m src.entrypoints.run_gen \
  --job '{"prompts": ["Test video"]}' \
  --no-upload
EOF
echo ""

echo -e "${BLUE}🔧 8. CUSTOM PARAMETERS${NC}"
echo "----------------------------------------"
cat << 'EOF'
docker run --rm --gpus all \
  -e B2_KEY="${B2_KEY}" \
  -e B2_SECRET="${B2_SECRET}" \
  -e B2_BUCKET="${B2_BUCKET}" \
  -e GEN_DEFAULT_NUM_INFERENCE_STEPS=50 \
  -e GEN_DEFAULT_GUIDANCE_SCALE=7.5 \
  -e GEN_ENABLE_SAFETY_CHECKER=true \
  video-gen:latest \
  python -m src.entrypoints.run_gen \
  --job '{
    "prompts": ["Detailed anime scene"],
    "negative_prompt": "blurry, low quality",
    "seed": 42,
    "guidance_scale": 8.0,
    "num_inference_steps": 60,
    "num_frames": 73,
    "fps": 12
  }'
EOF
echo ""

echo -e "${BLUE}🚀 9. VAST.AI DEPLOYMENT${NC}"
echo "----------------------------------------"
cat << 'EOF'
# На Vast.ai instance:
docker run -d --gpus all \
  --name video-gen-worker \
  --restart unless-stopped \
  -v /workspace/hf_cache:/root/.cache/huggingface \
  -v /workspace/output:/app/output \
  -e B2_KEY="${B2_KEY}" \
  -e B2_SECRET="${B2_SECRET}" \
  -e B2_BUCKET="${B2_BUCKET}" \
  -e GEN_ENABLE_CPU_OFFLOAD=true \
  -e GEN_ENABLE_VAE_SLICING=true \
  video-gen:latest \
  tail -f /dev/null

# Запуск job:
docker exec video-gen-worker \
  python -m src.entrypoints.run_gen \
  --job '{"prompts": ["Test"]}'
EOF
echo ""

echo -e "${BLUE}📊 10. MONITORING${NC}"
echo "----------------------------------------"
echo "# Logs"
echo "docker logs video-gen-worker -f"
echo ""
echo "# GPU usage"
echo "nvidia-smi -l 1"
echo ""
echo "# Disk usage"
echo "du -sh /workspace/output"
echo ""

echo -e "${GREEN}✅ Done! Copy-paste any command above to use.${NC}"
echo ""
echo "📚 Full documentation:"
echo "  → QUICKSTART_VIDEO_GEN.md"
echo "  → README_GENERATION.md"
echo "  → IMPLEMENTATION_PLAN_TEXT2VIDEO_I2V.md"
echo ""
