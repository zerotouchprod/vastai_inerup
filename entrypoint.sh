#!/bin/bash
set -e

echo "============================================================"
echo "RunPod Serverless — HunyuanVideo T2V"
echo "============================================================"

# ── Pull latest code from git ─────────────────────────────────────────────────
cd /app
echo "📦 Pulling latest code from branch: $(git branch --show-current)"
git pull --ff-only origin main_video_gen 2>&1 || echo "⚠️  git pull failed (offline?) — running with existing code"
echo "📌 Current commit: $(git log --oneline -1)"
echo "============================================================"

# ── Runtime dep check: bitsandbytes (нужен для 8-bit квантизации) ─────────────
python3 -c "import bitsandbytes" 2>/dev/null || {
    echo "📦 Installing bitsandbytes..."
    pip install bitsandbytes==0.44.1 -q
}

# ── Debug mode ────────────────────────────────────────────────────────────────
if [ "${DEBUG}" = "1" ]; then
    echo "🐛 DEBUG MODE — running debug_handler.py"
    echo "============================================================"
    exec python3 /app/debug_handler.py
fi

# ── Check only mode ───────────────────────────────────────────────────────────
if [ "${CHECK}" = "1" ]; then
    echo "🔍 CHECK MODE — environment + model check only"
    echo "============================================================"
    exec python3 /app/debug_handler.py --check
fi

# ── Production ────────────────────────────────────────────────────────────────
echo "🚀 Starting production handler..."
exec python3 -m src.entrypoints.runpod_handler
