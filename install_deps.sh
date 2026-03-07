#!/bin/bash
# Script to install all dependencies for video generation
# This can be used in Dockerfile or for manual setup

set -e

echo "=== Installing video generation dependencies ==="

# Update pip
pip install --upgrade pip

# Install PyTorch with CUDA 12.4 support (updated to fix CVE-2025-32434)
echo "Installing PyTorch 2.6.0 with CUDA 12.4..."
pip install \
    torch==2.6.0+cu124 \
    torchvision==0.21.0+cu124 \
    torchaudio==2.6.0+cu124 \
    --index-url https://download.pytorch.org/whl/cu124

# Install requirements from requirements.gen.txt
echo "Installing requirements from requirements.gen.txt..."
pip install -r requirements.gen.txt

# Install xformers compatible with torch 2.6.0
echo "Installing xformers 0.0.29.post3..."
pip install xformers==0.0.29.post3 --index-url https://download.pytorch.org/whl/cu124

# Verify installations
echo "=== Verification ==="
python -c "import torch; print(f'PyTorch: {torch.__version__}'); print(f'CUDA available: {torch.cuda.is_available()}'); print(f'CUDA version: {torch.version.cuda}')"
python -c "import diffusers; print(f'Diffusers: {diffusers.__version__}')"
python -c "import transformers; print(f'Transformers: {transformers.__version__}')"
python -c "import tiktoken; print('tiktoken: OK')"
python -c "import sentencepiece; print('sentencepiece: OK')"
python -c "import protobuf; print(f'protobuf: {protobuf.__version__}')"

echo "=== Dependencies installed successfully! ==="