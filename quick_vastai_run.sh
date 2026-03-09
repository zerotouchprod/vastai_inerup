#!/bin/bash
# Quick script to run video generation on Vast AI

set -e

PROMPT="${1:-A beautiful sunset over mountains, cinematic, 4k}"
OUTPUT_DIR="./results/$(date +%Y%m%d_%H%M%S)"

echo "🎬 Vast AI Video Generation"
echo "Prompt: $PROMPT"
echo "Output: $OUTPUT_DIR"

# Check if vastai is installed
if ! command -v vastai &> /dev/null; then
    echo "❌ vastai CLI not found"
    echo "Install with: pip install vastai"
    exit 1
fi

# Search for RTX 4090 instance
echo "🔍 Searching for RTX 4090 instance..."
OFFER_ID=$(vastai search offers \
    "gpu_name=RTX 4090" \
    "disk_space>=100" \
    "reliability>=0.9" \
    --order dph_total \
    --raw | jq -r '.[0].id')

if [ -z "$OFFER_ID" ] || [ "$OFFER_ID" = "null" ]; then
    echo "❌ No suitable instances found"
    exit 1
fi

echo "✅ Found instance: $OFFER_ID"

# Create instance
echo "🚀 Creating instance..."
INSTANCE_JSON=$(vastai create instance "$OFFER_ID" \
    --image "registry.gitlab.com/gfever/vastai_interup:video-gen" \
    --disk 100 \
    --label "video-gen-quick" \
    --raw)

INSTANCE_ID=$(echo "$INSTANCE_JSON" | jq -r '.id')
SSH_HOST=$(echo "$INSTANCE_JSON" | jq -r '.ssh_host')
SSH_PORT=$(echo "$INSTANCE_JSON" | jq -r '.ssh_port')

echo "✅ Instance created: $INSTANCE_ID"
echo "   SSH: ssh -p $SSH_PORT root@$SSH_HOST"

# Wait for instance to be ready
echo "⏳ Waiting for instance to start..."
for i in {1..30}; do
    STATUS=$(vastai show instance "$INSTANCE_ID" --raw | jq -r '.status')
    
    if [ "$STATUS" = "running" ]; then
        echo "✅ Instance is running"
        break
    elif [ "$STATUS" = "failed" ]; then
        echo "❌ Instance failed to start"
        vastai destroy instance "$INSTANCE_ID"
        exit 1
    fi
    
    echo "   Status: $STATUS (waiting...)"
    sleep 10
done

if [ "$STATUS" != "running" ]; then
    echo "❌ Instance failed to start in time"
    vastai destroy instance "$INSTANCE_ID"
    exit 1
fi

# Wait a bit more for SSH to be fully ready
sleep 30

# Run the pipeline
echo "🎬 Running video generation..."
JOB_JSON='{
  "prompts": ["'"$PROMPT"'"],
  "guidance_scale": 6.0,
  "num_inference_steps": 25,
  "num_frames": 16,
  "fps": 8,
  "output_prefix": "videos/",
  "seed": 42
}'

# Escape JSON for SSH
JOB_JSON_ESC=$(echo "$JOB_JSON" | sed 's/"/\\"/g')

ssh -o StrictHostKeyChecking=no -o ConnectTimeout=30 -p "$SSH_PORT" "root@$SSH_HOST" "
    echo 'Setting up workspace...'
    mkdir -p /tmp/results
    
    echo 'Running pipeline...'
    cd /workspace/vastai_inerup && \
    python -m src.entrypoints.run_gen \
      --job '$JOB_JSON_ESC' \
      --verbose \
      --no-upload 2>&1
    
    echo 'Listing generated files...'
    find /tmp -name '*.mp4' -o -name '*.png' 2>/dev/null | head -10
"

# Download results
echo "📥 Downloading results..."
mkdir -p "$OUTPUT_DIR"
scp -o StrictHostKeyChecking=no -P "$SSH_PORT" -r "root@$SSH_HOST:/tmp/results/*" "$OUTPUT_DIR/" 2>/dev/null || true

# List downloaded files
echo "📁 Downloaded files:"
find "$OUTPUT_DIR" -type f | while read -r file; do
    size=$(du -h "$file" | cut -f1)
    echo "   $(basename "$file") ($size)"
done

# Destroy instance
echo "🗑️  Destroying instance..."
vastai destroy instance "$INSTANCE_ID"

echo ""
echo "🎉 Done!"
echo "Results saved to: $OUTPUT_DIR"
echo "Prompt: $PROMPT"