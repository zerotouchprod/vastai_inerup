#!/usr/bin/env python3
"""
Simple script to upload models to RunPod network volume.

This script provides instructions and commands to:
1. Create a temporary pod with network volume mounted
2. Download DreamShaper XL Lightning and CogVideoX-5b models
3. Save them to the network volume
4. Destroy the temporary pod
"""

import os
import sys
import json
import subprocess
from pathlib import Path

# Configuration
RUNPOD_API_KEY = "your_runpod_api_key_here"
VOLUME_NAME = "shrill_coral_herring"
MOUNT_PATH = "/runpod-volume"

def check_runpod_cli():
    """Check if runpodctl CLI is installed."""
    try:
        result = subprocess.run(["runpodctl", "--version"], 
                              capture_output=True, text=True)
        if result.returncode == 0:
            print("✅ runpodctl CLI is installed")
            return True
        else:
            print("❌ runpodctl not found or not working")
            return False
    except FileNotFoundError:
        print("❌ runpodctl CLI not installed")
        print("Install with: curl -sSL https://cli.runpod.io/install.sh | sudo bash")
        return False

def generate_commands():
    """Generate commands for manual execution."""
    print("="*60)
    print("RunPod Model Upload Instructions")
    print("="*60)
    
    print(f"\n📋 Volume: {VOLUME_NAME}")
    print(f"📋 Mount Path: {MOUNT_PATH}")
    print(f"📋 API Key: {RUNPOD_API_KEY[:20]}...")
    
    print("\n🚀 Step 1: Create temporary pod with volume mounted")
    print("-"*50)
    
    create_pod_cmd = f"""runpodctl pod create \\
  --name "model-downloader" \\
  --image "pytorch/pytorch:2.5.1-cuda12.4-cudnn9-runtime" \\
  --gpu-type "NVIDIA GeForce RTX 4090" \\
  --volume "{VOLUME_NAME}:{MOUNT_PATH}" \\
  --container-disk-size 50 \\
  --env "HF_TOKEN=your-huggingface-token" \\
  --env "HF_HOME=/root/.cache/huggingface" \\
  --cloud-type "secure" \\
  --support-public-ip true"""
    
    print(create_pod_cmd)
    
    print("\n📥 Step 2: Connect to pod and download models")
    print("-"*50)
    
    download_commands = f"""# SSH into the pod (use the IP and port from pod details)
ssh -p <PORT> root@<IP>

# Once connected, run these commands:

# 1. Install necessary tools
apt-get update && apt-get install -y git-lfs wget curl python3-pip
pip3 install huggingface-hub==0.24.0
git lfs install

# 2. Create model directories
mkdir -p {MOUNT_PATH}/models/dreamshaper-xl-lightning
mkdir -p {MOUNT_PATH}/models/CogVideoX-5b-I2V

# 3. Download DreamShaper XL Lightning (~6.5GB)
cd {MOUNT_PATH}/models/dreamshaper-xl-lightning
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

# 4. Download CogVideoX-5b (~18GB, this will take time)
cd {MOUNT_PATH}/models/CogVideoX-5b-I2V
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
" > /tmp/cogvideox_download.log 2>&1 &

# 5. Check download progress
tail -f /tmp/cogvideox_download.log
# OR check with:
ps aux | grep python | grep huggingface
du -sh {MOUNT_PATH}/models/CogVideoX-5b-I2V/

# 6. Verify downloads
ls -lh {MOUNT_PATH}/models/dreamshaper-xl-lightning/
ls -lh {MOUNT_PATH}/models/CogVideoX-5b-I2V/ | head -10
du -sh {MOUNT_PATH}/models/*"""
    
    print(download_commands)
    
    print("\n🗑️ Step 3: Destroy the temporary pod")
    print("-"*50)
    
    destroy_cmd = """# Get pod ID
runpodctl pod list

# Destroy pod
runpodctl pod destroy <POD_ID>"""
    
    print(destroy_cmd)
    
    print("\n🔍 Step 4: Verify volume contents")
    print("-"*50)
    
    verify_cmd = f"""# Create another pod to verify
runpodctl pod create \\
  --name "volume-verifier" \\
  --image "ubuntu:22.04" \\
  --gpu-type "NVIDIA GeForce RTX 4090" \\
  --volume "{VOLUME_NAME}:{MOUNT_PATH}" \\
  --container-disk-size 10 \\
  --cloud-type "secure"
  
# SSH and check
ssh -p <PORT> root@<IP>
ls -la {MOUNT_PATH}/models/
du -sh {MOUNT_PATH}/models/*
find {MOUNT_PATH}/models -name "*.safetensors" | head -10"""
    
    print(verify_cmd)
    
    print("\n📊 Expected file structure:")
    print("-"*50)
    
    structure = f"""{MOUNT_PATH}/models/
├── dreamshaper-xl-lightning/
│   └── sdxl_lightning_4step_unet.safetensors  (~6.5GB)
└── CogVideoX-5b-I2V/
    ├── diffusion_pytorch_model.safetensors     (~18GB)
    ├── config.json
    └── ... other model files"""
    
    print(structure)
    
    print("\n⏱️ Estimated download times:")
    print("-"*50)
    print("DreamShaper XL Lightning: 5-15 minutes (6.5GB)")
    print("CogVideoX-5b: 30-60 minutes (18GB)")
    print("Total: 35-75 minutes")
    
    print("\n💰 Estimated cost:")
    print("-"*50)
    print("RTX 4090 pod: $0.70-$1.20/hour")
    print("1 hour download: $0.70-$1.20")
    print("Volume storage: $0.50/GB/month (100GB = $50/month)")

def create_automation_script():
    """Create an automation script for advanced users."""
    script_content = """#!/bin/bash
# Auto-download models to RunPod network volume

set -e

VOLUME_NAME="shrill_coral_herring"
MOUNT_PATH="/runpod-volume"
HF_TOKEN="${HF_TOKEN:-}"  # Set your HuggingFace token

echo "🚀 Starting model download to volume: $VOLUME_NAME"

# Step 1: Create pod
echo "Creating pod..."
POD_JSON=$(runpodctl pod create \\
  --name "auto-model-downloader" \\
  --image "pytorch/pytorch:2.5.1-cuda12.4-cudnn9-runtime" \\
  --gpu-type "NVIDIA GeForce RTX 4090" \\
  --volume "$VOLUME_NAME:$MOUNT_PATH" \\
  --container-disk-size 50 \\
  --env "HF_TOKEN=$HF_TOKEN" \\
  --env "HF_HOME=/root/.cache/huggingface" \\
  --cloud-type "secure" \\
  --support-public-ip true \\
  --raw)

POD_ID=$(echo "$POD_JSON" | jq -r '.id')
SSH_PORT=$(echo "$POD_JSON" | jq -r '.runtime.ports[] | select(.privatePort==22) | .publicPort')
SSH_IP=$(echo "$POD_JSON" | jq -r '.runtime.ports[] | select(.privatePort==22) | .ip')

echo "✅ Pod created: $POD_ID"
echo "   SSH: ssh -p $SSH_PORT root@$SSH_IP"

# Wait for pod to be ready
echo "⏳ Waiting for pod to be ready..."
sleep 30

# Step 2: Download models
echo "📥 Downloading models..."
ssh -o StrictHostKeyChecking=no -o ConnectTimeout=30 -p "$SSH_PORT" "root@$SSH_IP" "
    echo 'Installing tools...'
    apt-get update && apt-get install -y git-lfs wget curl python3-pip
    pip3 install huggingface-hub==0.24.0
    git lfs install
    
    echo 'Creating directories...'
    mkdir -p $MOUNT_PATH/models/dreamshaper-xl-lightning
    mkdir -p $MOUNT_PATH/models/CogVideoX-5b-I2V
    
    echo 'Downloading DreamShaper XL Lightning...'
    cd $MOUNT_PATH/models/dreamshaper-xl-lightning
    python3 -c \"
from huggingface_hub import hf_hub_download
import os
hf_hub_download(
    repo_id='ByteDance/SDXL-Lightning',
    filename='sdxl_lightning_4step_unet.safetensors',
    local_dir='.',
    local_dir_use_symlinks=False
)
\" 2>&1 | tee /tmp/dreamshaper.log
    
    echo 'Downloading CogVideoX-5b (this will take a while)...'
    cd $MOUNT_PATH/models/CogVideoX-5b-I2V
    python3 -c \"
from huggingface_hub import snapshot_download
import os
snapshot_download(
    repo_id='THUDM/CogVideoX-5b',
    local_dir='.',
    local_dir_use_symlinks=False,
    ignore_patterns=['*.bin', '*.msgpack', '*.h5', '*.ot'],
    max_workers=4
)
\" > /tmp/cogvideox.log 2>&1 &
    
    echo 'Downloads started in background.'
    echo 'Check progress with: tail -f /tmp/cogvideox.log'
"

# Step 3: Monitor progress
echo "⏳ Monitoring download progress..."
for i in {1..12}; do
    echo "Check $i/12..."
    ssh -o StrictHostKeyChecking=no -p "$SSH_PORT" "root@$SSH_IP" "
        echo 'DreamShaper log (last 5 lines):'
        tail -5 /tmp/dreamshaper.log 2>/dev/null || echo 'No log yet'
        echo ''
        echo 'CogVideoX progress:'
        ps aux | grep -E 'python.*huggingface' | grep -v grep || echo 'Process not running'
        echo ''
        echo 'Disk usage:'
        du -sh $MOUNT_PATH/models/* 2>/dev/null || echo 'No models yet'
    "
    sleep 300  # 5 minutes
done

# Step 4: Verify and destroy
echo "🔍 Verifying downloads..."
ssh -o StrictHostKeyChecking=no -p "$SSH_PORT" "root@$SSH_IP" "
    echo 'Final verification:'
    find $MOUNT_PATH/models -name '*.safetensors' -type f | head -10
    du -sh $MOUNT_PATH/models
    ls -lh $MOUNT_PATH/models/dreamshaper-xl-lightning/
    ls -lh $MOUNT_PATH/models/CogVideoX-5b-I2V/ | head -5
"

echo "🗑️ Destroying pod..."
runpodctl pod destroy "$POD_ID"

echo "✅ Done! Models uploaded to volume: $VOLUME_NAME"
echo "   Total size: Check with: runpodctl volume list"
"""

    script_path = Path(__file__).parent / "auto_upload_models.sh"
    with open(script_path, "w") as f:
        f.write(script_content)
    
    os.chmod(script_path, 0o755)
    print(f"\n📁 Automation script created: {script_path}")
    print("Usage: HF_TOKEN=your_token ./auto_upload_models.sh")

def main():
    """Main function."""
    print("="*60)
    print("RunPod Model Upload to Network Volume")
    print("="*60)
    
    # Check for runpodctl
    if not check_runpod_cli():
        print("\n⚠️ Please install runpodctl first:")
        print("curl -sSL https://cli.runpod.io/install.sh | sudo bash")
        print("Then configure with: runpodctl config --api-key=<your-api-key>")
        return
    
    # Generate commands
    generate_commands()
    
    # Create automation script
    create_automation_script()
    
    print("\n" + "="*60)
    print("✅ Instructions generated successfully!")
    print("="*60)
    print("\nNext steps:")
    print("1. Install runpodctl if not already installed")
    print("2. Configure with your API key")
    print("3. Run the commands above")
    print("4. Or use the automation script: ./auto_upload_models.sh")
    print("\nNote: You need a HuggingFace token for private/gated models.")
    print("Get one at: https://huggingface.co/settings/tokens")

if __name__ == "__main__":
    main()