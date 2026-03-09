#!/usr/bin/env python3
"""
Run video generation pipeline on Vast AI using existing code.

This script:
1. Connects to Vast AI instance
2. Runs the text2image + image2video pipeline
3. Downloads results
4. Cleans up resources
"""

import os
import sys
import json
import time
import subprocess
import argparse
from pathlib import Path
from typing import Dict, Any, Optional

# Add src to path
sys.path.insert(0, str(Path(__file__).parent))

def check_vastai_installed():
    """Check if vastai CLI is installed."""
    try:
        result = subprocess.run(["vastai", "--version"], 
                              capture_output=True, text=True)
        if result.returncode == 0:
            print("✅ vastai CLI is installed")
            return True
        else:
            print("❌ vastai CLI not found or not working")
            return False
    except FileNotFoundError:
        print("❌ vastai CLI not installed")
        print("Install with: pip install vastai")
        return False

def search_instances():
    """Search for available Vast AI instances."""
    print("\n🔍 Searching for available instances...")
    
    # Search for RTX 4090 instances
    cmd = [
        "vastai", "search", "offers",
        "gpu_name=RTX 4090",
        "disk_space>=100",
        "reliability>=0.9",
        "cuda_max_good>=12.0",
        "--order", "dph_total",
        "--raw"
    ]
    
    try:
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            print(f"❌ Search failed: {result.stderr}")
            return []
        
        # Parse JSON output
        offers = json.loads(result.stdout)
        print(f"✅ Found {len(offers)} instances")
        
        for i, offer in enumerate(offers[:5], 1):
            print(f"\n{i}. Instance {offer.get('id')}")
            print(f"   GPU: {offer.get('gpu_name')} ({offer.get('num_gpus')}x)")
            print(f"   Price: ${offer.get('dph_total'):.3f}/hour")
            print(f"   RAM: {offer.get('ram')} GB")
            print(f"   Disk: {offer.get('disk_space')} GB")
            print(f"   Location: {offer.get('geolocation')}")
        
        return offers
        
    except Exception as e:
        print(f"❌ Error searching instances: {e}")
        return []

def create_instance(offer_id: str, image: str = "registry.gitlab.com/gfever/vastai_interup:video-gen"):
    """Create a Vast AI instance."""
    print(f"\n🚀 Creating instance from offer {offer_id}...")
    
    cmd = [
        "vastai", "create", "instance",
        offer_id,
        "--image", image,
        "--disk", "100",
        "--label", "video-gen-pipeline",
        "--raw"
    ]
    
    try:
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            print(f"❌ Instance creation failed: {result.stderr}")
            return None
        
        instance = json.loads(result.stdout)
        print(f"✅ Instance created: {instance.get('id')}")
        print(f"   SSH: ssh -p {instance.get('ssh_port')} root@{instance.get('ssh_host')}")
        print(f"   Status: {instance.get('status')}")
        
        return instance
        
    except Exception as e:
        print(f"❌ Error creating instance: {e}")
        return None

def wait_for_instance(instance_id: str, timeout: int = 300):
    """Wait for instance to be ready."""
    print(f"\n⏳ Waiting for instance {instance_id} to be ready...")
    
    start_time = time.time()
    while time.time() - start_time < timeout:
        cmd = ["vastai", "show", "instance", instance_id, "--raw"]
        result = subprocess.run(cmd, capture_output=True, text=True)
        
        if result.returncode == 0:
            instance = json.loads(result.stdout)
            status = instance.get("status")
            
            if status == "running":
                print("✅ Instance is running")
                return instance
            elif status == "failed":
                print("❌ Instance failed to start")
                return None
            else:
                print(f"   Current status: {status}")
        
        time.sleep(10)
    
    print("❌ Timeout waiting for instance")
    return None

def run_ssh_command(instance: Dict[str, Any], command: str) -> bool:
    """Run SSH command on instance."""
    ssh_host = instance.get("ssh_host")
    ssh_port = instance.get("ssh_port")
    
    if not ssh_host or not ssh_port:
        print("❌ SSH details not available")
        return False
    
    ssh_cmd = [
        "ssh", "-o", "StrictHostKeyChecking=no",
        "-o", "ConnectTimeout=30",
        "-p", str(ssh_port),
        f"root@{ssh_host}",
        command
    ]
    
    try:
        print(f"\n🔧 Running: {command}")
        result = subprocess.run(ssh_cmd, capture_output=True, text=True, timeout=300)
        
        if result.returncode == 0:
            print("✅ Command executed successfully")
            if result.stdout:
                print(f"Output:\n{result.stdout}")
            return True
        else:
            print(f"❌ Command failed: {result.stderr}")
            return False
            
    except subprocess.TimeoutExpired:
        print("❌ Command timed out")
        return False
    except Exception as e:
        print(f"❌ SSH error: {e}")
        return False

def run_pipeline(instance: Dict[str, Any], prompt: str, output_dir: str = "/tmp/results"):
    """Run the video generation pipeline."""
    print(f"\n🎬 Running video generation pipeline...")
    
    # Create output directory
    mkdir_cmd = f"mkdir -p {output_dir}"
    if not run_ssh_command(instance, mkdir_cmd):
        return False
    
    # Prepare job JSON
    job = {
        "prompts": [prompt],
        "guidance_scale": 6.0,
        "num_inference_steps": 25,
        "num_frames": 16,
        "fps": 8,
        "output_prefix": "videos/",
        "seed": 42
    }
    
    job_json = json.dumps(job).replace('"', '\\"')
    
    # Run the pipeline
    pipeline_cmd = f"""
    cd /workspace/vastai_inerup && \
    python -m src.entrypoints.run_gen \
      --job '{job_json}' \
      --verbose \
      --no-upload
    """
    
    if not run_ssh_command(instance, pipeline_cmd):
        return False
    
    # List generated files
    list_cmd = f"find {output_dir} -name '*.mp4' -o -name '*.png' | head -10"
    run_ssh_command(instance, list_cmd)
    
    return True

def download_results(instance: Dict[str, Any], local_dir: str = "./results"):
    """Download results from instance."""
    print(f"\n📥 Downloading results...")
    
    ssh_host = instance.get("ssh_host")
    ssh_port = instance.get("ssh_port")
    
    if not ssh_host or not ssh_port:
        print("❌ SSH details not available")
        return False
    
    # Create local directory
    Path(local_dir).mkdir(parents=True, exist_ok=True)
    
    # Download using scp
    scp_cmd = [
        "scp", "-o", "StrictHostKeyChecking=no",
        "-P", str(ssh_port),
        "-r",
        f"root@{ssh_host}:/tmp/results/*",
        local_dir
    ]
    
    try:
        print(f"Downloading to {local_dir}...")
        result = subprocess.run(scp_cmd, capture_output=True, text=True)
        
        if result.returncode == 0:
            print("✅ Results downloaded successfully")
            
            # List downloaded files
            files = list(Path(local_dir).glob("*"))
            for file in files:
                print(f"   {file.name} ({file.stat().st_size / 1024:.1f} KB)")
            
            return True
        else:
            print(f"❌ Download failed: {result.stderr}")
            return False
            
    except Exception as e:
        print(f"❌ Download error: {e}")
        return False

def destroy_instance(instance_id: str):
    """Destroy Vast AI instance."""
    print(f"\n🗑️  Destroying instance {instance_id}...")
    
    cmd = ["vastai", "destroy", "instance", instance_id]
    
    try:
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode == 0:
            print("✅ Instance destroyed")
            return True
        else:
            print(f"❌ Failed to destroy instance: {result.stderr}")
            return False
    except Exception as e:
        print(f"❌ Error destroying instance: {e}")
        return False

def main():
    """Main function."""
    parser = argparse.ArgumentParser(description="Run video generation pipeline on Vast AI")
    parser.add_argument("--prompt", type=str, required=True,
                       help="Prompt for video generation")
    parser.add_argument("--offer-id", type=str,
                       help="Vast AI offer ID (optional, will search if not provided)")
    parser.add_argument("--keep-instance", action="store_true",
                       help="Keep instance running after completion")
    parser.add_argument("--output-dir", type=str, default="./results",
                       help="Local directory for results")
    parser.add_argument("--test-only", action="store_true",
                       help="Test connection only, don't run pipeline")
    
    args = parser.parse_args()
    
    print("="*60)
    print("Vast AI Video Generation Pipeline")
    print("="*60)
    
    # Check vastai CLI
    if not check_vastai_installed():
        return 1
    
    # Search or use provided offer
    if args.offer_id:
        offer_id = args.offer_id
        print(f"Using provided offer ID: {offer_id}")
    else:
        offers = search_instances()
        if not offers:
            print("❌ No suitable instances found")
            return 1
        
        # Use cheapest instance
        offer_id = offers[0].get("id")
        print(f"Selected cheapest instance: {offer_id}")
    
    # Create instance
    instance = create_instance(offer_id)
    if not instance:
        return 1
    
    instance_id = instance.get("id")
    
    try:
        # Wait for instance to be ready
        instance = wait_for_instance(instance_id)
        if not instance:
            return 1
        
        if args.test_only:
            print("\n✅ Test completed successfully")
            print(f"Instance {instance_id} is running")
            print(f"SSH: ssh -p {instance.get('ssh_port')} root@{instance.get('ssh_host')}")
            return 0
        
        # Run pipeline
        success = run_pipeline(instance, args.prompt)
        if not success:
            print("❌ Pipeline failed")
            return 1
        
        # Download results
        download_results(instance, args.output_dir)
        
        print("\n🎉 Pipeline completed successfully!")
        print(f"Results saved to: {args.output_dir}")
        
        return 0
        
    finally:
        # Cleanup
        if not args.keep_instance and instance_id:
            destroy_instance(instance_id)
        else:
            print(f"\n⚠️  Instance {instance_id} kept running")
            print(f"Destroy manually with: vastai destroy instance {instance_id}")

if __name__ == "__main__":
    sys.exit(main())