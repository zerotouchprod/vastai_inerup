#!/bin/bash
# Script to upload models to RunPod network volume using API

set -e

API_KEY="your_runpod_api_key_here"
VOLUME_NAME="shrill_coral_herring"
MOUNT_PATH="/runpod-volume"
HF_TOKEN="${HF_TOKEN:-}"  # Optional: for private models

echo "🚀 RunPod Model Upload Script"
echo "Volume: $VOLUME_NAME"
echo "API Key: ${API_KEY:0:20}..."

# Function to call RunPod GraphQL API
runpod_api() {
    local query="$1"
    local variables="$2"
    
    curl -s -X POST https://api.runpod.io/graphql \
        -H "Content-Type: application/json" \
        -H "Authorization: Bearer $API_KEY" \
        -d "{\"query\": \"$query\", \"variables\": $variables}" \
        | jq .
}

echo ""
echo "📋 Step 1: Find volume ID for '$VOLUME_NAME'"
echo "------------------------------------------------------------"

# Get network volumes
echo "Getting network volumes..."
VOLUMES_QUERY='query { myself { networkVolumes { id name size dataCenterId status } } }'
volume_response=$(runpod_api "$VOLUMES_QUERY" "{}")

volume_id=$(echo "$volume_response" | jq -r ".data.myself.networkVolumes[] | select(.name == \"$VOLUME_NAME\") | .id")

if [ -z "$volume_id" ] || [ "$volume_id" = "null" ]; then
    echo "❌ Volume '$VOLUME_NAME' not found!"
    echo "Available volumes:"
    echo "$volume_response" | jq -r ".data.myself.networkVolumes[] | \"\(.name) (\(.id)) - \(.size)GB\""
    exit 1
fi

echo "✅ Found volume: $VOLUME_NAME ($volume_id)"

echo ""
echo "🚀 Step 2: Create temporary pod with volume mounted"
echo "------------------------------------------------------------"

# Create pod with volume
CREATE_POD_MUTATION='mutation($input: PodFindAndDeployOnDemandInput!) { podFindAndDeployOnDemand(input: $input) { id imageName env machineId machine { podHostId } } }'

POD_VARIABLES=$(cat <<EOF
{
  "input": {
    "cloudType": "SECURE",
    "gpuCount": 1,
    "volumeInGb": 100,
    "containerDiskSizeGb": 50,
    "minVcpuCount": 2,
    "minMemoryInGb": 15,
    "gpuTypeId": "NVIDIA GeForce RTX 4090",
    "name": "model-downloader-script",
    "imageName": "pytorch/pytorch:2.5.1-cuda12.4-cudnn9-runtime",
    "dockerArgs": "",
    "ports": "22/tcp",
    "volumeMountPath": "$MOUNT_PATH",
    "env": [
      {"key": "HF_TOKEN", "value": "$HF_TOKEN"},
      {"key": "HF_HOME", "value": "/root/.cache/huggingface"}
    ]
  }
}
EOF
)

echo "Creating pod..."
pod_response=$(runpod_api "$CREATE_POD_MUTATION" "$POD_VARIABLES")
pod_id=$(echo "$pod_response" | jq -r ".data.podFindAndDeployOnDemand.id")

if [ -z "$pod_id" ] || [ "$pod_id" = "null" ]; then
    echo "❌ Failed to create pod!"
    echo "$pod_response"
    exit 1
fi

echo "✅ Pod created: $pod_id"

echo ""
echo "⏳ Step 3: Wait for pod to be ready (checking every 10 seconds)"
echo "------------------------------------------------------------"

for i in {1..30}; do
    echo "Check $i/30..."
    
    POD_QUERY='query($podId: String!) { pod(input: {podId: $podId}) { id name imageName env machineId runtime { ports { ip isIpPublic privatePort publicPort type } gpus { id gpuUtilPercent memoryUtilPercent } } desiredStatus lastStatusChange __typename } }'
    
    pod_status=$(runpod_api "$POD_QUERY" "{\"podId\": \"$pod_id\"}")
    status=$(echo "$pod_status" | jq -r ".data.pod.desiredStatus")
    
    if [ "$status" = "RUNNING" ]; then
        echo "✅ Pod is running"
        
        # Get SSH details
        ssh_ip=$(echo "$pod_status" | jq -r '.data.pod.runtime.ports[] | select(.privatePort==22) | .ip')
        ssh_port=$(echo "$pod_status" | jq -r '.data.pod.runtime.ports[] | select(.privatePort==22) | .publicPort')
        
        if [ -n "$ssh_ip" ] && [ -n "$ssh_port" ]; then
            echo "✅ SSH available: ssh -p $ssh_port root@$ssh_ip"
            break
        else
            echo "⚠️ SSH not ready yet, waiting..."
        fi
    elif [ "$status" = "FAILED" ]; then
        echo "❌ Pod failed to start"
        exit 1
    else
        echo "   Current status: $status"
    fi
    
    sleep 10
done

if [ -z "$ssh_ip" ] || [ -z "$ssh_port" ]; then
    echo "❌ Could not get SSH details after waiting"
    exit 1
fi

echo ""
echo "📥 Step 4: Download models via SSH"
echo "------------------------------------------------------------"

# Create SSH command function
run_ssh() {
    local cmd="$1"
    ssh -o StrictHostKeyChecking=no -o ConnectTimeout=30 -p "$ssh_port" "root@$ssh_ip" "$cmd"
}

echo "Installing tools..."
run_ssh "apt-get update && apt-get install -y git-lfs wget curl python3-pip" || true
run_ssh "pip3 install huggingface-hub==0.24.0" || true
run_ssh "git lfs install" || true

echo "Creating directories..."
run_ssh "mkdir -p $MOUNT_PATH/models/dreamshaper-xl-lightning"
run_ssh "mkdir -p $MOUNT_PATH/models/CogVideoX-5b-I2V"

echo "Downloading DreamShaper XL Lightning..."
dreamshaper_cmd=$(cat <<EOF
cd $MOUNT_PATH/models/dreamshaper-xl-lightning && \
python3 -c "
from huggingface_hub import hf_hub_download
import os
hf_hub_download(
    repo_id='ByteDance/SDXL-Lightning',
    filename='sdxl_lightning_4step_unet.safetensors',
    local_dir='.',
    local_dir_use_symlinks=False
)
"
EOF
)

run_ssh "$dreamshaper_cmd" || echo "⚠️ DreamShaper download may have issues"

echo "Downloading CogVideoX-5b (this will take a while)..."
cogvideox_cmd=$(cat <<EOF
cd $MOUNT_PATH/models/CogVideoX-5b-I2V && \
python3 -c "
from huggingface_hub import snapshot_download
import os
snapshot_download(
    repo_id='THUDM/CogVideoX-5b',
    local_dir='.',
    local_dir_use_symlinks=False,
    ignore_patterns=['*.bin', '*.msgpack', '*.h5', '*.ot'],
    max_workers=4
)
" > /tmp/cogvideox.log 2>&1 &
EOF
)

run_ssh "$cogvideox_cmd" || echo "⚠️ CogVideoX download started in background"

echo ""
echo "⏳ Step 5: Monitor download progress"
echo "------------------------------------------------------------"

for i in {1..6}; do
    echo "Progress check $i/6 (waiting 5 minutes between checks)..."
    
    run_ssh "echo '=== DreamShaper ===' && ls -lh $MOUNT_PATH/models/dreamshaper-xl-lightning/ 2>/dev/null || echo 'Not downloaded yet'"
    run_ssh "echo '=== CogVideoX ===' && ps aux | grep -E 'python.*huggingface' | grep -v grep || echo 'Process not running'"
    run_ssh "echo '=== Disk Usage ===' && du -sh $MOUNT_PATH/models/* 2>/dev/null || echo 'No models yet'"
    
    if [ $i -lt 6 ]; then
        sleep 300  # 5 minutes
    fi
done

echo ""
echo "🔍 Step 6: Final verification"
echo "------------------------------------------------------------"

run_ssh "echo '=== Final file list ===' && find $MOUNT_PATH/models -name '*.safetensors' -type f | head -10"
run_ssh "echo '=== Total size ===' && du -sh $MOUNT_PATH/models"
run_ssh "echo '=== DreamShaper details ===' && ls -lh $MOUNT_PATH/models/dreamshaper-xl-lightning/"
run_ssh "echo '=== CogVideoX details ===' && ls -lh $MOUNT_PATH/models/CogVideoX-5b-I2V/ | head -5"

echo ""
echo "🗑️ Step 7: Destroy temporary pod"
echo "------------------------------------------------------------"

DESTROY_MUTATION='mutation($input: PodStopInput!) { podStop(input: $input) { id desiredStatus } }'
destroy_response=$(runpod_api "$DESTROY_MUTATION" "{\"input\": {\"podId\": \"$pod_id\"}}")

if echo "$destroy_response" | jq -e ".data.podStop.id" > /dev/null; then
    echo "✅ Pod stopped"
    
    # Terminate pod
    TERMINATE_MUTATION='mutation($input: PodTerminateInput!) { podTerminate(input: $input) { id desiredStatus } }'
    terminate_response=$(runpod_api "$TERMINATE_MUTATION" "{\"input\": {\"podId\": \"$pod_id\"}}")
    
    if echo "$terminate_response" | jq -e ".data.podTerminate.id" > /dev/null; then
        echo "✅ Pod terminated"
    else
        echo "⚠️ Failed to terminate pod"
    fi
else
    echo "⚠️ Failed to stop pod"
fi

echo ""
echo "============================================================"
echo "✅ Model upload completed!"
echo "============================================================"
echo ""
echo "📊 Summary:"
echo "  Volume: $VOLUME_NAME ($volume_id)"
echo "  Models downloaded to: $MOUNT_PATH/models/"
echo "  Pod used: $pod_id (destroyed)"
echo ""
echo "🔧 Next steps:"
echo "  1. Create RunPod serverless endpoint"
echo "  2. Mount volume '$VOLUME_NAME' to endpoint"
echo "  3. Set mount path to '$MOUNT_PATH'"
echo "  4. Test with a simple prompt"
echo ""
echo "💡 Tip: Check volume contents:"
echo "  runpodctl volume list"
echo "  runpodctl volume get $volume_id"