#!/usr/bin/env python3
"""
Simple GPU / PyTorch verification script for container images.
Run inside the built image to confirm CUDA / PyTorch / device compatibility.
Exits with code 0 on success, non-zero on failure.
"""
import sys

try:
    import torch
except Exception as e:
    print("ERROR: failed to import torch:", e)
    sys.exit(2)

print("Torch version:", torch.__version__)
print("CUDA available:", torch.cuda.is_available())
if torch.cuda.is_available():
    try:
        dev = torch.device('cuda:0')
        name = torch.cuda.get_device_name(0)
        cc_major = torch.cuda.get_device_capability(0)[0]
        cc_minor = torch.cuda.get_device_capability(0)[1]
        print(f"Device 0: {name} (compute capability {cc_major}.{cc_minor})")
        # small test tensor to ensure ops run on GPU
        x = torch.randn(4, 4, device=dev)
        y = x * 2.0
        print("Tensor op on GPU succeeded, sample:", y.flatten()[:4].cpu().numpy())
    except Exception as e:
        print("ERROR: failed to run tensor op on GPU:", e)
        sys.exit(3)
else:
    print("CUDA not available - check drivers and PyTorch build")
    sys.exit(1)

print("OK: GPU test passed")
sys.exit(0)

