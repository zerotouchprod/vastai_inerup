#!/bin/bash
# Build script for RTX 50 series Docker image

set -e

echo "=================================="
echo "Building Docker image for RTX 50 series"
echo "=================================="
echo ""
echo "NOTE: Using Dockerfile.vastai.optimized.cuda130"
echo "      This is the best Dockerfile for RTX 5080/5090"
echo "      (uses PyTorch cu130 for exact CUDA 13.0.2 match)"
echo ""

# Check if RIFE models exist
if [ ! -d "RIFEv4.26_0921/train_log" ]; then
    echo "ERROR: RIFE models not found!"
    echo "Please ensure RIFEv4.26_0921/train_log/ directory exists"
    exit 1
fi

# Build image using the best Dockerfile
docker build \
    -f docker/Dockerfile.vastai.optimized.cuda130 \
    -t vastai_inerup:rtx50 \
    --build-arg BUILDKIT_INLINE_CACHE=1 \
    .

echo ""
echo "=================================="
echo "✅ Build complete!"
echo "=================================="
echo ""
echo "Image: vastai_inerup:rtx50"
echo "Built from: Dockerfile.vastai.optimized.cuda130 (cu130 - best for RTX 50)"
echo ""
echo "To test locally:"
echo "  docker run --gpus all -it vastai_inerup:rtx50 python3 -c 'import torch; print(f\"CUDA available: {torch.cuda.is_available()}\"); print(f\"Device: {torch.cuda.get_device_name(0) if torch.cuda.is_available() else \"N/A\"}\"); print(f\"sm_120 supported: {\\\"sm_120\\\" in str(torch.cuda.get_arch_list()) if torch.cuda.is_available() else \\\"N/A\\\"}\")'"
echo ""
echo "To push to registry:"
echo "  docker tag vastai_inerup:rtx50 YOUR_REGISTRY/vastai_inerup:rtx50"
echo "  docker push YOUR_REGISTRY/vastai_inerup:rtx50"
echo ""

