#!/usr/bin/env python3
"""
Diagnostic script to test GPU detection in ProPainterAdapter.
Run this to verify multi-GPU support is working.
"""
import sys
import os

# Add project to path
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

print("="*60)
print("GPU DETECTION DIAGNOSTIC")
print("="*60)

# Test 1: Check CUDA_VISIBLE_DEVICES environment variable
print("\n1. Environment Variables:")
cuda_visible = os.environ.get('CUDA_VISIBLE_DEVICES', 'not set')
print(f"   CUDA_VISIBLE_DEVICES: {cuda_visible}")

# Test 2: PyTorch GPU detection
print("\n2. PyTorch GPU Detection:")
try:
    import torch
    print(f"   PyTorch version: {torch.__version__}")
    print(f"   CUDA available: {torch.cuda.is_available()}")
    
    if torch.cuda.is_available():
        # Force CUDA initialization
        torch.cuda.init()
        
        device_count = torch.cuda.device_count()
        print(f"   GPU count: {device_count}")
        
        for i in range(device_count):
            gpu_name = torch.cuda.get_device_name(i)
            gpu_props = torch.cuda.get_device_properties(i)
            gpu_mem_gb = gpu_props.total_memory / (1024**3)
            print(f"   GPU {i}: {gpu_name} ({gpu_mem_gb:.1f}GB)")
            
        # Test if we can allocate on each GPU
        print("\n3. GPU Allocation Test:")
        for i in range(device_count):
            try:
                with torch.cuda.device(i):
                    test_tensor = torch.zeros(100, 100, device=f'cuda:{i}')
                    print(f"   ✅ GPU {i}: Can allocate tensors")
                    del test_tensor
                    torch.cuda.empty_cache()
            except Exception as e:
                print(f"   ❌ GPU {i}: Allocation failed - {e}")
    else:
        print("   ⚠️  CUDA not available!")
        
except ImportError as e:
    print(f"   ❌ PyTorch not installed: {e}")
    sys.exit(1)

# Test 3: nvidia-smi verification
print("\n4. nvidia-smi GPU List:")
try:
    import subprocess
    result = subprocess.run(['nvidia-smi', '--list-gpus'], 
                          capture_output=True, text=True, check=True)
    for line in result.stdout.strip().split('\n'):
        print(f"   {line}")
except Exception as e:
    print(f"   ⚠️  nvidia-smi failed: {e}")

# Test 4: ProPainterAdapter detection
print("\n5. ProPainterAdapter GPU Detection:")
try:
    from src.infrastructure.inpainting.propainter_adapter import ProPainterAdapter
    adapter = ProPainterAdapter()
    print(f"   Detected GPUs: {adapter.num_gpus}")
    print(f"   GPU devices: {adapter.devices}")
    
    if adapter.num_gpus > 1:
        print(f"   ✅ Multi-GPU support: ENABLED")
        print(f"   🎯 Will use parallel processing for chunked videos")
    elif adapter.num_gpus == 1:
        print(f"   ⚠️  Single GPU mode (expected 2 GPUs)")
        print(f"   Possible issues:")
        print(f"      - CUDA_VISIBLE_DEVICES limits GPU visibility")
        print(f"      - PyTorch initialized before second GPU detected")
        print(f"      - Driver/CUDA issue")
    else:
        print(f"   ❌ No GPUs detected!")
        
except Exception as e:
    print(f"   ❌ ProPainterAdapter failed: {e}")
    import traceback
    traceback.print_exc()

print("\n" + "="*60)
print("DIAGNOSTIC COMPLETE")
print("="*60)

# Recommendations
if torch.cuda.is_available() and torch.cuda.device_count() == 1:
    print("\n⚠️  ISSUE DETECTED: Only 1 GPU visible")
    print("\nRecommendations:")
    print("  1. Check CUDA_VISIBLE_DEVICES is not set:")
    print("     $ echo $CUDA_VISIBLE_DEVICES")
    print("     (should be empty or '0,1')")
    print("")
    print("  2. Verify both GPUs are visible to nvidia-smi:")
    print("     $ nvidia-smi --list-gpus")
    print("")
    print("  3. Restart Python process after checking environment")
    print("")
    print("  4. If issue persists, add this before importing torch:")
    print("     import os")
    print("     os.environ['CUDA_VISIBLE_DEVICES'] = '0,1'")
elif torch.cuda.is_available() and torch.cuda.device_count() > 1:
    print("\n✅ Multi-GPU detection working correctly!")

