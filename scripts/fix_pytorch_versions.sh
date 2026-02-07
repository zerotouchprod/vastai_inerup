#!/bin/bash
# Fix PyTorch versions in all Dockerfiles to use compatible versions for CUDA 12.4

set -e

echo "🔧 Fixing PyTorch versions in Dockerfiles..."
echo "============================================="

# Target versions (compatible with CUDA 12.4)
TORCH_VERSION="2.5.1+cu124"
TORCHVISION_VERSION="0.20.1+cu124"
TORCHAUDIO_VERSION="2.5.1+cu124"

# Find all Dockerfiles
DOCKERFILES=$(find . -name "Dockerfile*" -type f | grep -v ".git" | sort)

echo "📁 Found Dockerfiles:"
for file in $DOCKERFILES; do
    echo "  - $file"
done

echo ""
echo "🔄 Updating PyTorch versions..."

for file in $DOCKERFILES; do
    echo ""
    echo "📄 Processing: $file"
    
    # Check current versions
    echo "  Current versions:"
    grep -n "torch==" "$file" 2>/dev/null || echo "    No torch version found"
    grep -n "torchvision==" "$file" 2>/dev/null || echo "    No torchvision version found"
    grep -n "torchaudio==" "$file" 2>/dev/null || echo "    No torchaudio version found"
    
    # Update versions
    if grep -q "torch==" "$file"; then
        sed -i "s/torch==[0-9]\+\.[0-9]\+\.[0-9]\+[^ ]*/torch==$TORCH_VERSION/g" "$file"
        echo "  ✅ Updated torch to $TORCH_VERSION"
    fi
    
    if grep -q "torchvision==" "$file"; then
        sed -i "s/torchvision==[0-9]\+\.[0-9]\+\.[0-9]\+[^ ]*/torchvision==$TORCHVISION_VERSION/g" "$file"
        echo "  ✅ Updated torchvision to $TORCHVISION_VERSION"
    fi
    
    if grep -q "torchaudio==" "$file"; then
        sed -i "s/torchaudio==[0-9]\+\.[0-9]\+\.[0-9]\+[^ ]*/torchaudio==$TORCHAUDIO_VERSION/g" "$file"
        echo "  ✅ Updated torchaudio to $TORCHAUDIO_VERSION"
    fi
    
    # Check for problematic versions
    if grep -q "torchvision==0\.22\.0" "$file"; then
        echo "  ⚠️  WARNING: Found torchvision 0.22.0 (incompatible with CUDA 12.4)"
        sed -i "s/torchvision==0\.22\.0[^ ]*/torchvision==$TORCHVISION_VERSION/g" "$file"
        echo "  ✅ Fixed torchvision version"
    fi
    
    if grep -q "torch==2\.6\.0" "$file"; then
        echo "  ⚠️  WARNING: Found torch 2.6.0 (may have typing-extensions issues)"
        sed -i "s/torch==2\.6\.0[^ ]*/torch==$TORCH_VERSION/g" "$file"
        echo "  ✅ Fixed torch version"
    fi
done

echo ""
echo "✅ All Dockerfiles updated!"
echo ""
echo "📋 Summary of changes:"
echo "  - torch: $TORCH_VERSION"
echo "  - torchvision: $TORCHVISION_VERSION"
echo "  - torchaudio: $TORCHAUDIO_VERSION"
echo ""
echo "🚀 To apply these changes to the server:"
echo "  git add docker/ && git commit -m 'fix: Update PyTorch versions for CUDA 12.4 compatibility'"
echo "  git push origin main_video_gen"
echo ""
echo "🔍 Verification:"
for file in $DOCKERFILES; do
    echo ""
    echo "📄 $file:"
    grep -E "(torch==|torchvision==|torchaudio==)" "$file" 2>/dev/null || echo "  No PyTorch versions found"
done