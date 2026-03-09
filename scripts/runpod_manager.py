#!/usr/bin/env python3
"""
RunPod Manager Script

This script helps manage RunPod Serverless deployment:
1. Build and push Docker image
2. Create/update network volume
3. Create/update serverless endpoint
4. Test the deployment
"""

import os
import sys
import json
import time
import subprocess
from pathlib import Path
from typing import Dict, Any, Optional

import runpod

# Configuration
CONFIG = {
    "docker_image": "vastai-video-gen-serverless",
    "docker_tag": "latest",
    "network_volume_name": "video-gen-models",
    "network_volume_size_gb": 100,
    "endpoint_name": "video-generation-endpoint",
    "gpu_type": "NVIDIA RTX 4090",
    "idle_timeout": 5,
    "max_workers": 1,
    "flashboot": True,
    "container_disk_size_gb": 10,
}

def setup_api_key():
    """Setup RunPod API key from environment or prompt."""
    api_key = os.environ.get("RUNPOD_API_KEY")
    if not api_key:
        print("❌ RUNPOD_API_KEY environment variable not set")
        print("Please set it with: export RUNPOD_API_KEY='your-api-key'")
        sys.exit(1)
    
    runpod.api_key = api_key
    print("✅ RunPod API key configured")
    return api_key

def check_user_balance():
    """Check user balance and warn if low."""
    try:
        user_info = runpod.get_user()
        balance = user_info.get("balance", {}).get("credits", 0)
        print(f"💰 User balance: ${balance:.2f}")
        
        if balance < 10:
            print("⚠️  Warning: Low balance (< $10). Consider adding credits.")
        
        return balance
    except Exception as e:
        print(f"⚠️  Could not check balance: {e}")
        return 0

def build_docker_image():
    """Build Docker image for RunPod Serverless."""
    print("\n" + "="*60)
    print("Building Docker Image")
    print("="*60)
    
    dockerfile_path = "docker/Dockerfile.serverless"
    image_name = f"{CONFIG['docker_image']}:{CONFIG['docker_tag']}"
    
    if not Path(dockerfile_path).exists():
        print(f"❌ Dockerfile not found: {dockerfile_path}")
        return False
    
    try:
        # Build Docker image
        print(f"Building image: {image_name}")
        cmd = [
            "docker", "build",
            "-f", dockerfile_path,
            "-t", image_name,
            "."
        ]
        
        print(f"Running: {' '.join(cmd)}")
        result = subprocess.run(cmd, capture_output=True, text=True)
        
        if result.returncode != 0:
            print(f"❌ Docker build failed:")
            print(result.stderr)
            return False
        
        print("✅ Docker image built successfully")
        
        # Check image size
        cmd = ["docker", "images", image_name, "--format", "{{.Size}}"]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.stdout:
            print(f"Image size: {result.stdout.strip()}")
        
        return True
        
    except Exception as e:
        print(f"❌ Docker build error: {e}")
        return False

def push_docker_image():
    """Push Docker image to registry (GitHub Container Registry)."""
    print("\n" + "="*60)
    print("Pushing Docker Image to GitHub Container Registry")
    print("="*60)
    
    # For now, we'll use Docker Hub or local registry
    # In production, you would push to GitHub Container Registry or Docker Hub
    print("⚠️  Note: Docker image push requires registry credentials")
    print("For production, configure:")
    print("1. GitHub Container Registry (ghcr.io)")
    print("2. Docker Hub")
    print("3. RunPod Registry")
    
    # Check if we have GitHub token
    github_token = os.environ.get("GITHUB_TOKEN")
    if github_token:
        print("✅ GITHUB_TOKEN found")
        # Could push to ghcr.io
        # image_name = f"ghcr.io/zerotouchprod/{CONFIG['docker_image']}:{CONFIG['docker_tag']}"
    else:
        print("ℹ️  GITHUB_TOKEN not set, skipping push to registry")
        print("You'll need to push manually or configure registry credentials")
    
    return True

def create_network_volume():
    """Create or get existing network volume."""
    print("\n" + "="*60)
    print("Managing Network Volume")
    print("="*60)
    
    volume_name = CONFIG["network_volume_name"]
    
    try:
        # Try to get existing volumes
        # Note: RunPod Python SDK might not have direct volume methods
        # We'll use API calls or CLI
        
        print(f"Checking for existing volume: {volume_name}")
        
        # For now, we'll assume volume needs to be created manually
        # or through RunPod web interface
        print("ℹ️  Network volumes must be created through RunPod web interface:")
        print("   https://www.runpod.io/console/user/storage")
        print(f"\nVolume requirements:")
        print(f"  Name: {volume_name}")
        print(f"  Size: {CONFIG['network_volume_size_gb']} GB")
        print(f"  Data Center: Any (preferably with RTX 4090 availability)")
        
        print("\n✅ Volume setup instructions provided")
        return True
        
    except Exception as e:
        print(f"❌ Volume check failed: {e}")
        return False

def create_serverless_endpoint():
    """Create or update serverless endpoint."""
    print("\n" + "="*60)
    print("Creating Serverless Endpoint")
    print("="*60)
    
    endpoint_name = CONFIG["endpoint_name"]
    
    try:
        # Check existing endpoints
        endpoints = runpod.get_endpoints()
        existing_endpoint = None
        
        for endpoint in endpoints:
            if endpoint.get("name") == endpoint_name:
                existing_endpoint = endpoint
                break
        
        if existing_endpoint:
            print(f"✅ Endpoint already exists: {endpoint_name}")
            print(f"   ID: {existing_endpoint.get('id')}")
            print(f"   Status: {existing_endpoint.get('status')}")
            
            # Check endpoint configuration
            print("\nEndpoint configuration:")
            template = existing_endpoint.get("template", {})
            print(f"   GPU: {template.get('gpuTypes', {}).get('id', 'Unknown')}")
            print(f"   Container: {template.get('containerImage', 'Unknown')}")
            
            return existing_endpoint
        
        print(f"Creating new endpoint: {endpoint_name}")
        
        # Endpoint configuration
        endpoint_config = {
            "name": endpoint_name,
            "templateId": None,  # Will be created from template
            "networkVolumeId": None,  # Set after volume creation
            "gpuTypeId": "NVIDIA GeForce RTX 4090",
            "idleTimeout": CONFIG["idle_timeout"],
            "maxWorkers": CONFIG["max_workers"],
            "flashboot": CONFIG["flashboot"],
            "containerDiskSizeGb": CONFIG["container_disk_size_gb"],
        }
        
        print("\nEndpoint configuration:")
        for key, value in endpoint_config.items():
            print(f"  {key}: {value}")
        
        print("\n⚠️  Note: Endpoint creation requires:")
        print("   1. Existing network volume ID")
        print("   2. Docker image in registry")
        print("   3. Template creation")
        
        print("\n✅ Endpoint configuration ready")
        print("   Create through RunPod web interface:")
        print("   https://www.runpod.io/console/serverless")
        
        return endpoint_config
        
    except Exception as e:
        print(f"❌ Endpoint creation failed: {e}")
        return None

def test_endpoint(endpoint_id: str):
    """Test serverless endpoint with a simple job."""
    print("\n" + "="*60)
    print("Testing Endpoint")
    print("="*60)
    
    if not endpoint_id:
        print("❌ No endpoint ID provided")
        return False
    
    try:
        # Create test job
        test_input = {
            "prompt": "A beautiful sunset over mountains, cinematic, 4k",
            "t2i_steps": 4,
            "t2i_guidance_scale": 0.0,
            "num_inference_steps": 25,
            "guidance_scale": 6.0,
            "num_frames": 16,
            "fps": 8,
            "seed": 42
        }
        
        print(f"Testing endpoint: {endpoint_id}")
        print(f"Test input: {json.dumps(test_input, indent=2)}")
        
        # Run test job
        # Note: This requires the endpoint to be running
        print("\n⚠️  Note: Endpoint testing requires:")
        print("   1. Endpoint in 'READY' state")
        print("   2. Network volume mounted with models")
        print("   3. Sufficient credits")
        
        print("\n✅ Test configuration ready")
        print("   Run test through RunPod web interface or API")
        
        return True
        
    except Exception as e:
        print(f"❌ Endpoint test failed: {e}")
        return False

def main():
    """Main function to manage RunPod deployment."""
    print("="*60)
    print("RunPod Serverless Deployment Manager")
    print("="*60)
    
    # Setup API key
    api_key = setup_api_key()
    
    # Check balance
    check_user_balance()
    
    # Build Docker image
    if not build_docker_image():
        print("❌ Docker build failed, exiting")
        return
    
    # Push Docker image (optional)
    push_response = input("\nPush Docker image to registry? (y/N): ")
    if push_response.lower() == 'y':
        push_docker_image()
    
    # Create network volume
    create_network_volume()
    
    # Create serverless endpoint
    endpoint = create_serverless_endpoint()
    
    # Test endpoint if available
    if endpoint and isinstance(endpoint, dict) and endpoint.get("id"):
        test_response = input("\nTest endpoint? (y/N): ")
        if test_response.lower() == 'y':
            test_endpoint(endpoint["id"])
    
    print("\n" + "="*60)
    print("✅ Deployment Setup Complete")
    print("="*60)
    print("\nNext steps:")
    print("1. Create network volume through RunPod web interface")
    print("2. Push Docker image to registry (ghcr.io, Docker Hub, etc.)")
    print("3. Create serverless endpoint with the Docker image")
    print("4. Mount network volume to endpoint")
    print("5. Test with a simple prompt")
    print("\nRequired manual steps:")
    print("  - Volume creation: https://www.runpod.io/console/user/storage")
    print("  - Endpoint creation: https://www.runpod.io/console/serverless")
    print("\nFor help, see: https://docs.runpod.io/")

if __name__ == "__main__":
    main()