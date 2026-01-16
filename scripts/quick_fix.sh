#!/bin/bash
# Quick fix: Update corr.py on server and restart processing

echo "🔧 Quick Fix: Updating corr.py on running Vast.ai instance..."
echo ""

# Pull latest code
echo "Step 1/3: Pulling latest code..."
cd ~/vastai_inerup || cd /root/vastai_inerup || { echo "❌ Project not found!"; exit 1; }
git pull origin main_rmsubs_roi_ar

echo ""
echo "Step 2/3: Updating /opt/ProPainter/RAFT/corr.py..."

# Use the update script
bash scripts/update_corrpy.sh

if [ $? -ne 0 ]; then
    echo "❌ Update failed!"
    exit 1
fi

echo ""
echo "Step 3/3: Done!"
echo ""
echo "✅ System updated and ready!"
echo ""
echo "Now you can re-run your pipeline:"
echo "  python pipeline_v2.py --input video.mp4 --mode remove-subtitles"
echo ""

