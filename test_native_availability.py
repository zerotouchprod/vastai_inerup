"""
Test script to check native processor availability.

This is expected to fail locally (no PyTorch/CUDA) but work in Docker containers.
"""

import sys
sys.path.insert(0, 'src')

from infrastructure.processors.rife.native_wrapper import RIFENativeWrapper
from infrastructure.processors.realesrgan.native_wrapper import RealESRGANNativeWrapper

print("=" * 70)
print("Native Processor Availability Check")
print("=" * 70)
print()

# Check RIFE
print("1. RIFE Native Wrapper")
print(f"   is_available: {RIFENativeWrapper.is_available()}")
print()

# Check Real-ESRGAN
print("2. Real-ESRGAN Native Wrapper")
print(f"   is_available: {RealESRGANNativeWrapper.is_available()}")
print()

# Check PyTorch
print("3. PyTorch Check")
try:
    import torch
    print(f"   ✓ PyTorch installed: {torch.__version__}")
    print(f"   CUDA available: {torch.cuda.is_available()}")
    if torch.cuda.is_available():
        print(f"   CUDA device: {torch.cuda.get_device_name(0)}")
except ImportError:
    print("   ✗ PyTorch not installed (expected on local dev machine)")
print()

print("=" * 70)
print("NOTES:")
print("=" * 70)
print("• Native processors require PyTorch + CUDA")
print("• This is only available in Docker containers on Vast.ai")
print("• Local development uses shell wrapper fallbacks")
print("• This is EXPECTED BEHAVIOR - not a bug!")
print("=" * 70)

