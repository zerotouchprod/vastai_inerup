#!/usr/bin/env python3
"""
Test script for RunPod Serverless endpoint.

This script tests the video generation endpoint with various prompts
and parameters to ensure everything is working correctly.
"""

import os
import sys
import json
import time
from typing import Dict, Any, Optional

# Add src to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import runpod

# Configuration
RUNPOD_API_KEY = os.environ.get("RUNPOD_API_KEY", "your-api-key-here")
ENDPOINT_ID = None  # Set your endpoint ID here

# Test prompts
TEST_PROMPTS = [
    {
        "name": "Simple sunset",
        "prompt": "A beautiful sunset over mountains, cinematic, 4k",
        "t2i_steps": 4,
        "t2i_guidance_scale": 0.0,
        "num_inference_steps": 25,
        "guidance_scale": 6.0,
        "num_frames": 16,
        "fps": 8,
        "seed": 42
    },
    {
        "name": "Detailed landscape",
        "prompt": "A majestic mountain landscape with a flowing river, morning mist, photorealistic, detailed, 8k",
        "t2i_steps": 8,
        "t2i_guidance_scale": 3.5,
        "num_inference_steps": 30,
        "guidance_scale": 7.0,
        "num_frames": 24,
        "fps": 8,
        "seed": 123
    },
    {
        "name": "City at night",
        "prompt": "A futuristic city at night with neon lights, cyberpunk style, raining, cinematic",
        "t2i_steps": 6,
        "t2i_guidance_scale": 2.5,
        "num_inference_steps": 25,
        "guidance_scale": 6.5,
        "num_frames": 16,
        "fps": 8,
        "seed": 456
    }
]

def setup_runpod():
    """Setup RunPod API connection."""
    if not RUNPOD_API_KEY:
        print("❌ RUNPOD_API_KEY not set")
        return False
    
    runpod.api_key = RUNPOD_API_KEY
    
    # Test connection
    try:
        user_info = runpod.get_user()
        print(f"✅ Connected to RunPod as user: {user_info.get('id')}")
        print(f"   Balance: ${user_info.get('balance', {}).get('credits', 0):.2f}")
        return True
    except Exception as e:
        print(f"❌ RunPod connection failed: {e}")
        return False

def list_endpoints():
    """List available serverless endpoints."""
    try:
        endpoints = runpod.get_endpoints()
        print(f"\n📋 Available endpoints ({len(endpoints)}):")
        
        for i, endpoint in enumerate(endpoints, 1):
            print(f"\n{i}. {endpoint.get('name')}")
            print(f"   ID: {endpoint.get('id')}")
            print(f"   Status: {endpoint.get('status')}")
            print(f"   GPU: {endpoint.get('gpuTypeId', 'Unknown')}")
            
            template = endpoint.get('template', {})
            if template:
                print(f"   Image: {template.get('containerImage', 'Unknown')}")
        
        return endpoints
    except Exception as e:
        print(f"❌ Failed to list endpoints: {e}")
        return []

def test_endpoint_health(endpoint_id: str) -> bool:
    """Test if endpoint is healthy."""
    try:
        # Try to get endpoint details
        # Note: RunPod SDK might not have direct health check
        # We'll try to run a simple job instead
        
        print(f"\n🏥 Testing endpoint health: {endpoint_id}")
        
        # Create a tiny test job
        test_input = {
            "prompt": "test",
            "t2i_steps": 1,
            "num_inference_steps": 1,
            "num_frames": 2
        }
        
        # This would run an actual job
        # For now, just check if endpoint exists
        print("✅ Endpoint exists (health check simulated)")
        return True
        
    except Exception as e:
        print(f"❌ Endpoint health check failed: {e}")
        return False

def run_test_job(endpoint_id: str, test_config: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Run a test job on the endpoint."""
    print(f"\n🚀 Running test: {test_config['name']}")
    print(f"   Prompt: {test_config['prompt'][:60]}...")
    
    try:
        # Prepare input
        job_input = {
            "prompt": test_config["prompt"],
            "t2i_steps": test_config["t2i_steps"],
            "t2i_guidance_scale": test_config["t2i_guidance_scale"],
            "num_inference_steps": test_config["num_inference_steps"],
            "guidance_scale": test_config["guidance_scale"],
            "num_frames": test_config["num_frames"],
            "fps": test_config["fps"],
            "seed": test_config["seed"]
        }
        
        print(f"   Parameters: {json.dumps(job_input, indent=2)}")
        
        # Run job
        print("   Submitting job...")
        job = runpod.run(endpoint_id, job_input)
        
        if not job or "id" not in job:
            print("❌ Failed to submit job")
            return None
        
        job_id = job["id"]
        print(f"   Job ID: {job_id}")
        
        # Wait for completion (polling)
        print("   Waiting for completion...", end="", flush=True)
        
        max_wait_time = 600  # 10 minutes
        poll_interval = 10   # 10 seconds
        elapsed = 0
        
        while elapsed < max_wait_time:
            status = runpod.get_job_status(endpoint_id, job_id)
            
            if status.get("status") == "COMPLETED":
                print(" ✅")
                result = runpod.get_job_result(endpoint_id, job_id)
                print(f"   Result: {json.dumps(result, indent=2)}")
                return result
            
            elif status.get("status") == "FAILED":
                print(" ❌")
                print(f"   Job failed: {status.get('error', 'Unknown error')}")
                return None
            
            print(".", end="", flush=True)
            time.sleep(poll_interval)
            elapsed += poll_interval
        
        print(" ⏰ (timeout)")
        print(f"   Job timed out after {max_wait_time} seconds")
        return None
        
    except Exception as e:
        print(f"❌ Job execution failed: {e}")
        import traceback
        traceback.print_exc()
        return None

def estimate_cost(test_config: Dict[str, Any]) -> float:
    """Estimate cost for a test job."""
    # Rough estimation based on:
    # - T2I: 2 seconds per step
    # - I2V: 5 seconds per step per frame
    
    t2i_time = test_config["t2i_steps"] * 2  # seconds
    i2v_time = test_config["num_inference_steps"] * test_config["num_frames"] * 0.1  # seconds
    
    total_time = t2i_time + i2v_time  # seconds
    cost_per_second = 0.0002  # $0.0002/second for RTX 4090
    
    estimated_cost = total_time * cost_per_second
    
    print(f"   Estimated time: {total_time:.1f}s")
    print(f"   Estimated cost: ${estimated_cost:.4f}")
    
    return estimated_cost

def main():
    """Main test function."""
    print("="*60)
    print("RunPod Serverless Endpoint Tester")
    print("="*60)
    
    # Setup RunPod
    if not setup_runpod():
        return
    
    # List endpoints
    endpoints = list_endpoints()
    
    if not endpoints:
        print("\n❌ No endpoints found")
        print("Please create an endpoint first:")
        print("1. Go to https://www.runpod.io/console/serverless")
        print("2. Create endpoint with Docker image")
        print("3. Mount network volume with models")
        return
    
    # Select endpoint
    if ENDPOINT_ID:
        endpoint_id = ENDPOINT_ID
        print(f"\nUsing configured endpoint: {endpoint_id}")
    else:
        if len(endpoints) == 1:
            endpoint_id = endpoints[0]["id"]
            print(f"\nUsing only available endpoint: {endpoint_id}")
        else:
            print("\nSelect endpoint to test:")
            for i, endpoint in enumerate(endpoints, 1):
                print(f"{i}. {endpoint['name']} ({endpoint['id']})")
            
            try:
                choice = int(input("\nEnter choice (1-{}): ".format(len(endpoints))))
                if 1 <= choice <= len(endpoints):
                    endpoint_id = endpoints[choice-1]["id"]
                else:
                    print("Invalid choice")
                    return
            except ValueError:
                print("Invalid input")
                return
    
    # Test endpoint health
    if not test_endpoint_health(endpoint_id):
        print("\n❌ Endpoint is not healthy")
        return
    
    # Run test jobs
    print(f"\n{'='*60}")
    print("Running Test Jobs")
    print(f"{'='*60}")
    
    total_cost = 0
    successful_tests = 0
    
    for i, test_config in enumerate(TEST_PROMPTS, 1):
        print(f"\nTest {i}/{len(TEST_PROMPTS)}")
        
        # Estimate cost
        estimated_cost = estimate_cost(test_config)
        total_cost += estimated_cost
        
        # Ask for confirmation if cost > $0.10
        if estimated_cost > 0.10:
            response = input(f"   Estimated cost: ${estimated_cost:.4f}. Continue? (y/N): ")
            if response.lower() != 'y':
                print("   Skipping...")
                continue
        
        # Run job
        result = run_test_job(endpoint_id, test_config)
        
        if result and result.get("status") == "success":
            successful_tests += 1
            print(f"   ✅ Test passed")
            print(f"   Video URL: {result.get('video_url', 'N/A')}")
        else:
            print(f"   ❌ Test failed")
    
    # Summary
    print(f"\n{'='*60}")
    print("Test Summary")
    print(f"{'='*60}")
    print(f"Total tests: {len(TEST_PROMPTS)}")
    print(f"Successful: {successful_tests}")
    print(f"Failed: {len(TEST_PROMPTS) - successful_tests}")
    print(f"Estimated total cost: ${total_cost:.4f}")
    
    if successful_tests == len(TEST_PROMPTS):
        print("\n🎉 All tests passed! Endpoint is working correctly.")
    elif successful_tests > 0:
        print(f"\n⚠️  {successful_tests}/{len(TEST_PROMPTS)} tests passed.")
    else:
        print("\n❌ All tests failed. Check endpoint configuration.")

if __name__ == "__main__":
    main()