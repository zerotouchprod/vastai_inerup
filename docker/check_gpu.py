#!/usr/bin/env python3
"""
Check GPU availability and usage in Docker container.
"""

import torch
import sys
import os

def main():
    print("=" * 60)
    print("GPU/CPU Diagnostics")
    print("=" * 60)
    
    # Check PyTorch
    print(f"PyTorch version: {torch.__version__}")
    print(f"CUDA available: {torch.cuda.is_available()}")
    
    if torch.cuda.is_available():
        print(f"CUDA version: {torch.version.cuda}")
        print(f"Number of GPUs: {torch.cuda.device_count()}")
        
        for i in range(torch.cuda.device_count()):
            print(f"\nGPU {i}:")
            print(f"  Name: {torch.cuda.get_device_name(i)}")
            print(f"  Memory allocated: {torch.cuda.memory_allocated(i) / 1024**2:.2f} MB")
            print(f"  Memory cached: {torch.cuda.memory_reserved(i) / 1024**2:.2f} MB")
            print(f"  Total memory: {torch.cuda.get_device_properties(i).total_memory / 1024**3:.2f} GB")
    else:
        print("WARNING: CUDA not available! Running on CPU.")
        
    # Check environment variables
    print("\n" + "=" * 60)
    print("Environment Variables")
    print("=" * 60)
    gpu_env_vars = ['NVIDIA_VISIBLE_DEVICES', 'CUDA_VISIBLE_DEVICES', 'NVIDIA_DRIVER_CAPABILITIES']
    for var in gpu_env_vars:
        value = os.environ.get(var, 'Not set')
        print(f"{var}: {value}")
    
    # Check nvidia-smi
    print("\n" + "=" * 60)
    print("NVIDIA System Management Interface")
    print("=" * 60)
    try:
        import subprocess
        result = subprocess.run(['nvidia-smi'], capture_output=True, text=True)
        if result.returncode == 0:
            print("nvidia-smi output:")
            print(result.stdout[:1000])  # First 1000 chars
        else:
            print(f"nvidia-smi failed: {result.stderr}")
    except Exception as e:
        print(f"Cannot run nvidia-smi: {e}")
    
    print("\n" + "=" * 60)
    print("Diagnostics complete")
    print("=" * 60)
    
    return 0 if torch.cuda.is_available() else 1

if __name__ == '__main__':
    sys.exit(main())
