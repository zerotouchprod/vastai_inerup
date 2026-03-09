#!/bin/bash
# Entrypoint script for RunPod Serverless Video Generation
# Models should be pre-loaded in /runpod-volume/models/ from RunPod Network Volume

set -e

echo "=========================================="
echo "RunPod Video Generation Entrypoint"
echo "=========================================="
echo "Model paths (from Network Volume):"
echo "  T2I: /runpod-volume/models/dreamshaper-xl-lightning"
echo "  I2V: /runpod-volume/models/CogVideoX-5b-I2V"
echo "=========================================="

# Check if volume is mounted
if [ ! -d "/runpod-volume" ]; then
    echo "❌ ERROR: /runpod-volume not mounted!"
    echo "   Please mount RunPod Network Volume to /runpod-volume"
    exit 1
fi

# Create model directories if they don't exist (should already exist from volume)
mkdir -p /runpod-volume/models/dreamshaper-xl-lightning
mkdir -p /runpod-volume/models/CogVideoX-5b-I2V
mkdir -p /runpod-volume/output

# Check if models exist in volume
DREAMSHAPER_MODEL="/runpod-volume/models/dreamshaper-xl-lightning/sdxl_lightning_4step_unet.safetensors"
COGVIDEOX_DIR="/runpod-volume/models/CogVideoX-5b-I2V"

# Check DreamShaper
if [ -f "$DREAMSHAPER_MODEL" ]; then
    echo "✅ DreamShaper model found in volume: $DREAMSHAPER_MODEL"
    echo "   Size: $(du -h "$DREAMSHAPER_MODEL" | cut -f1)"
else
    echo "❌ ERROR: DreamShaper model not found in volume!"
    echo "   Expected: $DREAMSHAPER_MODEL"
    echo "   Please upload model to RunPod Network Volume before deployment"
    exit 1
fi

# Check CogVideoX
if [ -d "$COGVIDEOX_DIR" ] && [ "$(ls -A "$COGVIDEOX_DIR" 2>/dev/null)" ]; then
    echo "✅ CogVideoX model directory found in volume"
    echo "   Files count: $(find "$COGVIDEOX_DIR" -type f | wc -l)"
    echo "   Total size: $(du -sh "$COGVIDEOX_DIR" | cut -f1)"
    echo "   First 5 files:"
    ls -la "$COGVIDEOX_DIR" | head -10
else
    echo "❌ ERROR: CogVideoX model not found or empty in volume!"
    echo "   Expected directory: $COGVIDEOX_DIR"
    echo "   Please upload model to RunPod Network Volume before deployment"
    exit 1
fi

# Verify GPU availability
echo "=========================================="
echo "Checking GPU availability..."
python3 -c "
import torch
print(f'PyTorch: {torch.__version__}')
print(f'CUDA available: {torch.cuda.is_available()}')
if torch.cuda.is_available():
    print(f'GPU: {torch.cuda.get_device_name(0)}')
    print(f'VRAM: {torch.cuda.get_device_properties(0).total_memory / 1024**3:.2f} GB')
else:
    print('❌ WARNING: CUDA not available!')
"

# Verify model loading
echo "=========================================="
echo "Verifying model loading..."
python3 -c "
import os
print(f'T2I model exists: {os.path.exists(\"$DREAMSHAPER_MODEL\")}')
print(f'I2V directory exists: {os.path.exists(\"$COGVIDEOX_DIR\")}')
if os.path.exists(\"$COGVIDEOX_DIR\"):
    files = os.listdir(\"$COGVIDEOX_DIR\")
    print(f'I2V files count: {len(files)}')
    if files:
        print(f'First 5 files: {files[:5]}')
"

echo "=========================================="
echo "Starting RunPod Serverless Handler..."
echo "=========================================="

# Start the handler
exec python -m src.entrypoints.runpod_handler