#!/bin/bash
# Check RunPod network volume contents

set -e

API_KEY="your_runpod_api_key_here"
VOLUME_NAME="shrill_coral_herring"

echo "🔍 Checking RunPod volume: $VOLUME_NAME"
echo "API Key: ${API_KEY:0:20}..."
echo ""

# Function to call RunPod API
runpod_api() {
    local query="$1"
    local variables="${2:-{}}"
    
    curl -s -X POST https://api.runpod.io/graphql \
        -H "Content-Type: application/json" \
        -H "Authorization: Bearer $API_KEY" \
        -d "{\"query\": \"$query\", \"variables\": $variables}" \
        | jq .
}

echo "📋 Step 1: Get volume information"
echo "------------------------------------------------------------"

VOLUME_QUERY='query { myself { networkVolumes { id name size dataCenterId status } } }'
volume_info=$(runpod_api "$VOLUME_QUERY")

# Extract specific volume
volume_data=$(echo "$volume_info" | jq -r ".data.myself.networkVolumes[] | select(.name == \"$VOLUME_NAME\")")

if [ -z "$volume_data" ] || [ "$volume_data" = "null" ]; then
    echo "❌ Volume '$VOLUME_NAME' not found!"
    echo ""
    echo "Available volumes:"
    echo "$volume_info" | jq -r ".data.myself.networkVolumes[] | \"  \(.name) (\(.id)) - \(.size)GB - \(.status)\""
    exit 1
fi

volume_id=$(echo "$volume_data" | jq -r '.id')
volume_size=$(echo "$volume_data" | jq -r '.size')
volume_status=$(echo "$volume_data" | jq -r '.status')
volume_dc=$(echo "$volume_data" | jq -r '.dataCenterId')

echo "✅ Volume found:"
echo "   ID: $volume_id"
echo "   Name: $VOLUME_NAME"
echo "   Size: ${volume_size}GB"
echo "   Status: $volume_status"
echo "   Data Center: $volume_dc"
echo ""

echo "🚀 Step 2: Create verification pod"
echo "------------------------------------------------------------"

CREATE_POD_MUTATION='mutation($input: PodFindAndDeployOnDemandInput!) { podFindAndDeployOnDemand(input: $input) { id imageName env machineId } }'

POD_VARIABLES=$(cat <<EOF
{
  "input": {
    "cloudType": "SECURE",
    "gpuCount": 1,
    "volumeInGb": 20,
    "containerDiskSizeGb": 10,
    "minVcpuCount": 1,
    "minMemoryInGb": 2,
    "gpuTypeId": "NVIDIA GeForce RTX 4090",
    "name": "volume-checker",
    "imageName": "ubuntu:22.04",
    "dockerArgs": "",
    "ports": "22/tcp",
    "volumeMountPath": "/runpod-volume",
    "env": []
  }
}
EOF
)

echo "Creating verification pod..."
pod_response=$(runpod_api "$CREATE_POD_MUTATION" "$POD_VARIABLES")
pod_id=$(echo "$pod_response" | jq -r ".data.podFindAndDeployOnDemand.id")

if [ -z "$pod_id" ] || [ "$pod_id" = "null" ]; then
    echo "❌ Failed to create pod!"
    echo "$pod_response"
    exit 1
fi

echo "✅ Pod created: $pod_id"
echo ""

echo "⏳ Step 3: Wait for pod to be ready"
echo "------------------------------------------------------------"

for i in {1..10}; do
    echo "Check $i/10..."
    
    POD_QUERY='query($podId: String!) { pod(input: {podId: $podId}) { id runtime { ports { ip isIpPublic privatePort publicPort } } desiredStatus } }'
    
    pod_status=$(runpod_api "$POD_QUERY" "{\"podId\": \"$pod_id\"}")
    status=$(echo "$pod_status" | jq -r ".data.pod.desiredStatus")
    
    if [ "$status" = "RUNNING" ]; then
        ssh_ip=$(echo "$pod_status" | jq -r '.data.pod.runtime.ports[] | select(.privatePort==22) | .ip')
        ssh_port=$(echo "$pod_status" | jq -r '.data.pod.runtime.ports[] | select(.privatePort==22) | .publicPort')
        
        if [ -n "$ssh_ip" ] && [ -n "$ssh_port" ]; then
            echo "✅ Pod is running"
            echo "✅ SSH: ssh -p $ssh_port root@$ssh_ip"
            break
        fi
    fi
    
    sleep 10
done

if [ -z "$ssh_ip" ] || [ -z "$ssh_port" ]; then
    echo "❌ Could not get SSH details"
    
    # Clean up
    echo "Cleaning up..."
    runpod_api 'mutation($input: PodStopInput!) { podStop(input: $input) { id } }' "{\"input\": {\"podId\": \"$pod_id\"}}"
    exit 1
fi

echo ""
echo "🔍 Step 4: Check volume contents"
echo "------------------------------------------------------------"

# SSH and check
echo "Checking volume contents via SSH..."
ssh -o StrictHostKeyChecking=no -o ConnectTimeout=30 -p "$ssh_port" "root@$ssh_ip" "
    echo '=== Volume mount point ==='
    ls -la /runpod-volume/
    echo ''
    
    echo '=== Models directory ==='
    if [ -d '/runpod-volume/models' ]; then
        ls -la /runpod-volume/models/
        echo ''
        
        echo '=== DreamShaper XL Lightning ==='
        if [ -d '/runpod-volume/models/dreamshaper-xl-lightning' ]; then
            ls -lh /runpod-volume/models/dreamshaper-xl-lightning/
            echo 'File count:'
            find /runpod-volume/models/dreamshaper-xl-lightning -type f | wc -l
        else
            echo '❌ Directory not found'
        fi
        echo ''
        
        echo '=== CogVideoX-5b ==='
        if [ -d '/runpod-volume/models/CogVideoX-5b-I2V' ]; then
            ls -lh /runpod-volume/models/CogVideoX-5b-I2V/ | head -20
            echo 'File count:'
            find /runpod-volume/models/CogVideoX-5b-I2V -type f | wc -l
        else
            echo '❌ Directory not found'
        fi
        echo ''
        
        echo '=== Disk usage ==='
        du -sh /runpod-volume/models/*
        echo ''
        
        echo '=== Safetensors files ==='
        find /runpod-volume/models -name '*.safetensors' -type f | head -10
        echo ''
        
        echo '=== Total size ==='
        du -sh /runpod-volume/models/
    else
        echo '❌ Models directory not found'
        echo 'Current volume contents:'
        find /runpod-volume -type f | head -20
    fi
"

echo ""
echo "🗑️ Step 5: Clean up"
echo "------------------------------------------------------------"

echo "Stopping pod..."
stop_response=$(runpod_api 'mutation($input: PodStopInput!) { podStop(input: $input) { id } }' "{\"input\": {\"podId\": \"$pod_id\"}}")

if echo "$stop_response" | jq -e ".data.podStop.id" > /dev/null; then
    echo "✅ Pod stopped"
    
    echo "Terminating pod..."
    terminate_response=$(runpod_api 'mutation($input: PodTerminateInput!) { podTerminate(input: $input) { id } }' "{\"input\": {\"podId\": \"$pod_id\"}}")
    
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
echo "✅ Volume check completed!"
echo "============================================================"
echo ""
echo "📊 Summary for volume '$VOLUME_NAME':"
echo "  ID: $volume_id"
echo "  Size: ${volume_size}GB"
echo "  Status: $volume_status"
echo ""
echo "💡 Next steps:"
echo "  If models are missing, run: ./upload_models_api.sh"
echo "  If volume is empty, you need to upload models"
echo "  If everything is OK, create serverless endpoint"