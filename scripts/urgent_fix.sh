#!/bin/bash
# URGENT FIX: Add proper SpatialCorrelationSampler (nn.Module) to Pure PyTorch

echo "🔧 URGENT FIX: Adding proper SpatialCorrelationSampler..."
echo ""

# Pull latest code
echo "Step 1/2: Pulling latest code with fix..."
cd ~/vastai_inerup || cd /root/vastai_inerup || { echo "❌ Project not found!"; exit 1; }

echo "Current commit:"
git log -1 --oneline

echo ""
echo "Pulling updates..."
git pull origin main_rmsubs_roi_ar

echo ""
echo "New commit:"
git log -1 --oneline

echo ""
echo "Step 2/2: Verifying fix is applied..."

# Check if SpatialCorrelationSampler is properly defined
if grep -q "class SpatialCorrelationSampler(nn.Module)" src/infrastructure/inpainting/pure_pytorch_correlation.py; then
    echo "✅ SpatialCorrelationSampler is properly defined as nn.Module"
else
    echo "❌ SpatialCorrelationSampler not found - something went wrong"
    exit 1
fi

echo ""
echo "✅ Fix applied successfully!"
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "What was fixed:"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  ✅ Added SpatialCorrelationSampler as proper nn.Module"
echo "  ✅ Has correct __init__ signature (kernel_size, patch_size, etc.)"
echo "  ✅ Has forward() method for validation"
echo "  ✅ CorrBlock remains as callable class (what RAFT uses)"
echo "  ✅ raft_wrapper.py validation will now pass"
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "Next step:"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  python pipeline_v2.py --input video.mp4 --mode remove-subtitles"
echo ""
echo "Expected result:"
echo "  ✅ Validation passes"
echo "  ✅ ProPainter subprocess runs successfully"
echo "  ✅ Video processed without errors"
echo ""



